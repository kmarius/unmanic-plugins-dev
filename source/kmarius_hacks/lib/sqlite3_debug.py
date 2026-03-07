import sqlite3
import time
import traceback

from unmanic.libs.logs import UnmanicLogging

_window = []
_window_max_duration = 60.0
_last_print = 0
_start = time.time()
_start_timeout = 4.0  # skip a bunch of initialization queries

enable_counting = True
enable_logging = False
enable_explain = False
explain_next_query = False  # explain the next query
enable_traceback = False


class DebugCursor(sqlite3.Cursor):
    _logger = UnmanicLogging.get_logger('DebugCursor')

    def execute(self, sql, params=()):
        global _window, _last_print, explain_next_query
        if enable_logging:
            self._logger.info(sql[:80])
        if enable_traceback:
            for line in traceback.format_stack():
                self._logger.info(line.strip())
        if enable_explain or enable_explain_next:
            if enable_explain_next:
                enable_explain_next = False
            self._logger.info('---')
            if not enable_logging:
                self._logger.info(sql)
            for *_, ex in super().execute('EXPLAIN QUERY PLAN ' + sql, params):
                self._logger.info(ex)
        if enable_counting:
            now = time.time()
            if now - _start > _start_timeout:
                _window.append(now)
                if now - _last_print >= 1:
                    while now - _window[0] >= _window_max_duration:
                        _window.pop(0)
                    size = min(_window_max_duration, now - _start - _start_timeout)
                    if size > 0:
                        self._logger.info(f'{len(_window) / size:.2f} queries/s')
                    _last_print = now
        return super(DebugCursor, self).execute(sql, params)


class DebugConn(sqlite3.Connection):
    def cursor(self, factory=None):
        return super(DebugConn, self).cursor(DebugCursor)


original_connect = sqlite3.connect


def connect(*args, **kwargs):
    kwargs['factory'] = DebugConn
    return original_connect(*args, **kwargs)


sqlite3.connect = connect