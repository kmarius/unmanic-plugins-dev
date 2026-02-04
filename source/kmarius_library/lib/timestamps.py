import sqlite3
import os
import time

from threading import local
from typing import Mapping, Tuple

from unmanic.libs import common
from . import logger, PLUGIN_ID

DB_PATH = os.path.join(common.get_home_dir(), ".unmanic",
                       "userdata", PLUGIN_ID, "timestamps.db")

if not os.path.exists(os.path.dirname(DB_PATH)):
    os.makedirs(os.path.dirname(DB_PATH))


def check_column_exists(conn: sqlite3.Connection, table_name: str, column_name: str):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    return any(column[1] == column_name for column in columns)


# check the database table, create it if it doesn't exist.
# migration for the addition of a column consists of dropping the table
def init():
    # attempt to migrate old database from the sibling plugin
    # remove this a year after discontinuing the other plugin
    if not os.path.exists(DB_PATH):
        old_db = os.path.join(common.get_home_dir(), ".unmanic",
                              "userdata", "kmarius_incremental_scan_db", "timestamps.db")
        if os.path.exists(old_db):
            logger.info(f"Migrating database from kmarius_incremental_scan_db")
            os.rename(old_db, DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    with conn:
        cursor = conn.cursor()
        if not check_column_exists(conn, "timestamps", "library_id"):
            logger.info(
                "Table 'timestamps' does not exists or is missing the 'library_id' column. (Re-)creating...")
            cursor.execute("DROP TABLE IF EXISTS timestamps")

        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS timestamps
                       (
                           library_id  INTEGER NULL,
                           path        TEXT    NOT NULL,
                           mtime       INTEGER NOT NULL,
                           last_update INTEGER,
                           PRIMARY KEY (library_id, path)
                       )''')

        if not check_column_exists(conn, "timestamps", "last_update"):
            logger.info('table is missing last_update column')
            cursor.execute('''
                           ALTER TABLE timestamps
                               ADD COLUMN last_update INTEGER
                           ''')
            cursor.execute('''
                           UPDATE timestamps
                           SET last_update = mtime
                           ''')

        cursor.execute('''
                       CREATE INDEX IF NOT EXISTS idx_last_update ON timestamps (last_update)
                       ''')

    conn.close()


threadlocal = local()


# we only reuse connection in when file testing, because we currently can't close connections after
# the scan finishes, these will get closed when going out of scope
# other threads, such as the post-processor will get a single use connection
def _get_connection(reuse_connection=False) -> sqlite3.Connection:
    if reuse_connection:
        if not hasattr(threadlocal, "connection"):
            threadlocal.connection = sqlite3.connect(DB_PATH)

        return threadlocal.connection
    else:
        return sqlite3.connect(DB_PATH)


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
    conn = _get_connection()
    cur = conn.cursor()
    now = int(time.time())
    values = [value + (now,) for value in values]
    cur.executemany('''
                    INSERT INTO timestamps (library_id, path, mtime, last_update)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(library_id, path) DO UPDATE SET (mtime, last_update) = (EXCLUDED.mtime, EXCLUDED.last_update)
                    ''', values)
    conn.commit()


def get(library_id: int, path: str, reuse_connection=False):
    conn = _get_connection(reuse_connection)
    cur = conn.cursor()
    cur.execute(
        "SELECT mtime FROM timestamps WHERE library_id = ? AND path = ?", (library_id, path))
    row = cur.fetchone()
    mtime = row[0] if row else None
    return mtime


def get_num_entries(library_id: int = None) -> int:
    conn = _get_connection()
    cur = conn.cursor()
    if library_id:
        cur.execute('''SELECT count(*)
                       FROM timestamps
                       WHERE library_id = ?''', (library_id,))
    else:
        cur.execute('''SELECT count(*)
                       FROM timestamps''')
    return cur.fetchone()[0]


def reset_oldest(library_id: int, n: int) -> list[str]:
    conn = _get_connection()
    with (conn):
        cur = conn.cursor()
        cur.execute('''
                    SELECT path, library_id
                    FROM timestamps
                    WHERE library_id = ?
                    ORDER BY last_update ASC
                    LIMIT ?
                    ''', (library_id, n))
        rows = cur.fetchall()
        cur.execute(
            f'''
            UPDATE timestamps SET mtime = 0 WHERE rowid IN (SELECT rowid FROM timestamps WHERE library_id = ? ORDER BY last_update ASC LIMIT ?)
            ''',
            (library_id, n))
        conn.commit()
        return rows
        # [row[0] for row in rows]


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
        cur.execute('''SELECT DISTINCT path
                       FROM timestamps''')
    paths = [path[0] for path in cur.fetchall()]
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