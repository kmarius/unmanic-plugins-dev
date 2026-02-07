import sqlite3
import os
import json
import threading
import time
from typing import Optional, Callable

from unmanic.libs import common
from . import PLUGIN_ID, logger

# TODO: function to clean up orphans

DB_PATH = os.path.join(common.get_home_dir(), ".unmanic",
                       "userdata", PLUGIN_ID, "metadata.db")

local = threading.local()


def _check_column_exists(conn: sqlite3.Connection, table_name: str, column_name: str):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    return any(column[1] == column_name for column in columns)


# NOTE: only reuse in short-lived threads like FileTester
def _get_connection(reuse_connection=False) -> sqlite3.Connection:
    if reuse_connection:
        if not hasattr(local, "connection"):
            local.connection = sqlite3.connect(DB_PATH)

        return local.connection
    else:
        return sqlite3.connect(DB_PATH)


def init(tables: list[str]):
    if not os.path.exists(os.path.dirname(DB_PATH)):
        os.makedirs(os.path.dirname(DB_PATH))

    conn = _get_connection()
    with conn:
        cur = conn.cursor()
        for table in tables:
            cur.execute(f'''
                           CREATE TABLE IF NOT EXISTS {table} (
                               path TEXT PRIMARY KEY,
                               mtime INTEGER NOT NULL,
                               last_update INTEGER NOT NULL,
                               data TEXT DEFAULT NULL
                           )''')

            if False and _check_column_exists(conn, table, "last_update"):
                cur.execute(f'''DROP INDEX IF EXISTS idx_{table}_last_update''')
                cur.execute(f'''alter table {table} DROP column last_update''')

            if not _check_column_exists(conn, table, "last_update"):
                logger.info(f'Creating missing last_update column in table {table}')
                cur.execute(f'ALTER TABLE {table} ADD COLUMN last_update INTEGER NOT NULL DEFAULT 0')
                cur.execute(f'UPDATE {table} SET last_update = mtime')
                cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_last_update ON {table} (last_update)')
        conn.commit()


def get(table: str, path: str, mtime: int = None, reuse_connection=False) -> Optional[dict]:
    conn = _get_connection(reuse_connection=reuse_connection)
    cur = conn.cursor()
    if mtime:
        cur.execute(f"SELECT data FROM {table} WHERE path = ? AND mtime = ? LIMIT 1",
                    (path, mtime))
    else:
        cur.execute(f"SELECT data FROM {table} WHERE path = ? LIMIT 1",
                    (path,))
    row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    return json.loads(row[0])


def exists(table: str, path: str, mtime: int = None) -> bool:
    conn = _get_connection()
    cur = conn.cursor()
    if mtime:
        [[count]] = cur.execute(f"SELECT COUNT(*) FROM {table} WHERE path = ? AND mtime = ? LIMIT 1",
                                (path, mtime))
    else:
        [[count]] = cur.execute(f"SELECT COUNT(*) FROM {table} WHERE path = ? LIMIT 1",
                                (path,))
    conn.close()
    return count > 0


def put(table: str, path: str, mtime: int, data: dict, reuse_connection=False) -> None:
    conn = _get_connection(reuse_connection=reuse_connection)
    last_update = int(time.time())
    data = json.dumps(data)
    with conn:
        cur = conn.cursor()
        cur.execute(f'''
                    INSERT INTO {table} (path, mtime, last_update, data)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (path) DO
                    UPDATE SET
                        (mtime, last_update, data) = (EXCLUDED.mtime, EXCLUDED.last_update, EXCLUDED.data)
                    ''', (path, mtime, last_update, data))
        conn.commit()


def get_all_paths(table: str) -> list[str]:
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute(f'SELECT path FROM {table}')
    paths = [path[0] for path in cur.fetchall()]
    conn.close()
    return paths


def remove_paths(table: str, paths: list[str]):
    conn = _get_connection()
    with conn:
        cur = conn.cursor()
        for path in paths:
            cur.execute(f'DELETE FROM {table} WHERE path = ?', (path,))
        conn.commit()
    conn.close()


def check_oldest(table: str, fraction: float, callback: Callable[[str], bool]) -> int:
    conn = _get_connection()
    cur = conn.cursor()

    cur.execute(f'SELECT count(*) FROM {table}')
    num_entries = cur.fetchone()[0]
    limit = int(fraction * num_entries)
    limit = max(1, min(limit, num_entries))

    cur.execute(f'''
                SELECT path, rowid
                FROM {table}
                ORDER BY last_update ASC
                LIMIT ?
                ''', (limit,))

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
        cur.executemany(f'DELETE FROM {table} WHERE rowid = ?', delete_row_ids)
        cur.executemany(f'UPDATE {table} SET last_update = ? WHERE rowid = ?', keep_row_ids)
        conn.commit()

    return len(delete_row_ids)