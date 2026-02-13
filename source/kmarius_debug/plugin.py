import time

from unmanic.libs.unmodels import Libraries
from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_debug.lib.types import *
from kmarius_debug.lib import logger, PLUGIN_ID


class Settings(PluginSettings):
    settings = {
        "force_process_first_n": 0,
        "skip_after_force_n": False,
        "slow_test_ms": 0,
        "processing_duration_s": 1,
        "fail_processing": False,
    }
    form_settings = {
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


_scan_info = {}


def _reset_scan_info(library_id: int):
    _scan_info[library_id] = {
        "forced": set(),
        "num_forced": 0,
        "num_processed": 0,
    }


for lib in Libraries().select().where(Libraries.enable_remote_only == False):
    _reset_scan_info(lib.id)


def on_library_management_file_test(data: FileTestData):
    library_id = data["library_id"]
    path = data["path"]
    settings = Settings(library_id=library_id)

    logger.info(f"testing library_id={library_id} path={path}")
    slow_test_ms = int(settings.get_setting("slow_test_ms"))
    if slow_test_ms > 0:
        time.sleep(slow_test_ms / 1000.0)

    force_process_first_n = int(settings.get_setting("force_process_first_n"))
    if force_process_first_n > 0:
        if _scan_info[library_id]["num_forced"] < force_process_first_n:
            data["add_file_to_pending_tasks"] = True
            data["issues"].append({
                'id': PLUGIN_ID,
                'message': f"force processing: library_id={library_id} path={path}"
            })
            _scan_info[library_id]["num_forced"] += 1
            _scan_info[library_id]["forced"].add(path)
        elif settings.get_setting("skip_after_force_n"):
            data["add_file_to_pending_tasks"] = False
            data["issues"].append({
                'id': PLUGIN_ID,
                'message': f"skipping after forcing n: library_id={library_id} path={path}"
            })
        return


def on_worker_process(data: ProcessItemData):
    library_id = data["library_id"]
    path = data["file_in"]
    settings = Settings(library_id=library_id)

    global _scan_info
    if path in _scan_info[library_id]["forced"]:
        _scan_info[library_id]["num_processed"] += 1
    if _scan_info[library_id]["num_processed"] >= _scan_info[library_id]["num_forced"]:
        logger.info("all forced tasks processed, resetting counters")
        _reset_scan_info(library_id)

    duration = int(settings.get_setting("processing_duration_s"))
    logger.info(f"processing library_id={library_id} path={path} for {duration} seconds")

    updates_per_second = 4
    steps = duration * updates_per_second
    sleep_time = 1.0 / updates_per_second
    command = "; ".join([f"echo {i * 100 // steps}; sleep {sleep_time}" for i in range(steps)])
    command += "; echo 100; touch $1"

    if settings.get_setting("fail_processing"):
        command += "; exit 1"

    data["exec_command"] = ["bash", "-c", command, "_", data["file_in"]]
    data["command_progress_parser"] = lambda line: {"percent": int(line)}


def on_postprocessor_task_results(data: TaskResultData):
    library_id = data["library_id"]
    path = data["final_cache_path"]
    logger.info(f"post-processing library_id={library_id} path={path}")
    logger.info(data)


def _render_frontend_panel(data: PanelData):
    pass


def _render_plugin_api(data: PluginApiData):
    pass