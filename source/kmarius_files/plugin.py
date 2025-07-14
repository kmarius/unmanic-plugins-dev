#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import logging
import os
import queue
import time
import uuid
import threading
from operator import attrgetter

from peewee import *
from playhouse.shortcuts import model_to_dict
from playhouse.sqliteq import SqliteQueueDatabase

from unmanic.libs.filetest import FileTest, FileTesterThread
from unmanic.libs.unplugins.settings import PluginSettings
from unmanic.libs.library import Libraries
import unmanic.libs.libraryscanner

logger = logging.getLogger("Unmanic.Plugin.kmarius_files")


class Settings(PluginSettings):
    settings = {}


settings = Settings()


def get_thread(name):
    for thread in threading.enumerate():
        if thread.name == name:
            return thread
    return None


libraryscanner = get_thread("LibraryScannerManager")


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
    if "arr" in payload:
        items = payload["arr"]
    else:
        items = [payload]

    for item in items:
        if os.path.isdir(item["path"]):
            for path in expand_path(item["path"]):
                if path.endswith(".mp4") or path.endswith(".mkv"):
                    libraryscanner.add_path_to_queue(path, item["library_id"], item['priority_score'])
        else:
            if path.endswith(".mp4") or path.endswith(".mkv"):
                libraryscanner.add_path_to_queue(item['path'], item["library_id"], item['priority_score'])


def load_subtree(path, title, id, lazy=True):
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
                        "folder": True,
                    })
                else:
                    children.append(load_subtree(abspath, name, id, lazy=False))
            else:
                if name.endswith(".mp4") or name.endswith(".mkv"):
                    file_info = os.stat(abspath)
                    files.append({
                        "title": name,
                        "libraryId": id,
                        "path": abspath,
                        "mtime": int(file_info.st_mtime),
                        "size": int(file_info.st_size),
                        "folder": False,
                        "icon": "bi bi-film"
                    })

    children.sort(key=lambda c: c["title"])
    files.sort(key=lambda c: c["title"])

    children += files

    return {
        "title": title,
        "children": children,
        "libraryId": id,
        "path": path,
        "folder": True,
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

    return load_subtree(path, title, id, lazy=lazy)


def get_libraries():
    libs = []
    for lib in Libraries().select().where(Libraries.enable_remote_only == False):
        libs.append({
            "title": lib.name,
            "libraryId": lib.id,
            "path": lib.path,
            "directory": True,
            "lazy": True,
        })
    return {"children": libs}


def render_frontend_panel(data):
    data["content_type"] = "text/html"

    with open(os.path.abspath(os.path.join(os.path.dirname(__file__), 'static', 'index.html'))) as file:
        content = file.read()
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
        else:
            data["content"] = {
                "success": False,
                "error": f"unknown path: {data['path']}",
            }
    except Exception as e:
        data["content"] = {
            "success": False,
            "error": str(e),
        }

    end_time = time.time()
    elapsed = end_time - start_time
    path = data["path"]
    logger.info(f"{path} {int(elapsed * 1000)}ms")

    return data