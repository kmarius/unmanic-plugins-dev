import sqlite3
import os
import threading
import time
from typing import Mapping, Tuple, Callable

from unmanic.libs import common

from . import logger, PLUGIN_ID

DB_PATH = os.path.join(common.get_home_dir(), ".unmanic",
                       "userdata", PLUGIN_ID, "timestamps.db")

_local = threading.local()


# NOTE: only reuse in short-lived threads like FileTester
def _get_connection(reuse_connection=False) -> sqlite3.Connection:
    if reuse_connection:
        if not hasattr(_local, "connection"):
            _local.connection = sqlite3.connect(DB_PATH)
        return _local.connection
    else:
        return sqlite3.connect(DB_PATH)


def _check_column_exists(conn: sqlite3.Connection, table_name: str, column_name: str):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    return any(column[1] == column_name for column in columns)


# check the database table, create it if it doesn't exist.
# migration for the addition of a column consists of dropping the table
def init():
    if not os.path.exists(os.path.dirname(DB_PATH)):
        os.makedirs(os.path.dirname(DB_PATH))

    # attempt to migrate old database from the sibling plugin
    # remove this a year after discontinuing the other plugin
    if not os.path.exists(DB_PATH):
        old_db = os.path.join(common.get_home_dir(), ".unmanic",
                              "userdata", "kmarius_incremental_scan_db", "timestamps.db")
        if os.path.exists(old_db):
            logger.info(f"Migrating database from kmarius_incremental_scan_db")
            os.rename(old_db, DB_PATH)

    conn = _get_connection()
    with conn:
        cur = conn.cursor()
        if not _check_column_exists(conn, "timestamps", "library_id"):
            logger.info("Table 'timestamps' does not exists or is missing the 'library_id' column. (Re-)creating...")
            cur.execute("DROP TABLE IF EXISTS timestamps")

        cur.execute('''
                    CREATE TABLE IF NOT EXISTS timestamps
                    (
                        library_id  INTEGER NULL,
                        path        TEXT    NOT NULL,
                        mtime       INTEGER NOT NULL,
                        last_update INTEGER NOT NULL,
                        PRIMARY KEY (library_id, path)
                    )''')

        if not _check_column_exists(conn, "timestamps", "last_update"):
            logger.info('Creating missing last_update column in table timestamps')
            cur.execute('ALTER TABLE timestamps ADD COLUMN last_update INTEGER DEFAULT 0')
            cur.execute('UPDATE timestamps SET last_update = mtime')

        cur.execute('CREATE INDEX IF NOT EXISTS idx_last_update ON timestamps (last_update)')
    conn.close()


def put(library_id: int, path: str, mtime: int):
    conn = _get_connection()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute('''
                INSERT INTO timestamps (library_id, path, mtime, last_update)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(library_id, path) DO UPDATE SET (mtime, last_update) = (EXCLUDED.mtime, EXCLUDED.last_update)
                ''', (library_id, path, mtime, now))
    conn.commit()


def put_many(values: list[Tuple[int, str, int]]):
    """list of tuples: (library_id, path, mtime)"""
    conn = _get_connection()
    cur = conn.cursor()
    now = int(time.time())
    values = [value + (now,) for value in values]
    with conn:
        cur.executemany('''
                        INSERT INTO timestamps (library_id, path, mtime, last_update)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(library_id, path)
                            DO UPDATE SET (mtime, last_update) = (EXCLUDED.mtime, EXCLUDED.last_update)
                        ''', values)
        conn.commit()


def get(library_id: int, path: str, reuse_connection=False):
    conn = _get_connection(reuse_connection)
    cur = conn.cursor()
    cur.execute("SELECT mtime FROM timestamps WHERE library_id = ? AND path = ?", (library_id, path))
    row = cur.fetchone()
    mtime = row[0] if row else None
    return mtime


# we only allow batch loading with fixed library_id
def get_many(library_id: int, paths: list[str]):
    conn = _get_connection()
    with conn:
        cur = conn.cursor()
        mtimes = []

        # I tested this with a temp relation instead of a loop and int was faster at > 15 items per query
        for path in paths:
            cur.execute(
                "SELECT mtime FROM timestamps WHERE library_id = ? AND path = ?", (library_id, path))
            row = cur.fetchone()
            mtimes.append(row[0] if row else None)
    return mtimes


def reset_oldest(library_id: int, fraction: float) -> list[str]:
    """Does not modify last_update"""
    if fraction <= 0:
        return []
    conn = _get_connection()
    with conn:
        cur = conn.cursor()
        cur.execute(f'SELECT count(*) FROM timestamps WHERE library_id = ?', (library_id,))
        num_entries = cur.fetchone()[0]

        limit = int(fraction * num_entries)
        limit = max(1, min(limit, num_entries))

        cur.execute('''
                    SELECT path, library_id
                    FROM timestamps
                    WHERE library_id = ?
                    ORDER BY last_update ASC
                    LIMIT ?
                    ''', (library_id, limit))
        rows = cur.fetchall()
        cur.execute(
            f'''
            UPDATE timestamps SET mtime = 0 
            WHERE rowid IN (SELECT rowid FROM timestamps WHERE library_id = ? ORDER BY last_update ASC LIMIT ?)
            ''',
            (library_id, limit))
        conn.commit()
        return rows


def get_all_paths(library_id: int = None) -> list[str]:
    conn = _get_connection()
    cur = conn.cursor()
    if library_id:
        cur.execute('''
                    SELECT path
                    FROM timestamps
                    WHERE library_id = ?
                    ''', (library_id,))
    else:
        cur.execute('SELECT DISTINCT path FROM timestamps')
    paths = [path[0] for path in cur.fetchall()]
    conn.close()
    return paths


# we directly construct the map here instead of returning a list and creating the map from that
def get_all(library_id: int) -> Mapping[str, int]:
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute('''
                SELECT path, mtime
                FROM timestamps
                WHERE library_id = ?
                ''', (library_id,))
    return dict(cur)


def remove_paths(library_id: int, paths: list[str]):
    conn = _get_connection()
    cur = conn.cursor()
    # one by one is good enough for now, I don't think we can use CTEs from python
    with conn:
        for path in paths:
            cur.execute('''
                        DELETE
                        FROM timestamps
                        WHERE library_id = ?
                          AND path = ?
                        ''', (library_id, path))
        conn.commit()


def check_oldest(library_id: int, fraction: float, callback: Callable[[str], bool], set_last_update=True) -> int:
    conn = _get_connection()
    cur = conn.cursor()

    cur.execute('SELECT count(*) FROM timestamps WHERE library_id = ?', (library_id,))
    num_entries = cur.fetchone()[0]
    limit = int(fraction * num_entries)
    limit = max(1, min(limit, num_entries))

    cur.execute('''
                SELECT path, rowid
                FROM timestamps
                WHERE library_id = ?
                ORDER BY last_update ASC
                LIMIT ?
                ''', (library_id, limit,))

    delete_row_ids = []
    keep_row_ids = []
    for row in cur:
        if not callback(row[0]):
            delete_row_ids.append((row[1],))
        else:
            keep_row_ids.append((int(time.time()), row[1]))

    logger.info(f"delete {delete_row_ids}")
    logger.info(f"keep {keep_row_ids}")

    with conn:
        cur.executemany('DELETE FROM timestamps WHERE rowid = ?', delete_row_ids)
        if set_last_update:
            cur.executemany('UPDATE timestamps SET last_update = ? WHERE rowid = ?', keep_row_ids)
        conn.commit()

    return len(delete_row_ids)