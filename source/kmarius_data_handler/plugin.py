import logging

from kmarius_executor.lib import lazy_init

logger = logging.getLogger("Unmanic.Plugin.kmarius_data_handler")


def on_library_management_file_test(data: dict):
    mydata = lazy_init(data, logger)

    data_streams = mydata["streams"]["data"]
    data_mappings = {}

    # remove all streams
    for idx, stream_info in enumerate(data_streams):
        data_mappings[idx] = {
            'stream_mapping': [],
            'stream_encoding': [],
        }

    mydata["mappings"]["data"] = data_mappings
    if len(data_mappings) > 0:
        mydata["add_file_to_pending_tasks"] = True