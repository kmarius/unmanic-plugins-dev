#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import queue
import re
import threading
import uuid
import traceback
from typing import override

from unmanic.libs.filetest import FileTesterThread
from unmanic.libs.library import Libraries
from unmanic.libs.unplugins.settings import PluginSettings

logger = logging.getLogger("Unmanic.Plugin.kmarius_files")


class Settings(PluginSettings):

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)
        self.settings, self.form_settings = self.__build_settings()
        self._valid_extensions = None
        self._ignore_patterns = None

    @staticmethod
    def __build_settings():
        libs = []
        for lib in Libraries().select().where(Libraries.enable_remote_only == False):
            libs.append((lib.id, lib.name))

        settings = {
            "library_id": libs[0][0],
        }

        form_settings = {
            "library_id": {
                "label":          "Configuration for library",
                "input_type":     "select",
                "select_options": [
                    {"value": library_id, "label": name} for library_id, name in libs
                ],
            },
        }

        settings.update({
            f"library_{library_id}_extensions": "mp4,mkv,webm,avi,mov" for library_id, _ in libs
        })
        form_settings.update({
            f"library_{library_id}_extensions":
                {
                    "label":       "Allowed extensions for this library",
                    "sub_setting": True,
                    "display":     "hidden",
                }
            for library_id, _ in libs
        })

        settings.update({
            f"library_{library_id}_ignored_paths": "" for library_id, _ in libs
        })
        form_settings.update({
            f"library_{library_id}_ignored_paths":
                {
                    "label":       "Ignored path patterns for this library - one per line",
                    "input_type":  "textarea",
                    "sub_setting": True,
                    "display":     "hidden",
                }
            for library_id, _ in libs
        })

        settings.update({
            f"library_{library_id}_lazy_load": False for library_id, _ in libs
        })
        form_settings.update({
            f"library_{library_id}_lazy_load":
                {
                    "label":       "Lazily load files in this library.",
                    "sub_setting": True,
                    "display":     "hidden",
                }
            for library_id, _ in libs
        })

        return settings, form_settings

    @override
    def get_form_settings(self):
        form_settings = super(Settings, self).get_form_settings()
        if not self.settings_configured:
            # FIXME: in staging, settings_configured is not populated at this point and the corresponding method is private
            self._PluginSettings__import_configured_settings()
        if self.settings_configured:
            library_id = self.settings_configured.get("library_id")
            settings = [
                f"library_{library_id}_extensions",
                f"library_{library_id}_ignored_paths",
                f"library_{library_id}_lazy_load",
            ]
            for setting in settings:
                if setting in form_settings:
                    del form_settings[setting]["display"]
        return form_settings

    def is_extension_valid(self, library_id: int, path: str):
        if self._valid_extensions is None:
            self._valid_extensions = {}
            for lib in Libraries().select().where(Libraries.enable_remote_only == False):
                extensions = self.get_setting(f"library_{lib.id}_extensions").split(",")
                extensions = [e.strip().lower() for e in extensions]
                self._valid_extensions[lib.id] = set(extensions)
        ext = os.path.splitext(path)[1]
        if not ext:
            return False
        ext = ext.lower().lstrip(".")
        return ext in self._valid_extensions[library_id]

    def is_path_ignored(self, library_id: int, path: str):
        if self._ignore_patterns is None:
            self._ignore_patterns = {}
            for lib in Libraries().select().where(Libraries.enable_remote_only == False):
                patterns = []
                for pattern in self.get_setting(f"library_{lib.id}_ignored_paths").splitlines():
                    pattern = pattern.strip()
                    if pattern != "" and not pattern.startswith("#"):
                        patterns.append(re.compile(pattern))
                self._ignore_patterns[lib.id] = patterns
        for pattern in self._ignore_patterns[library_id]:
            if pattern.search(path):
                return True
        return False

    def is_in_library(self, library_id: int, path: str):
        return self.is_extension_valid(library_id, path) and not self.is_path_ignored(library_id, path)


settings = Settings()


def get_thread(name):
    for thread in threading.enumerate():
        if thread.name == name:
            return thread
    return None


libraryscanner = get_thread("LibraryScannerManager")


def have_incremental_scan():
    try:
        import kmarius_incremental_scan_db.lib
        return True
    except ImportError:
        pass
    return False


def expand_path(path):
    res = []
    for dirpath, dirnames, filenames in os.walk(path):
        for filename in filenames:
            res.append(os.path.join(dirpath, filename))
    return res


def get_library_paths():
    paths = {}
    for lib in Libraries().select().where(Libraries.enable_remote_only == False):
        paths[lib.id] = lib.path
    return paths


