import logging

from kmarius_executor.lib import lazy_init

logger = logging.getLogger("Unmanic.Plugin.kmarius_attachment_handler")


def on_library_management_file_test(data: dict):
    mydata = lazy_init(data, logger)

    attachment_streams = mydata["streams"]["attachment"]
    attachment_mappings = {}

    # remove all streams
    for idx, stream_info in enumerate(attachment_streams):
        attachment_mappings[idx] = {
            'stream_mapping': [],
            'stream_encoding': [],
        }

    mydata["mappings"]["attachment"] = attachment_mappings

    if len(attachment_mappings) > 0:
        mydata["add_file_to_pending_tasks"] = True