from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_template.lib.types import *
from kmarius_template.lib import logger, PLUGIN_ID


class Settings(PluginSettings):
    settings = {
    }
    form_settings = {
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


def on_library_management_file_test(data: FileTestData, **kwargs):
    pass


def on_worker_process(data: ProcessItemData, **kwargs):
    pass


def on_postprocessor_task_results(data: TaskResultData, **kwargs):
    pass


def render_frontend_panel(data: PanelData, **kwargs):
    pass


def render_plugin_api(data: PluginApiData, **kwargs):
    pass