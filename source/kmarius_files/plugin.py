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

# Configure plugin logger
logger = logging.getLogger("Unmanic.Plugin.kmarius_files")


class Settings(PluginSettings):
    settings = {}


settings = Settings()
profile_directory = settings.get_profile_directory()
db_file = os.path.abspath(os.path.join(profile_directory, 'files.db'))
db = SqliteQueueDatabase(
    db_file,
    use_gevent=False,
    autostart=False,
    queue_max_size=None,
    results_timeout=15.0,
    pragmas=(
        ('foreign_keys', 1),
        ('journal_mode', 'wal'),
    )
)


class BaseModel(Model):
    class Meta:
        database = db

    def model_to_dict(self):
        return model_to_dict(self, backrefs=True)


class Files(BaseModel):
    path = TextField(primary_key=True, default='UNKNOWN')
    name = TextField(null=False, index=True, default='UNKNOWN')
    size = IntegerField(null=False, index=True, default=0)
    mtime = IntegerField(null=False, index=True, default=0)
    library = IntegerField(null=False, index=True, default=0)


class Data(object):
    def __init__(self):
        self.create_db_schema()

    @staticmethod
    def db_start():
        db.start()
        db.connect()

    @staticmethod
    def db_stop():
        db.close()
        # db.stop()

    @staticmethod
    def create_db_schema():
        Data.db_start()
        db.create_tables([Files], safe=True)
        Data.db_stop()

    @staticmethod
    def get_file_count():
        return Files.select().count()

    @staticmethod
    def get_files_filtered_and_sorted(sort=[], start=0, length=None, search=None, library=None):
        total = 0

        try:
            query = (
                Files.select()
            )

            if search:
                query = query.where(Files.name.contains(search))

            if library:
                query = query.where(Files.library == library)

            total = query.count()

            sorts = sort
            if len(sort) == 0:
                sorts = [{"column": "name", "asc": True}]

            sort_table = Files

            # TODO: allow sorting by multiple columns
            for sort in sorts:
                if sort["asc"]:
                    order_by = attrgetter(sort["column"])(sort_table).asc()
                else:
                    order_by = attrgetter(sort["column"])(sort_table).desc()

            if length:
                query = query.order_by(order_by).offset(start).limit(length)

        except Files.DoesNotExist:
            logger.warning("No historic tasks exist yet.")
            query = []

        return query.dicts(), total

    @staticmethod
    def save_source_item(abspath, library):
        Data.db_start()

        name = os.path.basename(abspath)
        file_info = os.stat(abspath)

        try:
            Files.insert(path=abspath, name=name, size=file_info.st_size, mtime=int(file_info.st_mtime),
                         library=library).on_conflict('replace').execute()
        except Exception:
            logger.exception("Failed to save historic data to database.")

        Data.db_stop()


Data()

for thread in threading.enumerate():
    continue
    print(f"Name: {thread.name}, ID: {thread.ident}, Daemon: {thread.daemon}")


def get_thread(name):
    for thread in threading.enumerate():
        if thread.name == name:
            return thread
    return None


def parse_arguments(arguments):
    sorts = []
    if "sort" in arguments:
        for tok in arguments["sort"]:
            if len(tok) == 0:
                continue
            tok = tok.decode('utf-8')
            ascending = tok[0] == "+"
            column = tok[1:]
            sorts.append({"column": column, "asc": ascending})
    arguments["sort"] = sorts
    if "search" in arguments:
        terms = arguments["search"]
        search_value = None
        if len(terms) > 0:
            search_value = terms[0].decode('utf-8')
        arguments["search"] = search_value
    if "start" in arguments and len(arguments["start"]) > 0:
        arguments["start"] = int(arguments["start"][0])
    if "length" in arguments and len(arguments["length"]) > 0:
        arguments["length"] = int(arguments["length"][0])
    if "library" in arguments:
        if len(arguments["library"]) > 0:
            arguments["library"] = int(arguments["library"][0])
        else:
            del arguments["library"]
    return arguments


def get_files(arguments):
    print(arguments)
    arguments = parse_arguments(arguments)
    print(arguments)

    data = Data()
    results, total = data.get_files_filtered_and_sorted(**arguments)
    results = [file for file in results]
    data.db_stop()

    return {
        "files": results,
        "total": total
    }


def render_frontend_panel(data):
    data["content_type"] = "text/html"

    with open(os.path.abspath(os.path.join(os.path.dirname(__file__), 'static', 'index.html'))) as file:
        content = file.read()
        data['content'] = content.replace("{cache_buster}", str(uuid.uuid4()))

    return


def scan(library):
    data = Data()

    for lib in Libraries().select():
        if library and lib.id != library:
            continue
        for dirpath, dirnames, filenames in os.walk(lib.path):
            for filename in filenames:
                if filename.endswith(".mp4") or filename.endswith(".mkv"):
                    data.save_source_item(os.path.abspath(os.path.join(dirpath, filename)), lib.id)


