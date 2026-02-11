import logging

from kmarius_executor.lib import init_task_data

logger = logging.getLogger("Unmanic.Plugin.kmarius_data_handler")


def on_library_management_file_test(data: dict):
    task_data = init_task_data(data)

    data_streams = task_data["streams"]["data"]
    data_mappings = {}

    # remove all streams
    for idx, stream_info in enumerate(data_streams):
        data_mappings[idx] = {
            'stream_mapping': [],
            'stream_encoding': [],
        }

    task_data["mappings"]["data"] = data_mappings
    if len(data_mappings) > 0:
        task_data["add_file_to_pending_tasks"] = True