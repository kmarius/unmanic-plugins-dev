import sqlite3
import os

from unmanic.libs import common

# TODO: function to clean up orphans

DB_PATH = os.path.join(common.get_home_dir(), ".unmanic",
                       "userdata", "kmarius_incremental_scan_db", "timestamps.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    setup(conn)
    return conn


def setup(conn):
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS timestamps (
           path TEXT PRIMARY KEY,
           mtime INTEGER NOT NULL
        )''')


def store_timestamp(path, mtime):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO timestamps (path, mtime)
        VALUES (?, ?) 
        ON CONFLICT(path) DO UPDATE SET
            mtime = excluded.mtime
        ''', (path, mtime))
    conn.commit()
    conn.close()


def load_timestamp(path):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT mtime FROM timestamps WHERE path = ?", (path,))
    row = cur.fetchone()
    mtime = row[0] if row else None
    conn.close()
    return mtime