def validate_path(path, library_path):
    return ".." not in path and path.startswith(library_path)


def test_file_thread(items, library_id, num_threads=1):
    if len(items) == 0:
        return
    print(f"testing {len(items)} files")

    # pre-fill queue
    files_to_test = queue.Queue()
    for item in items:
        files_to_test.put(item)
    files_to_process = queue.Queue()

    event = libraryscanner.event

    threads = []

    for i in range(num_threads):
        tester = FileTesterThread(f"kmarius-file-tester-{library_id}-{i}", files_to_test, files_to_process,
                                  queue.Queue(),
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


def test_files(payload):
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
                if settings.is_in_library(library_id, path):
                    items_.add(path)
        else:
            items_per_lib[library_id].add(path)

    for library_id, items in items_per_lib.items():
        threading.Thread(target=test_file_thread, args=(list(items), library_id), daemon=True).start()


def process_files(payload):
    library_paths = get_library_paths()

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
                if settings.is_in_library(library_id, path):
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
def load_subtree(path, title, library_id, lazy=True, get_timestamps=False):
    if get_timestamps:
        try:
            from kmarius_incremental_scan_db.lib import load_timestamp, load_timestamps
        except ImportError:
            get_timestamps = False

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
                if settings.is_in_library(library_id, name):
                    file_info = os.stat(abspath)
                    files.append({
                        "title":      name,
                        "library_id": library_id,
                        "path":       abspath,
                        "mtime":      int(file_info.st_mtime),
                        "size":       int(file_info.st_size),
                        "icon":       get_icon(name)
                    })

    children.sort(key=lambda c: c["title"])
    files.sort(key=lambda c: c["title"])

    # getting timestamps in bulk makes the operation >5 times faster
    if get_timestamps:
        paths = [file["path"] for file in files]
        for i, timestamp in enumerate(load_timestamps(library_id, paths)):
            files[i]['timestamp'] = timestamp

    children += files

    return {
        "title":      title,
        "children":   children,
        "library_id": library_id,
        "path":       path,
        "type":       "folder",
    }


def get_subtree(arguments):
    library_id = int(arguments["library_id"][0])
    path = arguments["path"][0].decode('utf-8')
    title = arguments["title"][0].decode('utf-8')

    library = Libraries().select().where(Libraries.id == library_id).first()

    if library.enable_remote_only:
        raise Exception("Library is remote only")

    if not path.startswith(library.path) or ".." in path:
        raise Exception("Invalid path")

    get_timestamps = have_incremental_scan()
    lazy = settings.get_setting(f"library_{library.id}_lazy_load")

    return load_subtree(path, title, library_id, lazy=lazy, get_timestamps=get_timestamps)


def reset_timestamps(payload):
    try:
        from kmarius_incremental_scan_db.lib import store_timestamps
    except ImportError:
        return

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
    values = [(library_id, path, 0) for library_id, path in distinct if settings.is_in_library(library_id, path)]

    store_timestamps(values)


def update_timestamps(payload):
    try:
        from kmarius_incremental_scan_db.lib import store_timestamps
    except ImportError:
        return

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
    items = [(library_id, path) for library_id, path in distinct if settings.is_in_library(library_id, path)]

    values = []
    for library_id, path in items:
        try:
            info = os.stat(path)
            values.append((library_id, path, int(info.st_mtime)))
        except OSError as e:
            logger.error(f"{e}")

    store_timestamps(values)


def get_libraries(lazy=True):
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


def render_frontend_panel(data):
    data["content_type"] = "text/html"

    with open(os.path.abspath(os.path.join(os.path.dirname(__file__), 'static', 'index.html'))) as file:
        content = file.read()
        if have_incremental_scan():
            content = content.replace("HAVE_INCREMENTAL_SCAN = false;", "HAVE_INCREMENTAL_SCAN = true;")
        data['content'] = content.replace("{cache_buster}", str(uuid.uuid4()))


def render_plugin_api(data):
    data['content_type'] = 'application/json'

    try:
        path = data["path"]
        if path == "/test":
            test_files(json.loads(data["body"].decode('utf-8')))
        elif path == '/process':
            process_files(json.loads(data["body"].decode('utf-8')))
        elif path == '/subtree':
            data["content"] = get_subtree(data["arguments"])
        elif path == "/libraries":
            data["content"] = get_libraries()
        elif path == "/timestamp/reset":
            reset_timestamps(json.loads(data["body"].decode('utf-8')))
        elif path == "/timestamp/update":
            update_timestamps(json.loads(data["body"].decode('utf-8')))
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