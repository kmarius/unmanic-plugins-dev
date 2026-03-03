import sqlite3
import os
import json
import threading
import time
from typing import Optional, Callable

from unmanic.libs import common
from . import PLUGIN_ID, logger

# TODO: function to clean up orphans

DB_PATH = os.path.join(common.get_home_dir(), ".unmanic", "userdata", PLUGIN_ID, "metadata.db")

_local = threading.local()


def _check_column_exists(conn: sqlite3.Connection, table_name: str, column_name: str):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    return any(column[1] == column_name for column in columns)


# NOTE: only reuse in short-lived threads like FileTester
def _get_connection(reuse_connection: bool = False) -> sqlite3.Connection:
    if reuse_connection:
        if not hasattr(_local, "connection"):
            _local.connection = sqlite3.connect(DB_PATH)
        return _local.connection
    else:
        return sqlite3.connect(DB_PATH)


def _perform_maintenance(cur: sqlite3.Cursor):
    mode = os.getenv("UNMANIC_SQLITE_MAINTENANCE")
    if not mode:
        mode = "basic"

    if mode not in ["off", "basic", "full"]:
        logger.error(f"Unknown UNMANIC_SQLITE_MAINTENANCE mode '{mode}'")
        return

    if mode == "off":
        return

    cur.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    cur.execute('PRAGMA optimize')
    if mode == "full":
        cur.execute('VACUUM')


def init(tables: list[str]):
    if not os.path.exists(os.path.dirname(DB_PATH)):
        os.makedirs(os.path.dirname(DB_PATH))

    with _get_connection() as conn:
        cur = conn.cursor()
        for table in tables:
            cur.execute(f'''
                           CREATE TABLE IF NOT EXISTS {table} (
                               path TEXT PRIMARY KEY,
                               mtime INTEGER NOT NULL,
                               last_update INTEGER NOT NULL,
                               data TEXT DEFAULT NULL
                           )''')

            if not _check_column_exists(conn, table, "last_update"):
                logger.info(f'Creating missing last_update column in table {table}')
                cur.execute(f'ALTER TABLE {table} ADD COLUMN last_update INTEGER NOT NULL DEFAULT 0')
                cur.execute(f'UPDATE {table} SET last_update = mtime')

            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_last_update ON {table} (last_update)')

        _perform_maintenance(cur)


def get(table: str, path: str, mtime: int = None, reuse_connection=False) -> Optional[dict]:
    with _get_connection(reuse_connection) as conn:
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
    with _get_connection() as conn:
        cur = conn.cursor()
        if mtime:
            [[count]] = cur.execute(f"SELECT COUNT(*) FROM {table} WHERE path = ? AND mtime = ? LIMIT 1",
                                    (path, mtime))
        else:
            [[count]] = cur.execute(f"SELECT COUNT(*) FROM {table} WHERE path = ? LIMIT 1",
                                    (path,))
        return count > 0


def put(table: str, path: str, mtime: int, data: dict, reuse_connection=False) -> None:
    last_update = int(time.time())
    data = json.dumps(data)
    with _get_connection(reuse_connection) as conn:
        cur = conn.cursor()
        cur.execute(f'''
                    INSERT INTO {table} (path, mtime, last_update, data)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (path) DO
                    UPDATE SET
                        (mtime, last_update, data) = (EXCLUDED.mtime, EXCLUDED.last_update, EXCLUDED.data)
                    ''', (path, mtime, last_update, data))


def get_all_paths(table: str) -> list[str]:
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT path FROM {table}')
        return [path for path, in cur]


def remove_paths(table: str, paths: list[str]):
    with _get_connection() as conn:
        cur = conn.cursor()
        for path in paths:
            cur.execute(f'DELETE FROM {table} WHERE path = ?', (path,))


def check_oldest(table: str, fraction: float, callback: Callable[[str], bool]) -> int:
    with _get_connection() as conn:
        cur = conn.cursor()

        [[num_rows]] = cur.execute(f'SELECT COUNT(*) FROM {table}')
        limit = max(1, int(fraction * num_rows))

        cur.execute(f'''
                    SELECT path, rowid
                    FROM {table}
                    ORDER BY last_update 
                    LIMIT ?
                    ''', (limit,))

        delete_row_ids = []
        keep_row_ids = []
        for path, rowid in cur:
            if callback(path):
                keep_row_ids.append((int(time.time()), rowid))
            else:
                delete_row_ids.append((rowid,))

        cur.executemany(f'UPDATE {table} SET last_update = ? WHERE rowid = ?', keep_row_ids)
        cur.executemany(f'DELETE FROM {table} WHERE rowid = ?', delete_row_ids)

        return cur.rowcount