#!/usr/bin/env python3

import os

from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_interleave_mp4.lib.plugin_types import *
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


def needs_interleave(mp4box: dict, param: int, path) -> bool:
    for track in mp4box["tracks"]:
        if track["handler_name"] == "VideoHandler":
            chunk_duration_average = track["chunk_duration_average"]
            if chunk_duration_average < param * 2 / 3 or chunk_duration_average > param * 4 / 3:
                return True
        if track["handler_name"] == "unknown":
            logger.warning(f"Unknown handlers in {path}: {mp4box}")
    return False


def on_library_management_file_test(data: FileTestData):
    library_id = data["library_id"]
    settings = Settings(library_id=library_id)
    param = int(settings.get_setting("interleave_parameter"))

    path = data["path"]
    ext = os.path.splitext(path)[-1][1:].lower()

    if ext != "mp4":
        return

    if "mp4box" in data["shared_info"]:
        mp4box = data["shared_info"]["mp4box"]
    else:
        mp4box = MP4Box.probe(path)

    if mp4box is None:
        logger.error(f"No mp4box info for {path}")
        return

    if needs_interleave(mp4box, param, path):
        data["issues"].append({
            'id': PLUGIN_ID,
            'message': f"not interleaved: library_id={library_id} path={path}",
        })
        data["add_file_to_pending_tasks"] = True


def on_worker_process(data: ProcessItemData):
    settings = Settings(library_id=data["library_id"])
    param = int(settings.get_setting("interleave_parameter"))

    file_in = data.get("file_in")
    file_out = data.get('file_out')

    ext = os.path.splitext(file_in)[-1][1:].lower()

    if ext != "mp4":
        return

    data['exec_command'] = ['MP4Box', '-inter', str(param), file_in, '-out', file_out]
    data['command_progress_parser'] = MP4Box.parse_progress