from kmarius_stream_remover.lib.types import FileTestData
from kmarius_executor.lib import init_task_data


def on_library_management_file_test(data: FileTestData):
    task_data = init_task_data(data)

    for stream_type in ["attachment", "data"]:
        streams = task_data["streams"][stream_type]
        mappings = {}

        # remove all streams
        for idx, stream_info in enumerate(streams):
            mappings[idx] = {
                'stream_mapping': [],
                'stream_encoding': [],
            }

        task_data["mappings"][stream_type] = mappings

        if len(mappings) > 0:
            task_data["add_file_to_pending_tasks"] = True