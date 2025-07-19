#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import queue
import threading
import time
import uuid
import traceback

from playhouse.shortcuts import model_to_dict
from playhouse.sqliteq import SqliteQueueDatabase
from unmanic.libs.filetest import FileTesterThread
from unmanic.libs.library import Libraries
from unmanic.libs.unplugins.settings import PluginSettings

logger = logging.getLogger("Unmanic.Plugin.kmarius_files")


class Settings(PluginSettings):
    settings = {
        "Valid extensions ": ".mp4,.mkv,.webm",
    }


settings = Settings()


def get_valid_extensions():
    extensions = settings.get_setting("Valid extensions ")
    return [ext.strip() for ext in extensions.split(",")]


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


def extension_valid(path, extensions):
    _, ext = os.path.splitext(path)
    return ext.lower() in extensions


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

    # pre-fill queue
    files_to_test = queue.Queue()
    for item in items:
        files_to_test.put(item)
    files_to_process = queue.Queue()

    event = libraryscanner.event

    threads = []

    for i in range(num_threads):
        tester = FileTesterThread(f"kmarius-file-tester-{library_id}-{i}", files_to_test, files_to_process, queue.Queue(),
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
    extensions = get_valid_extensions()
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
                if extension_valid(path, extensions):
                    items_.add(path)
        else:
            items_per_lib[library_id].add(path)

    for id in items_per_lib:
        threading.Thread(target=test_file_thread, args=(list(items_per_lib[id]), id)).start()


def process_files(payload):
    extensions = get_valid_extensions()
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
                if extension_valid(path, extensions):
                    items_.append({"path": path, "priority_score": priority_score})
        else:
            items_per_lib[library_id].append({"path": path, "priority_score": priority_score})

    for id in items_per_lib:
        for item in items_per_lib[id]:
            libraryscanner.add_path_to_queue(item['path'], id, item['priority_score'])


# this function can't load single files currently, only directories with their files
def load_subtree(path, title, id, lazy=True, get_timestamps=False):
    if get_timestamps:
        try:
            from kmarius_incremental_scan_db.lib import load_timestamp, load_timestamps
        except ImportError:
            get_timestamps = False

    extensions = get_valid_extensions()

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
                        "title":     name,
                        "libraryId": id,
                        "path":      abspath,
                        "lazy":      True,
                        "type":      "folder",
                    })
                else:
                    children.append(load_subtree(abspath, name, id, lazy=False, get_timestamps=get_timestamps))
            else:
                if extension_valid(name, extensions):
                    file_info = os.stat(abspath)
                    files.append({
                        "title":     name,
                        "libraryId": id,
                        "path":      abspath,
                        "mtime":     int(file_info.st_mtime),
                        "size":      int(file_info.st_size),
                        "icon":      "bi bi-film"
                    })

    children.sort(key=lambda c: c["title"])
    files.sort(key=lambda c: c["title"])

    # getting timestamps in bulk makes the operation >5 times faster
    if get_timestamps:
        paths = [file["path"] for file in files]
        for i, timestamp in enumerate(load_timestamps(paths)):
            files[i]['timestamp'] = timestamp

    children += files

    return {
        "title":     title,
        "children":  children,
        "libraryId": id,
        "path":      path,
        "type":      "folder",
    }


def get_subtree(arguments, lazy=True):
    id = int(arguments["libraryId"][0])
    path = arguments["path"][0].decode('utf-8')
    title = arguments["title"][0].decode('utf-8')

    library = Libraries().select().where(Libraries.id == id).first()

    if library.enable_remote_only:
        raise Exception("Library is remote only")

    if not path.startswith(library.path) or ".." in path:
        raise Exception("Invalid path")

    get_timestamps = have_incremental_scan()

    return load_subtree(path, title, id, lazy=lazy, get_timestamps=get_timestamps)


def reset_timestamps(payload):
    try:
        from kmarius_incremental_scan_db.lib import store_timestamps
    except ImportError:
        return

    extensions = get_valid_extensions()

    if "arr" in payload:
        paths = [item["path"] for item in payload["arr"]]
    else:
        paths = [payload["path"]]

    distinct = set()
    for path in paths:
        if os.path.isdir(path):
            for p in expand_path(path):
                distinct.add(p)
        else:
            distinct.add(path)
    values = [(path, 0) for path in distinct if extension_valid(path, extensions)]

    store_timestamps(values)


def update_timestamps(payload):
    try:
        from kmarius_incremental_scan_db.lib import store_timestamps
    except ImportError:
        return

    extensions = get_valid_extensions()

    if "arr" in payload:
        paths = [item["path"] for item in payload["arr"]]
    else:
        paths = [payload["path"]]

    distinct = set()
    for path in paths:
        if os.path.isdir(path):
            for p in expand_path(path):
                distinct.add(p)
        else:
            distinct.add(path)
    paths = [path for path in distinct if extension_valid(path, extensions)]

    values = []
    for path in paths:
        try:
            info = os.stat(path)
            values.append((path, int(info.st_mtime)))
        except OSError as e:
            logger.error(f"{e}")

    store_timestamps(values)


def get_libraries(lazy=True):
    libs = []
    for lib in Libraries().select().where(Libraries.enable_remote_only == False):
        libs.append({
            "title":     lib.name,
            "libraryId": lib.id,
            "path":      lib.path,
            "type":      "folder",
            "lazy":      lazy,
        })

    return {
        "children": libs,
    }


def render_frontend_panel(data):
    data["content_type"] = "text/html"

    with open(os.path.abspath(os.path.join(os.path.dirname(__file__), 'static', 'index.html'))) as file:
        content = file.read()
        if have_incremental_scan():
            content = content.replace("HAVE_INCREMENTAL_SCAN = false;", "HAVE_INCREMENTAL_SCAN = true;")
        data['content'] = content.replace("{cache_buster}", str(uuid.uuid4()))


def render_plugin_api(data):
    start_time = time.time()
    data['content_type'] = 'application/json'
    
    try:
        path = data["path"]
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

    end_time = time.time()
    elapsed = end_time - start_time
    path = data["path"]
    # logger.info(f"{path} {int(elapsed * 1000)}ms")

    return data