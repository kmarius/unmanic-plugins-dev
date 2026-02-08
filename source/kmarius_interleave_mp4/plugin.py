import os

from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_interleave_mp4.lib.types import *
from kmarius_interleave_mp4.lib import logger, PLUGIN_ID
from kmarius_interleave_mp4.lib.mp4box import MP4Box


class Settings(PluginSettings):
    settings = {
        "interleave_parameter": 500,
    }
    form_settings = {
        "interleave_parameter": {
            "label": "Interleave parameter in ms",
            "description": "Processing is triggered if the current interleaving differs by more than one third of this value.",
        }
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


def is_interleaved(mp4box: dict, param: int) -> bool:
    for track in mp4box["tracks"]:
        if "chunk_duration_average" in track:
            chunk_duration_average = track["chunk_duration_average"]
            if chunk_duration_average < param * 2 / 3 or chunk_duration_average > param * 4 / 3:
                return False
    return True


def is_progressive(mp4box: dict) -> bool:
    return mp4box.get("progressive", False)


def on_library_management_file_test(data: FileTestData):
    library_id = data["library_id"]
    settings = Settings(library_id=library_id)
    param = int(settings.get_setting("interleave_parameter"))

    path = data["path"]

    ext = os.path.splitext(path)[1][1:].lower()
    if ext != "mp4":
        return

    if "mp4box" in data["shared_info"]:
        mp4box = data["shared_info"]["mp4box"]
    else:
        mp4box = MP4Box.probe(path)
        if mp4box:
            data["shared_info"]["mp4box"] = mp4box

    if mp4box is None:
        logger.error(f"No mp4box info: path={path}")
        return

    if not is_progressive(mp4box) or not is_interleaved(mp4box, param):
        data["issues"].append({
            'id': PLUGIN_ID,
            'message': f"Not interleaved: library_id={library_id} path={path}",
        })
        data["add_file_to_pending_tasks"] = True


def on_worker_process(data: ProcessItemData):
    settings = Settings(library_id=data["library_id"])
    param = int(settings.get_setting("interleave_parameter"))

    file_in = data.get("file_in")
    file_out = data.get('file_out')

    ext = os.path.splitext(file_in)[1][1:].lower()
    if ext != "mp4":
        return

    mp4box = MP4Box.probe(file_in)
    if mp4box is None:
        logger.error(f"No mp4box info: path={file_in}")
        return

    if is_progressive(mp4box) and is_interleaved(mp4box, param):
        logger.info(f"No processing required: path={file_in}")
        return

    data['exec_command'] = MP4Box.build_command(file_in, file_out, param)
    data['command_progress_parser'] = MP4Box.parse_progress