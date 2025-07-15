#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import queue
import threading
import time
import uuid

from playhouse.shortcuts import model_to_dict
from playhouse.sqliteq import SqliteQueueDatabase
from unmanic.libs.filetest import FileTest, FileTesterThread
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


def test_file_thread(items, library_id):
    # pre-fill queue
    files_to_test = queue.Queue()
    for item in items:
        files_to_test.put(item["path"])
    files_to_process = queue.Queue()

    event = libraryscanner.event

    tester = FileTesterThread("my-file-tester", files_to_test, files_to_process, queue.Queue(), library_id, event)
    tester.daemon = True
    tester.start()

    # Wait until the thread has grabbed all paths, then wait another second to ensure we don't stop it
    # before it starts working. It will shut down afterward
    while not files_to_test.empty():
        event.wait(1)
    event.wait(1)

    tester.stop()
    tester.join()

    while not files_to_process.empty():
        item = files_to_process.get()
        libraryscanner.add_path_to_queue(item.get('path'), library_id, item.get('priority_score'))


def test_files(payload):
    if "arr" in payload:
        items = payload["arr"]
    else:
        items = [payload]

    items_per_lib = {}

    for item in items:
        if not item["library_id"] in items_per_lib:
            items_per_lib[item["library_id"]] = []
        if os.path.isdir(item["path"]):
            for path in expand_path(item["path"]):
                items_per_lib[item["library_id"]].append({
                    "path": path,
                    "library_id": item["library_id"],
                    "library_name": item["library_name"],
                    "type": item["type"],
                    "priority_score": item["priority_score"]
                })
        else:
            items_per_lib[item["library_id"]].append(item)

    # deduplicate as expand_path can add duplicates
    for id in items_per_lib:
        paths = set()
        new_items = []
        for item in items_per_lib[id]:
            if item["path"] in paths:
                continue
            paths.add(item["path"])
            new_items.append(item)
        items_per_lib[id] = new_items

    for id in items_per_lib:
        threading.Thread(target=test_file_thread, args=(items_per_lib[id], id)).start()


def process_files(payload):
    extensions = get_valid_extensions()

    if "arr" in payload:
        items = payload["arr"]
    else:
        items = [payload]

    for item in items:
        if os.path.isdir(item["path"]):
            for path in expand_path(item["path"]):
                if extension_valid(path, extensions):
                    libraryscanner.add_path_to_queue(path, item["library_id"], item['priority_score'])
        else:
            if extension_valid(path, extensions):
                libraryscanner.add_path_to_queue(item['path'], item["library_id"], item['priority_score'])


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
                        "title": name,
                        "libraryId": id,
                        "path": abspath,
                        "lazy": True,
                        "type": "folder",
                    })
                else:
                    children.append(load_subtree(abspath, name, id, lazy=False, get_timestamps=get_timestamps))
            else:
                if extension_valid(name, extensions):
                    file_info = os.stat(abspath)
                    files.append({
                        "title": name,
                        "libraryId": id,
                        "path": abspath,
                        "mtime": int(file_info.st_mtime),
                        "size": int(file_info.st_size),
                        "icon": "bi bi-film"
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
        "title": title,
        "children": children,
        "libraryId": id,
        "path": path,
        "type": "folder",
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


def get_libraries():
    libs = []
    for lib in Libraries().select().where(Libraries.enable_remote_only == False):
        libs.append({
            "title": lib.name,
            "libraryId": lib.id,
            "path": lib.path,
            "type": "folder",
            "lazy": True,
        })
    return {"children": libs}


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
                "error": f"unknown path: {data['path']}",
            }
    except Exception as e:
        logger.error(f"{e}")
        data["content"] = {
            "success": False,
            "error": str(e),
        }

    end_time = time.time()
    elapsed = end_time - start_time
    path = data["path"]
    # logger.info(f"{path} {int(elapsed * 1000)}ms")

    return data