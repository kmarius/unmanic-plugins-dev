import logging
import os

from kmarius_executor.lib import init_task_data

logger = logging.getLogger("Unmanic.Plugin.kmarius_container_handler")


def on_library_management_file_test(data: dict):
    task_data = init_task_data(data)

    ext = os.path.splitext(data.get("path"))[1][1:].lower()
    if ext != "mp4":
        task_data["needs_remux"] = True
        task_data["add_file_to_pending_tasks"] = True