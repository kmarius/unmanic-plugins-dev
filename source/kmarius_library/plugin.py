#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import queue
import re
import threading
import time
import traceback
import uuid
from typing import Mapping, Optional, override

from unmanic.libs.libraryscanner import LibraryScannerManager
from unmanic.libs.filetest import FileTesterThread
from unmanic.libs.library import Libraries
from unmanic.libs.unplugins.settings import PluginSettings
from kmarius_library import logger
from kmarius_library.lib import cache, timestamps
from kmarius_library.lib.metadata_provider import MetadataProvider, PROVIDERS
from kmarius_library.plugin_types import *

cache.init([p.name for p in PROVIDERS])
timestamps.init()


class Settings(PluginSettings):
    @staticmethod
    def __build_settings():
        settings = {
            "ignored_path_patterns":    "",
            "allowed_extensions":       '',
            "incremental_scan_enabled": True,
            "quiet_incremental_scan":   True,
            "caching_enabled":          True,
        }
        form_settings = {
            "ignored_path_patterns":    {
                "input_type": "textarea",
                "label":      "Regular expression patterns of pathes to ignore - one per line"
            },
            "allowed_extensions":       {
                "label":       "Search library only for extensions",
                "description": "A comma separated list of allowed file extensions."
            },
            "incremental_scan_enabled": {
                "label": "Enable incremental scans (ignore unchanged files)",
            },
            "quiet_incremental_scan":   {
                "label":       "Don't spam the logs with unchanged files and timestamp updates.",
                'display':     'hidden',
                "sub_setting": True,
            },
            "caching_enabled":          {
                "label": "Enable metadata caching"
            },
        }

        settings.update({
            p.setting_name(): p.default_enabled for p in PROVIDERS
        })
        settings.update({
            "quiet_caching": True,
        })

        form_settings.update({
            p.setting_name(): {
                'label':       f'Enable {p.name} caching',
                "sub_setting": True,
                'display':     'hidden',
            } for p in PROVIDERS
        })
        form_settings.update({
            "quiet_caching": {
                'label':       "Don't spam the logs with information on caching.",
                "sub_setting": True,
                'display':     'hidden',
            }
        })

        return settings, form_settings

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)
        self.settings, self.form_settings = self.__build_settings()

    @override
    def get_form_settings(self):
        form_settings = super(Settings, self).get_form_settings()
        if not self.settings_configured:
            # FIXME: in staging, settings_configured is not populated at this point and the corresponding method is private
            self._PluginSettings__import_configured_settings()
        if self.settings_configured:
            if self.settings_configured.get("caching_enabled"):
                for setting, val in form_settings.items():
                    if setting.startswith("cache_"):
                        del val["display"]
                    if setting == "quiet_caching":
                        del val["display"]
            if self.settings_configured.get("incremental_scan_enabled"):
                del form_settings["quiet_incremental_scan"]["display"]
        return form_settings


def critical(f):
    """Decorator to allow only one thread to execute this at a time."""
    lock = threading.Lock()

    def wrapped(*args, **kwargs):
        if not lock.acquire(blocking=False):
            logger.info("Could not acquire lock")
            return
        try:
            f(*args, **kwargs)
        finally:
            lock.release()

    return wrapped


_allowed_extensions = {}
_ignored_path_patterns = {}


def get_allowed_extensions(library_id: int) -> list[str]:
    if library_id not in _allowed_extensions:
        settings = Settings(library_id=library_id)
        extensions = settings.get_setting("allowed_extensions").split(",")
        extensions = [ext.strip().lstrip(".") for ext in extensions]
        _allowed_extensions[library_id] = extensions
    return _allowed_extensions[library_id]


def get_ignored_path_patterns(library_id: int) -> list[re.Pattern]:
    if library_id not in _ignored_path_patterns:
        settings = Settings(library_id=library_id)
        patterns = []
        for regex_pattern in settings.get_setting("ignored_path_patterns").splitlines():
            regex_pattern = regex_pattern.strip()
            if regex_pattern != "" and not regex_pattern.startswith("#"):
                pattern = re.compile(regex_pattern)
                patterns.append(pattern)
        _ignored_path_patterns[library_id] = patterns
    return _ignored_path_patterns[library_id]


def update_cached_metadata(providers: list[MetadataProvider], path: str, quiet: bool = True):
    try:
        mtime = int(os.path.getmtime(path))

        for p in providers:
            if cache.exists(p.name, path, mtime):
                continue

            res = p.run_prog(path)

            if res:
                cache.put(p.name, path, mtime, res)
                if not quiet:
                    logger.info(f"Updating {p.name} data - {path}")
    except Exception as e:
        logger.error(e)


