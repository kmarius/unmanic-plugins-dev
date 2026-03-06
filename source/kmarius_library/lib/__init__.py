import logging
from typing import Dict, Set

PLUGIN_ID = "kmarius_library"

logger = logging.getLogger(f"Unmanic.Plugin.{PLUGIN_ID}")

# this dict holds all files with their current timestamp (per-library) that were sent down the file-test pipeline
# we remove them, once a file is added to the pending queue. Of all files that remain
# we update the timestamp once the scan completes.
_files_tested: Dict[int, Dict[str, int]] = {}

# all files that we have seen in a scan that belong to a library (i.e. not filtered), unchanged or not
_files_seen: Dict[int, Set[str]] = {}


def add_file_seen(library_id: int, path: str):
    if library_id not in _files_seen:
        _files_seen[library_id] = set()
    _files_seen[library_id].add(path)


def get_files_seen(library_id: int, clear=True) -> Set[str]:
    if library_id not in _files_seen:
        return set()
    res = _files_seen[library_id]
    if clear:
        del _files_seen[library_id]
    return res


def add_file_tested(library_id: int, path: str, mtime: int):
    if library_id not in _files_tested:
        _files_tested[library_id] = {}
    _files_tested[library_id][path] = mtime


def remove_file_tested(library_id: int, path: str):
    if library_id not in _files_tested:
        _files_tested[library_id] = {}
    if path in _files_tested[library_id]:
        del _files_tested[library_id]


def get_files_tested(library_id: int, clear=True) -> Dict[str, int]:
    if library_id not in _files_tested:
        return {}
    res = _files_tested[library_id]
    if clear:
        del _files_tested[library_id]
    return res