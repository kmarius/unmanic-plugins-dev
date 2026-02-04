import time

from unmanic.libs.unmodels import Libraries
from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_debug.lib.plugin_types import *
from kmarius_debug.lib import logger, PLUGIN_ID


class Settings(PluginSettings):
    settings = {
        "force_process_first_n": 0,
        "slow_test_ms": 0,
    }
    form_settings = {
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


_scan_info = {}
for lib in Libraries().select().where(Libraries.enable_remote_only == False):
    _scan_info.update({
        lib.id: {
            "num_forced": 0,
            "num_processed": 0,
        }
    })


def on_library_management_file_test(data: FileTestData):
    library_id = data["library_id"]
    path = data["path"]
    settings = Settings(library_id=library_id)

    logger.info(f"testing library_id={library_id} path={path}")
    slow_test_ms = int(settings.get_setting("slow_test_ms"))
    if slow_test_ms > 0:
        time.sleep(slow_test_ms / 1000.0)

    force_process_first_n = int(settings.get_setting("force_process_first_n"))
    if force_process_first_n > 0 and _scan_info[library_id]["num_forced"] < force_process_first_n:
        data["add_file_to_pending_tasks"] = True
        data["issues"].append({
            'id': PLUGIN_ID,
            'message': f"force processing: library_id={library_id} path={path}"
        })
        _scan_info[library_id]["num_forced"] += 1
        return


def on_worker_process(data: ProcessItemData):
    library_id = data["library_id"]
    path = data["file_in"]

    global _scan_info
    _scan_info[library_id]["num_processed"] += 1
    if _scan_info[library_id]["num_processed"] >= _scan_info[library_id]["num_forced"]:
        logger.info("all forced tasks processed, resetting counters")
        _scan_info[library_id] = {
            "num_forced": 0,
            "num_processed": 0,
        }

    logger.info(f"processing library_id={library_id} path={path}")
    data["exec_command"] = ["sh", "-c", "echo 0; sleep 1; echo 50; sleep 1; echo 100; touch $1", "_", data["file_in"]]
    data["command_progress_parser"] = lambda line: {"percent": int(line)}


def on_postprocessor_task_results(data: TaskResultData):
    library_id = data["library_id"]
    path = data["final_cache_path"]
    logger.info(f"post-processing library_id={library_id} path={path}")


def _render_frontend_panel(data: PanelData):
    pass


def _render_plugin_api(data: PluginApiData):
    pass