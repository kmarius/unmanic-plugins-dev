import sqlite3
import os
import logging
import json
from typing import Optional

from unmanic.libs import common

# TODO: function to clean up orphans
# TODO: shouldn't have to create a new connection for every operation

logger = logging.getLogger("Unmanic.Plugin.kmarius_library")

DB_PATH = os.path.join(common.get_home_dir(), ".unmanic",
                       "userdata", "kmarius_library", "metadata.db")


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    return conn


def init(tables: list[str]):
    if not os.path.exists(os.path.dirname(DB_PATH)):
        os.makedirs(os.path.dirname(DB_PATH))

    conn = _get_connection()
    cur = conn.cursor()
    for table in tables:
        cur.execute(f'''
                       CREATE TABLE IF NOT EXISTS {table} (
                           path TEXT PRIMARY KEY,
                           mtime INTEGER NOT NULL,
                           data TEXT DEFAULT NULL
                       )''')
    conn.commit()
    conn.close()


def lookup(table: str, path: str, mtime: int = None) -> Optional[dict]:
    conn = _get_connection()
    cur = conn.cursor()
    if mtime:
        cur.execute(f"SELECT data FROM {table} WHERE path = ? AND mtime = ? LIMIT 1",
                    (path, mtime))
    else:
        cur.execute(f"SELECT data FROM {table} WHERE path = ? LIMIT 1",
                    (path,))
    row = cur.fetchone()
    conn.close()
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


def put(table: str, path: str, mtime: int, data: dict):
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute(f'''
                INSERT INTO {table} (path, mtime, data)
                VALUES (?, ?, ?) 
                ON CONFLICT (path) DO
                UPDATE SET
                    (mtime, data) = (EXCLUDED.mtime, EXCLUDED.data)
                ''', (path, mtime, json.dumps(data)))
    conn.commit()
    conn.close()