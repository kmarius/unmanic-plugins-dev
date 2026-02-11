from kmarius_attachment_handler.lib.types import FileTestData
from kmarius_executor.lib import init_task_data


def on_library_management_file_test(data: FileTestData):
    task_data = init_task_data(data)

    attachment_streams = task_data["streams"]["attachment"]
    attachment_mappings = {}

    # remove all streams
    for idx, stream_info in enumerate(attachment_streams):
        attachment_mappings[idx] = {
            'stream_mapping': [],
            'stream_encoding': [],
        }

    task_data["mappings"]["attachment"] = attachment_mappings

    if len(attachment_mappings) > 0:
        task_data["add_file_to_pending_tasks"] = True