def update_timestamp(library_id: int, path: str):
    try:
        mtime = int(os.path.getmtime(path))
        timestamps.put(library_id, path, mtime)
    except Exception as e:
        logger.error(e)


def is_extension_allowed(library_id: int, path: str) -> bool:
    extensions = get_allowed_extensions(library_id)
    ext = os.path.splitext(path)[-1]
    if ext and ext[1:].lower() in extensions:
        return True
    return False


def is_path_ignored(library_id: int, path: str) -> bool:
    regex_patterns = get_ignored_path_patterns(library_id)
    for pattern in regex_patterns:
        if pattern.search(path):
            return True
    return False


def is_file_unchanged(library_id: int, path: str) -> bool:
    mtime = int(os.path.getmtime(path))
    stored_timestamp = timestamps.get(library_id, path)
    if stored_timestamp == mtime:
        return True
    return False


def init_shared_data(data: FileTestData, settings: Settings):
    if not "shared_info" in data:
        data["shared_info"] = {}
    shared_info = data["shared_info"]
    if not "kmarius_library" in shared_info:
        shared_info["kmarius_library"] = settings


def on_library_management_file_test(data: FileTestData) -> Optional[FileTestData]:
    settings = Settings(library_id=data.get('library_id'))
    path = data["path"]
    library_id = data["library_id"]

    if not is_extension_allowed(library_id, path):
        data['add_file_to_pending_tasks'] = False
        return data

    if is_path_ignored(library_id, path):
        data['add_file_to_pending_tasks'] = False
        return data

    init_shared_data(data, settings)

    if settings.get_setting("incremental_scan_enabled"):
        if is_file_unchanged(library_id, path):
            if not settings.get_setting("quiet_incremental_scan"):
                data["issues"].append({
                    'id':      "kmarius_library",
                    'message': f"unchanged: {path}, library_id={library_id}"
                })
            data['add_file_to_pending_tasks'] = False
            return data

    if settings.get_setting("caching_enabled"):
        mtime = int(os.path.getmtime(path))
        quiet = settings.get_setting("quiet_caching")

        for p in PROVIDERS:
            if not settings.get_setting(p.setting_name()):
                continue

            res = cache.lookup(p.name, path, mtime)

            if res is None:
                if not quiet:
                    logger.info(f"No cached {p.name} data found, refreshing - {path}")
                res = p.run_prog(path)
            else:
                if not quiet:
                    logger.info(f"Cached {p.name} data found - {path}")

            if res:
                data["shared_info"][p.name] = res
                cache.put(p.name, path, mtime, res)

    return data


def on_postprocessor_task_results(data: TaskResultData) -> Optional[TaskResultData]:
    if data["task_processing_success"] and data["file_move_processes_success"]:
        settings = Settings(library_id=data["library_id"])
        incremental_scan_enabled = settings.get_setting("incremental_scan_enabled")
        caching_enabled = settings.get_setting("caching_enabled")

        library_id = data["library_id"]

        metadata_providers = []

        if caching_enabled:
            for p in PROVIDERS:
                if settings.get_setting(p.setting_name()):
                    metadata_providers.append(p)

        quiet = settings.get_setting("quiet_caching")

        for path in data["destination_files"]:
            if is_extension_allowed(library_id, path):
                if caching_enabled:
                    update_cached_metadata(metadata_providers, path, quiet)
                if incremental_scan_enabled:
                    # TODO: it could be desirable to not add this file to the db and have it checked again
                    if not settings.get_setting("quiet_incremental_scan"):
                        logger.info(f"Updating timestamp path={path} library_id={library_id}")
                    update_timestamp(library_id, path)
    return data


def get_thread(name: str) -> Optional[threading.Thread]:
    for thread in threading.enumerate():
        if thread.name == name:
            return thread
    return None


def get_libraryscanner() -> LibraryScannerManager:
    return get_thread("LibraryScannerManager")


def expand_path(path: str) -> list[str]:
    res = []
    for dirpath, dirnames, filenames in os.walk(path):
        for filename in filenames:
            res.append(os.path.join(dirpath, filename))
    return res


def get_library_paths() -> Mapping[int, str]:
    paths = {}
    for lib in Libraries().select().where(Libraries.enable_remote_only == False):
        paths[lib.id] = lib.path
    return paths


def validate_path(path: str, library_path: str) -> bool:
    return ".." not in path and path.startswith(library_path)


