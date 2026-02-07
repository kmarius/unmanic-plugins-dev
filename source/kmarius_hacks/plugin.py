import os.path
import signal
import subprocess
import sys
import threading
import types
import uuid
from typing import Optional

from unmanic.libs import common
from unmanic.libs.filetest import FileTest
from unmanic.libs.unplugins import PluginExecutor
from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_hacks.lib import logger, PLUGIN_ID
from kmarius_hacks.lib.plugin_types import *

AUTOSTART_SCRIPT = os.path.join(common.get_home_dir(), ".unmanic",
                                "plugins", PLUGIN_ID, "init.d", "autostart.sh")


def critical(f):
    """Decorator to allow only one thread to execute this function at a time."""
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


def _get_thread(name: str) -> Optional[threading.Thread]:
    for thread in threading.enumerate():
        if thread.name == name:
            return thread
    return None


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


def _try_exec_runner(plugin_id, plugin_runner, data):
    executor = PluginExecutor()
    executor.get_plugin_settings(plugin_id)
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


def scan_library_path(self, library_path, library_id):
    _try_exec_runner("kmarius_library", "emit_scan_start", {
        "library_id": library_id,
    })
    res = getattr(self, Patch.get_real_name("scan_library_path"))(library_path, library_id)
    _try_exec_runner("kmarius_library", "emit_scan_complete", {
        "library_id": library_id,
    })
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
        _get_thread("LibraryScannerManager"),
        "scan_library_path",
        scan_library_path,
        "Enable emit_scan_start and emit_scan_complete.",
        "This setting only affects newly spawned file tester threads."
    ),
]


class Settings(PluginSettings):
    settings = {
        "enable_data_panel": False,
    }
    form_settings = {
        "enable_data_panel": {
            "label": "Enable data panel with restart button.",
            "description": "Disabling requires a restart."
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


@critical
def run_init_d_scripts():
    proc = subprocess.Popen(["/etc/cont-init.d/60-custom-setup-script"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # we read stdout completely before reading stderr, surely the script wouldn't fill up its stderr buffer
    for line in proc.stdout:
        line = line.decode("utf-8")
        if line[-1] == "\n":
            line = line[:-1]
        logger.info(line)
    for line in proc.stderr:
        line = line.decode("utf-8")
        if line[-1] == "\n":
            line = line[:-1]
        logger.error(line)

    proc.wait()
    logger.info(f"exit status: {proc.returncode}")


def render_plugin_api(data: PluginApiData):
    match data["path"]:
        case "/":
            # we call this plugin's endpoint after startup to force loading of all plugins
            pass
        case "/restart":
            # restarts inside a docker container, otherwise quits unmanic
            logger.info(f"Restart request received, sending SIGINT")
            os.kill(os.getpid(), signal.SIGINT)

            # the autostart script is only called on container start, so we do it now
            # TODO: do we need a higher delay or a mechanism to make sure unmanic has quit
            # and doesn't respond to the startup script before it shuts down?
            subprocess.call(['/usr/bin/sh', AUTOSTART_SCRIPT, "1"])
        case "/init":
            threading.Thread(target=run_init_d_scripts, daemon=True).start()
        case path:
            logger.error(f"Unrecognized patch: {path}")

    data["content_type"] = "application/json"
    data["content"] = {}


if settings.get_setting("enable_data_panel"):
    def render_frontend_panel(data: PanelData):
        data["content_type"] = "text/html"

        with open(os.path.abspath(os.path.join(os.path.dirname(__file__), 'static', 'index.html'))) as file:
            content = file.read()
            data['content'] = content.replace("{cache_buster}", str(uuid.uuid4()))