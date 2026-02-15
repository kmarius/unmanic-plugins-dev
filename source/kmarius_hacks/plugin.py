import os.path
import signal
import sys
import threading
import time
import types
import uuid
from typing import Optional, cast

from unmanic.libs import common
from unmanic.libs.filetest import FileTest
from unmanic.libs.foreman import Foreman
from unmanic.libs.libraryscanner import LibraryScannerManager
from unmanic.libs.unplugins import PluginExecutor
from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_hacks.lib import logger, PLUGIN_ID
from kmarius_hacks.lib.types import *


def _get_thread(name: str) -> Optional[threading.Thread]:
    for thread in threading.enumerate():
        if thread.name == name:
            return thread
    return None


# sometimes we are executed too early, but our patch works with either the class or the instances
def _get_thread_or_class(clazz: type):
    for thread in threading.enumerate():
        if type(thread) == clazz:
            return thread
    return clazz


class Patch:
    def __init__(self, obj, method_name, new_method, label, description):
        self._obj = obj
        self._method_name = method_name
        self._old_name = Patch.get_real_name(method_name)

        if type(obj) == type:
            self._new_method = new_method
            self.setting_name = f"{self._obj.__name__}.{self._method_name}"
        else:
            # patching the method of an instance
            self._new_method = types.MethodType(new_method, obj)
            self.setting_name = f"{type(self._obj).__name__}.{self._method_name}"

        self.setting = False
        self.form_setting = {
            "label": label,
            "description": description,
        }

    def apply(self):
        if not hasattr(self._obj, self._old_name):
            logger.info(f"Patching {self.setting_name}")
            setattr(self._obj, self._old_name, getattr(self._obj, self._method_name))
            setattr(self._obj, self._method_name, self._new_method)

    def remove(self):
        if hasattr(self._obj, self._old_name):
            logger.info(f"Removing patch {self.setting_name}")
            setattr(self._obj, self._method_name, getattr(self._obj, self._old_name))
            delattr(self._obj, self._old_name)

    def patch(self, settings):
        if settings.get_setting(self.setting_name):
            self.apply()
        else:
            self.remove()

    @staticmethod
    def get_real_name(name):
        return f"_original_{name}"


def _try_exec_runner(plugin_id: str, plugin_runner: str, data: dict):
    executor = PluginExecutor()
    executor.get_plugin_settings(plugin_id)  # loads the plugin if it wasn't already
    module_name = f"{plugin_id}.plugin"
    if module_name not in sys.modules:
        logger.error(f"{module_name} not in sys.modules")
        return
    plugin_module = sys.modules[module_name]
    if not hasattr(plugin_module, plugin_runner):
        logger.error(f"{plugin_runner} not found")
        return
    runner = getattr(plugin_module, plugin_runner)
    try:
        runner(data)
    except Exception as e:
        logger.error(e)


def file_failed_in_history(self, path):
    return False


def should_file_be_added_to_task_list(self, path):
    if not os.path.exists(path):
        return False, [], 0
    return getattr(self, Patch.get_real_name("should_file_be_added_to_task_list"))(path)


def scan_library_path(self, library_name, library_path, library_id):
    plugin_ids = ["kmarius_hacks", "kmarius_library", ]
    for plugin_id in plugin_ids:
        _try_exec_runner(plugin_id, "emit_scan_start", {
            "library_id": library_id,
        })
    res = getattr(self, Patch.get_real_name("scan_library_path"))(library_name, library_path, library_id)
    return res


PATCHES = [
    Patch(
        FileTest,
        "file_failed_in_history",
        file_failed_in_history,
        "Run file testers on tasks even if they are marked as failed in the task history.",
        "This setting only affects newly spawned file tester threads."
    ),
    Patch(
        FileTest,
        "should_file_be_added_to_task_list",
        should_file_be_added_to_task_list,
        "Ensure that files exist before running the test flow.",
        "This setting only affects newly spawned file tester threads.",
    ),
    Patch(
        _get_thread_or_class(LibraryScannerManager),
        "scan_library_path",
        scan_library_path,
        "Enable emit_scan_start.",
        "This setting only affects newly spawned file tester threads."
    ),
]


class Settings(PluginSettings):
    settings = {
        "pause_workers_during_scan": False,
    }
    form_settings = {
        "pause_workers_during_scan": {
            "label": "Pause workers during scans.",
            "description": "Requires emit_scan_start and emit_scan_complete."
        },
    }

    for patch in PATCHES:
        settings.update({
            patch.setting_name: patch.setting
        })
        form_settings.update({
            patch.setting_name: patch.form_setting
        })

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


settings = Settings()

for patch in PATCHES:
    patch.patch(settings)

_scans_in_progress = set()


def _restart_maybe(delay: float):
    time.sleep(delay)
    if len(_scans_in_progress) == 0:
        foreman: Foreman = cast(Foreman, _get_thread("Foreman"))
        foreman.resume_all_worker_threads()


def emit_scan_start(data: dict):
    if settings.get_setting("pause_workers_during_scan"):
        foreman: Foreman = cast(Foreman, _get_thread("Foreman"))
        foreman.pause_all_worker_threads()
        _scans_in_progress.add(data["library_id"])


def emit_scan_complete(data: dict):
    if settings.get_setting("pause_workers_during_scan"):
        _scans_in_progress.remove(data["library_id"])
        threading.Thread(target=_restart_maybe, args=(4,), daemon=True).start()


def render_plugin_api(data: PluginApiData):
    match data["path"]:
        case "/":
            # we call this plugin's endpoint after startup to force loading of all plugins
            pass
        case "/stop_unmanic":
            # stops unmanic, docker will restart the container
            logger.info(f"Restart request received, sending SIGINT")
            os.kill(os.getpid(), signal.SIGINT)
        case path:
            logger.error(f"Unrecognized patch: {path}")

    data["content_type"] = "application/json"
    data["content"] = {}


def render_frontend_panel(data: PanelData):
    data["content_type"] = "text/html"

    with open(os.path.abspath(os.path.join(os.path.dirname(__file__), 'static', 'index.html'))) as file:
        content = file.read()
        data['content'] = content.replace("{cache_buster}", str(uuid.uuid4()))