scanner = None


def scan_libraries(arguments):
    global scanner

    if scanner is not None and scanner.is_alive():
        print("already scanning")
        return

    library = None
    if "library" in arguments and len(arguments["library"]) > 0:
        library = int(arguments["library"][0])

    print("scanning libraries", library)
    scanner = threading.Thread(target=scan, args=(library,))
    scanner.start()
    scanner.join()


libraryscanner = None


def test_file_thread(elements, library_id):
    global libraryscanner

    print("tester for ", library_id)

    files = queue.Queue()
    for elem in elements:
        print(elem["path"])
        files.put(elem["path"])
    event = threading.Event()
    to_process = queue.Queue()

    tester = FileTesterThread("my-file-tester", files, to_process, queue.Queue(), library_id, event)
    tester.daemon = True
    tester.start()

    # Wait until the thread has grabbed all paths, then wait another second to ensure we don't stop it
    # before it starts working. It will shut down afterward
    while not files.empty():
        event.wait(1)
    event.wait(1)

    tester.stop()
    tester.join()

    while not to_process.empty():
        item = to_process.get()
        libraryscanner.add_path_to_queue(item.get('path'), library_id, item.get('priority_score'))


def test_file(payload):
    global libraryscanner
    if libraryscanner is None:
        libraryscanner = get_thread("LibraryScannerManager")

    if "arr" in payload:
        elements = payload["arr"]
    else:
        elements = [payload]

    elems_per_lib = {}

    for elem in elements:
        if not elem["library_id"] in elems_per_lib:
            elems_per_lib[elem["library_id"]] = []
        if os.path.isdir(elem["path"]):
            for path in expand_path(elem["path"]):
                elems_per_lib[elem["library_id"]].append({
                    "path":           path,
                    "library_id":     elem["library_id"],
                    "library_name":   elem["library_name"],
                    "type":           elem["type"],
                    "priority_score": elem["priority_score"]
                })
        else:
            elems_per_lib[elem["library_id"]].append(elem)

    # deduplicate as expand_path can add duplicates
    for library_id in elems_per_lib:
        paths = set()
        new_items = []
        for item in elems_per_lib[library_id]:
            if item["path"] in paths:
                continue
            paths.add(item["path"])
            new_items.append(item)
        elems_per_lib[library_id] = new_items

    for library_id in elems_per_lib:
        threading.Thread(target=test_file_thread, args=(elems_per_lib[library_id], library_id)).start()


def expand_path(path):
    res = []
    for dirpath, dirnames, filenames in os.walk(path):
        for filename in filenames:
            res.append(os.path.join(dirpath, filename))
    return res


def process_files(payload):
    global libraryscanner
    if libraryscanner is None:
        libraryscanner = get_thread("LibraryScannerManager")

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
                        "title":     name,
                        "libraryId": id,
                        "path":      abspath,
                        "lazy":      True,
                        "folder": True,
                    })
                else:
                    children.append(load_subtree(abspath, name, id, lazy=False))
            else:
                if name.endswith(".mp4") or name.endswith(".mkv"):
                    file_info = os.stat(abspath)
                    files.append({
                        "title":     name,
                        "libraryId": id,
                        "path":      abspath,
                        "mtime":     int(file_info.st_mtime),
                        "size":      int(file_info.st_size),
                        "folder": False,
                        "icon": "bi bi-film"
                    })

    children.sort(key=lambda c: c["title"])
    files.sort(key=lambda c: c["title"])

    children += files

    return {
        "title":     title,
        "children":  children,
        "libraryId": id,
        "path":      path,
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
            "title":     lib.name,
            "libraryId": lib.id,
            "path":      lib.path,
            "directory": True,
            "lazy":      True,
        })
    return {"children": libs}


def render_plugin_api(data):
    start_time = time.time()
    data['content_type'] = 'application/json'
    try:
        path = data["path"]
        if path in ['scan', '/scan', '/scan/']:
            scan_libraries(data["arguments"])
            data["content"]["success"] = True
        elif path in ['query', '/query', '/query/']:
            data['content'] = json.dumps(get_files(data["arguments"]))
        elif path == "/test":
            test_file(json.loads(data["body"].decode('utf-8')))
            data["content"] = {
                "success": True,
            }
        elif path in ['/process']:
            process_files(json.loads(data["body"].decode('utf-8')))
            data["content"] = {
                "success": True,
            }
        elif path == '/subtree':
            data["content"] = get_subtree(data["arguments"], False)
        elif path == "/libraries":
            data["content"] = get_libraries()
        else:
            data["content"] = {
                "success": False,
                "error":   f"unknown path: {data['path']}",
            }
    except Exception as e:
        print(e)
        data["content"] = {
            "success": False,
            "error":   str(e),
        }

    end_time = time.time()
    elapsed = end_time - start_time
    path = data["path"]
    print(f"{path} {int(elapsed * 1000)}ms")

    return data