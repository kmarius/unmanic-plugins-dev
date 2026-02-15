import logging
from typing import Collection

PLUGIN_ID = "kmarius_library"

logger = logging.getLogger(f"Unmanic.Plugin.{PLUGIN_ID}")

# this dict holds all files (per-library) that were sent down the file-test pipeline
# we remove them, once a file is added to the pending queue. Of all files that remain
# we update the timestamp once the scan completes.
_files_tested = {}


def add_file_tested(library_id: int, path: str):
    if library_id not in _files_tested:
        _files_tested[library_id] = set()
    _files_tested[library_id].add(path)


def remove_file_tested(library_id: int, path: str):
    if library_id not in _files_tested:
        _files_tested[library_id] = set()
    if path in _files_tested[library_id]:
        _files_tested[library_id].remove(path)


def get_files_tested(library_id: int, clear=True) -> Collection[str]:
    if library_id in _files_tested:
        res = _files_tested[library_id]
        if clear:
            del (_files_tested[library_id])
    else:
        res = []
    return res