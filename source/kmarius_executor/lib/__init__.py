import logging

from kmarius_executor.lib.ffmpeg import Probe

PLUGIN_ID = "kmarius_executor"

logger = logging.getLogger(f"Unmanic.Plugin.{PLUGIN_ID}")


def streams_from_probe(probe_info: dict) -> dict:
    streams = {
        "audio": [],
        "video": [],
        "subtitle": [],
        "data": [],
        "attachment": []
    }
    for stream_info in probe_info.get('streams', {}):
        codec_type = stream_info.get('codec_type', '').lower()
        streams[codec_type].append(stream_info)

    # store stream idx in the actual stream info
    for codec_type, streams_infos in streams.items():
        for idx, stream in enumerate(streams_infos):
            stream["idx"] = idx

    return streams


def init_task_data(data: dict) -> dict:
    shared_info = data["shared_info"]
    if "task_data" not in shared_info:
        shared_info["task_data"] = {
            "add_file_to_pending_tasks": False,
            "streams": streams_from_probe(shared_info["ffprobe"]),
            "mappings": {},
            "ffprobe": shared_info["ffprobe"],
        }
    return shared_info["task_data"]


# this is how we pass task data from tester to processor
# obviously this is cleared on startup and plugin update, but not on config change.
_task_data = {}


def put_task_data(library_id: int, path: str, data: dict):
    _task_data[(library_id, path)] = data


def clear_task_data(library_id: int, path: str):
    if (library_id, path) in _task_data:
        del _task_data[(library_id, path)]


def get_task_data(library_id: int, path: str, delete=False):
    data = _task_data.get((library_id, path), None)
    if delete and data:
        del _task_data[(library_id, path)]
    return data