def test_file_thread(items: list, library_id: int, num_threads=1):
    if len(items) == 0:
        return

    libraryscanner = get_libraryscanner()

    # pre-fill queue
    files_to_test = queue.Queue()
    for item in items:
        files_to_test.put(item)
    files_to_process = queue.Queue()

    event = libraryscanner.event

    threads = []

    for i in range(num_threads):
        tester = FileTesterThread(f"kmarius-file-tester-{library_id}-{i}",
                                  files_to_test, files_to_process, queue.Queue(),
                                  library_id, event)
        tester.daemon = True
        tester.start()
        threads.append(tester)

    def queue_up_result(item):
        libraryscanner.add_path_to_queue(item.get('path'), library_id, item.get('priority_score'))

    while not files_to_test.empty():
        while not files_to_process.empty():
            queue_up_result(files_to_process.get())
        event.wait(1)

    for thread in threads:
        thread.stop()

    for thread in threads:
        thread.join()

    while not files_to_process.empty():
        queue_up_result(files_to_process.get())


def test_files(payload: dict):
    library_paths = get_library_paths()

    if "arr" in payload:
        items = payload["arr"]
    else:
        items = [payload]

    items_per_lib = {}

    for item in items:
        library_id = item["library_id"]
        path = item["path"]

        if not validate_path(path, library_paths[library_id]):
            raise Exception("Invalid path")

        if not library_id in items_per_lib:
            items_per_lib[library_id] = set()

        if os.path.isdir(path):
            items_ = items_per_lib[library_id]
            for path in expand_path(path):
                if is_extension_allowed(library_id, path):
                    items_.add(path)
        else:
            items_per_lib[library_id].add(path)

    for library_id, items in items_per_lib.items():
        threading.Thread(target=test_file_thread, args=(list(items), library_id)).start()


def process_files(payload: dict):
    library_paths = get_library_paths()

    libraryscanner = get_libraryscanner()

    if "arr" in payload:
        items = payload["arr"]
    else:
        items = [payload]

    items_per_lib = {}

    for item in items:
        library_id = item["library_id"]
        path = item["path"]
        priority_score = item["priority_score"]

        if not validate_path(path, library_paths[library_id]):
            raise Exception("Invalid path")

        if not library_id in items_per_lib:
            items_per_lib[library_id] = []

        if os.path.isdir(path):
            items_ = items_per_lib[library_id]
            for path in expand_path(path):
                if is_extension_allowed(library_id, path):
                    items_.append({"path": path, "priority_score": priority_score})
        else:
            items_per_lib[library_id].append({"path": path, "priority_score": priority_score})

    for library_id, items in items_per_lib.items():
        for item in items:
            libraryscanner.add_path_to_queue(item['path'], library_id, item['priority_score'])


def get_icon(name: str) -> str:
    ext = os.path.splitext(name)[1][1:].lower()
    if ext in ["mp4", "mkv", "webm", "avi", "mov", "flv"]:
        return "bi bi-film"
    elif ext in ["mp3", "m4a", "flac", "opus", "ogg"]:
        return "bi bi-music-note-beamed"
    elif ext in ["jpg", "png", "bmp"]:
        return "bi bi-image"
    else:
        return "bi bi-file-earmark"


# this function can't load single files currently, only directories with their files
def load_subtree(path: str, title: str, library_id: int, lazy=True, get_timestamps=False) -> dict:
    children = []
    files = []

    with os.scandir(path) as entries:
        for entry in entries:
            name = entry.name
            if name.startswith("."):
                continue
            abspath = os.path.abspath(os.path.join(path, name))
            if entry.is_dir():
                if lazy:
                    children.append({
                        "title":      name,
                        "library_id": library_id,
                        "path":       abspath,
                        "lazy":       True,
                        "type":       "folder",
                    })
                else:
                    children.append(load_subtree(abspath, name, library_id, lazy=False, get_timestamps=get_timestamps))
            else:
                if is_extension_allowed(library_id, name):
                    file_info = os.stat(abspath)
                    files.append({
                        "title":      name,
                        "library_id": library_id,
                        "path":       abspath,
                        "mtime":      int(file_info.st_mtime),
                        "size":       int(file_info.st_size),
                        "icon":       get_icon(name),
                    })

    children.sort(key=lambda c: c["title"])
    files.sort(key=lambda c: c["title"])

    # getting timestamps in bulk makes the operation >5 times faster
    if get_timestamps:
        paths = [file["path"] for file in files]
        for i, timestamp in enumerate(timestamps.get_many(library_id, paths)):
            files[i]['timestamp'] = timestamp

    children += files

    return {
        "title":      title,
        "children":   children,
        "library_id": library_id,
        "path":       path,
        "type":       "folder",
    }


