import os
import sqlite3
import threading
import time
from typing import List, Tuple

from unmanic.libs import common

from . import logger, PLUGIN_ID

DB_PATH = os.path.join(common.get_home_dir(), '.unmanic', 'userdata', PLUGIN_ID, 'issues.db')

_local = threading.local()


def SQL(sql):
    def decorator(func):
        def wrapper(*args, **kwargs):
            with _get_connection(kwargs.get('reuse_connection')) as conn:
                cur = conn.cursor()
                cur.execute(sql, tuple(args))

        return wrapper

    return decorator


class ExplainCursor(sqlite3.Cursor):
    _EXPLAIN = True

    def __init__(self, *args, **kwargs):
        super(ExplainCursor, self).__init__(*args, **kwargs)

    def execute(self, sql: str, parameters=()):
        if ExplainCursor._EXPLAIN:
            logger.info('Explaining: ' + sql + " " + str(parameters))
            for *_, ex in super().execute('EXPLAIN QUERY PLAN ' + sql, parameters):
                logger.info(ex)
        return super().execute(sql, parameters)


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
    cursor.execute(f'PRAGMA table_info({table_name})')
    columns = cursor.fetchall()
    return any(column[1] == column_name for column in columns)


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


def _init():
    if not os.path.exists(os.path.dirname(DB_PATH)):
        os.makedirs(os.path.dirname(DB_PATH))

    with _get_connection() as conn:
        cur = conn.cursor()
        if not _check_column_exists(conn, 'issues', 'name'):
            cur.execute('DROP TABLE IF EXISTS issues')

        cur.execute('''
                    CREATE TABLE IF NOT EXISTS issues
                    (
                        library_id  INTEGER NULL,
                        path        TEXT    NOT NULL,
                        name        TEXT    NOT NULL,
                        mtime       INTEGER NOT NULL,
                        last_update INTEGER NOT NULL,
                        issues      TEXT    NOT NULL,
                        resolved    INTEGER NOT NULL,
                        PRIMARY KEY (library_id, path)
                    )''')

        cur.execute('CREATE INDEX IF NOT EXISTS idx_last_update ON issues (last_update)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_issues ON issues (issues)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_name ON issues (name)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_resolved_name ON issues (resolved, name)')

        _perform_maintenance(cur)


_init()


def insert(library_id: int, path: str, mtime: int, issues: str):
    now = int(time.time())
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute('''
                    INSERT INTO issues (library_id, path, name, mtime, last_update, issues, resolved)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(library_id, path) DO UPDATE
                        SET (name, mtime, last_update, issues, resolved) = (EXCLUDED.name,
                                                                            EXCLUDED.mtime,
                                                                            EXCLUDED.last_update,
                                                                            EXCLUDED.issues,
                                                                            EXCLUDED.resolved)
                    ''', (library_id, path, os.path.basename(path), mtime, now, issues, 0))


def append_issues(library_id: int, path: str, mtime: int, issues: str):
    now = int(time.time())
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute('''SELECT issues
                       FROM issues
                       WHERE library_id = ?
                         and path = ?''', (library_id, path))
        row = cur.fetchone()
        if row:
            current_issues = row[0].split(',')
            initial_len = len(current_issues)
            for issue in issues.split(','):
                if not issue in current_issues:
                    current_issues.append(issue)
            if len(current_issues) > initial_len:
                cur.execute('''UPDATE issues
                               SET issues = ?
                               WHERE library_id = ?
                                 AND path = ?''', (','.join(current_issues), library_id, path))
            return
    insert(library_id, path, mtime, issues)


@SQL('UPDATE issues SET resolved = ? WHERE rowid = ?')
def resolve(resolved: bool, rowid: int):
    pass


@SQL('DELETE FROM issues WHERE library_id = ? AND path = ?')
def delete(library_id: int, path: str, reuse_connection=False):
    pass


@SQL('UPDATE issues SET mtime = ? WHERE library_id = ? AND path = ?')
def update_mtime(mtime: int, library_id: int, path: str):
    pass


def rename(library_id: int, path: str, new_path: str, mtime: int):
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute('SELECT issues FROM issues WHERE library_id = ? AND path = ?', (library_id, path))
        row = cur.fetchone()
        if not row:
            return
    delete(library_id, path)
    insert(library_id, new_path, mtime, row[0])


def query(library_id: int = None, offset: int = None, limit: int = None, order=None, search: list = None,
          columns=None, fetch_total=False, resolved: int = None, row_factory=None) -> Tuple[List[Tuple], int, int] | \
                                                                                      List[Tuple]:
    valid_columns = ['library_id', 'path', 'name', 'mtime', 'last_update', 'issues', 'resolved', 'rowid']
    if columns is None:
        columns = valid_columns
    else:
        for column in columns:
            if not column in valid_columns:
                raise ValueError(f"Invalid column '{column}'")

    query_string = f'SELECT {', '.join(columns)} FROM issues'
    count_query_string = 'SELECT COUNT(*) FROM issues'
    parameters = ()
    total, filtered = 0, 0

    sep = ' WHERE'
    if library_id is not None:
        count_query_string += f'{sep} library_id = ?'
        query_string += f'{sep} library_id = ?'
        sep = ' AND'
        parameters += (library_id,)

    if resolved is not None:
        count_query_string += f'{sep} resolved = ?'
        query_string += f'{sep} resolved = ?'
        sep = ' AND'
        parameters += (resolved,)

    with _get_connection() as conn:
        cur = conn.cursor()

        if fetch_total:
            [[total]] = cur.execute(count_query_string, parameters)
            filtered = total

        if search:
            for s in search:
                column = columns[s.get('column')]
                parameters += (f'%{s.get('value')}%',)
                query_string += f'{sep} {column} LIKE ?'
                count_query_string += f'{sep} {column} LIKE ?'
                sep = ' AND'
            if fetch_total:
                [[filtered]] = cur.execute(count_query_string, parameters)

        if order is not None:
            query_string += f' ORDER BY {columns[order.get('column')]}'
            if order.get('dir') == 'desc':
                query_string += ' DESC'

        if limit is not None:
            query_string += f' LIMIT {limit}'

        if offset is not None:
            query_string += f' OFFSET {offset}'

        if row_factory is not None:
            cur.row_factory = row_factory
        cur.execute(query_string, parameters)

        if fetch_total:
            return cur.fetchall(), total, filtered

        return cur.fetchall()