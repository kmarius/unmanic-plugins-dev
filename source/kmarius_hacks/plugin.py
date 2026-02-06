import os.path
import signal
import subprocess
import uuid

from unmanic.libs import common
from unmanic.libs.filetest import FileTest
from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_hacks.lib import logger, PLUGIN_ID
from kmarius_hacks.lib.plugin_types import *

AUTOSTART_SCRIPT = os.path.join(common.get_home_dir(), ".unmanic",
                                "plugins", PLUGIN_ID, "init.d", "autostart.sh")


class Patch:
    def __init__(self, clazz, method_name, new_method, label, description):
        self._clazz = clazz
        self._method_name = method_name
        self._old_name = Patch.get_real_name(method_name)
        self._new_method = new_method
        self.setting_name = f"{self._clazz.__name__}.{self._method_name}"
        self.setting = False
        self.form_setting = {
            "label": label,
            "description": description,
        }

    def apply(self):
        if not hasattr(self._clazz, self._old_name):
            logger.info(f"Patching {self.setting_name}")
            setattr(self._clazz, self._old_name, getattr(self._clazz, self._method_name))
            setattr(self._clazz, self._method_name, self._new_method)

    def remove(self):
        if hasattr(self._clazz, self._old_name):
            logger.info(f"Removing patch {self.setting_name}")
            setattr(self._clazz, self._method_name, getattr(self._clazz, self._old_name))
            delattr(self._clazz, self._old_name)

    def patch(self, settings):
        if settings.get_setting(self.setting_name):
            self.apply()
        else:
            self.remove()

    @staticmethod
    def get_real_name(name):
        return f"_original_{name}"


def file_failed_in_history(self, path):
    return False


def should_file_be_added_to_task_list(self, path):
    if not os.path.exists(path):
        return False, [], 0
    return getattr(self, Patch.get_real_name("should_file_be_added_to_task_list"))(path)


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
    )
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

    data["content_type"] = "application/json"
    data["content"] = {}


if settings.get_setting("enable_data_panel"):
    def render_frontend_panel(data: PanelData):
        data["content_type"] = "text/html"

        with open(os.path.abspath(os.path.join(os.path.dirname(__file__), 'static', 'index.html'))) as file:
            content = file.read()
            data['content'] = content.replace("{cache_buster}", str(uuid.uuid4()))