def get_subtree(arguments: dict, lazy=True) -> dict:
    library_id = int(arguments["library_id"][0])
    path = arguments["path"][0].decode('utf-8')
    title = arguments["title"][0].decode('utf-8')

    library = Libraries().select().where(Libraries.id == library_id).first()

    if library.enable_remote_only:
        raise Exception("Library is remote only")

    if not path.startswith(library.path) or ".." in path:
        raise Exception("Invalid path")

    return load_subtree(path, title, library_id, lazy=lazy, get_timestamps=True)


def reset_timestamps(payload: dict):
    if "arr" in payload:
        items = [(item["library_id"], item["path"]) for item in payload["arr"]]
    else:
        items = [(payload["library_id"], payload["path"])]

    distinct = set()
    for library_id, path in items:
        if os.path.isdir(path):
            for p in expand_path(path):
                distinct.add((library_id, p))
        else:
            distinct.add((library_id, path))
    values = [(library_id, path, 0) for library_id, path in distinct if
              is_extension_allowed(library_id, path)]

    timestamps.put_many(values)


def update_timestamps(payload: dict):
    if "arr" in payload:
        items = [(item["library_id"], item["path"]) for item in payload["arr"]]
    else:
        items = [(payload["library_id"], payload["path"])]

    distinct = set()
    for library_id, path in items:
        if os.path.isdir(path):
            for p in expand_path(path):
                distinct.add((library_id, p))
        else:
            distinct.add((library_id, path))
    items = [(library_id, path) for library_id, path in distinct if is_extension_allowed(library_id, path)]

    values = []
    for library_id, path in items:
        try:
            mtime = int(os.path.getmtime(path))
            values.append((library_id, path, mtime))
        except OSError as e:
            logger.error(f"{e}")

    timestamps.put_many(values)


def get_libraries(lazy=True) -> dict:
    libraries = []
    for lib in Libraries().select().where(Libraries.enable_remote_only == False):
        libraries.append({
            "title":      lib.name,
            "library_id": lib.id,
            "path":       lib.path,
            "type":       "folder",
            "lazy":       lazy,
        })

    return {
        "children": libraries,
    }


@critical
def prune_database(payload: dict):
    library_ids = []
    # we only prune metadata after pruning all libraries
    prune_metadata = True

    if "library_id" in payload:
        library_ids.append(payload["library_id"])
        prune_metadata = False
    else:
        for lib in Libraries().select().where(Libraries.enable_remote_only == False):
            library_ids.append(lib.id)

    num_pruned = 0
    for library_id in library_ids:
        logger.info(f"Pruning library {library_id}")

        paths = []
        for path in timestamps.get_all_paths(library_id):
            if not is_extension_allowed(library_id, path) or is_path_ignored(library_id, path) or not os.path.exists(path):
                paths.append(path)

        timestamps.remove_paths(library_id, paths)

        num_pruned += len(paths)
    logger.info(f"Pruned {num_pruned} paths")

    if prune_metadata:
        # we don't care whether caching is enabled for a library or not
        # we prune all items, that are in no library

        num_pruned = 0
        all_paths = set(timestamps.get_all_paths())
        for p in PROVIDERS:
            paths = []
            for path in cache.get_all_paths(p.name):
                if not path in all_paths:
                    paths.append(path)
            cache.remove_paths(p.name, paths)
            num_pruned += len(paths)
        logger.info(f"Pruned {num_pruned} metadata items")


def render_frontend_panel(data: PanelData):
    data["content_type"] = "text/html"

    with open(os.path.abspath(os.path.join(os.path.dirname(__file__), 'static', 'index.html'))) as file:
        content = file.read()
        data['content'] = content.replace("{cache_buster}", str(uuid.uuid4()))


def render_plugin_api(data: PluginApiData) -> PluginApiData:
    data['content_type'] = 'application/json'

    path = data["path"]

    try:
        if path == "/test":
            test_files(json.loads(data["body"].decode('utf-8')))
        elif path == '/process':
            process_files(json.loads(data["body"].decode('utf-8')))
        elif path == '/subtree':
            data["content"] = get_subtree(data["arguments"], False)
        elif path == "/libraries":
            data["content"] = get_libraries()
        elif path == "/timestamp/reset":
            reset_timestamps(json.loads(data["body"].decode('utf-8')))
        elif path == "/timestamp/update":
            update_timestamps(json.loads(data["body"].decode('utf-8')))
        elif path == "/prune":
            body = data["body"].decode('utf-8')
            if body.startswith("{"):
                payload = json.loads(body)
            else:
                payload = {}
            threading.Thread(target=prune_database, args=(payload,)).start()
        else:
            data["content"] = {
                "success": False,
                "error":   f"unknown path: {data['path']}",
            }
    except Exception as e:
        trace = traceback.format_exc()
        logger.error(trace)
        data["content"] = {
            "success": False,
            "error":   str(e),
            "trace":   trace,
        }

    return data