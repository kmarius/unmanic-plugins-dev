#!/usr/bin/env python3

import os
import re
import subprocess

from unmanic.libs.unplugins.settings import PluginSettings
from kmarius_interleave_mp4.lib.plugin_types import *
from kmarius_interleave_mp4.lib import logger


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


def mp4box_parse_infox(output: str) -> list[dict]:
    lines = output.splitlines()

    match = re.match(r'^# Movie Info - (\d+) tracks - TimeScale .*$', lines[0])
    num_tracks = int(match.group(1))

    def consume_stream(lines: list[str]):
        # Track 6 Info - ID 6 - TimeScale 1000000
        match = re.match(r'^# Track \d+ Info - ID (\d+) - TimeScale (\d+)$', lines[0])
        track = {
            "id": int(match.group(1)),
            "timescale": int(match.group(2)),
        }
        for line in lines[1:]:
            line = line.strip()
            if line.startswith('#'):
                # next track header
                break
            if line.startswith('Handler name: '):
                track["handler_name"] = line[len('Handler Name: '):]
            if line.startswith('Chunk durations: '):
                # Chunk durations: min 125 ms - max 1000 ms - average 912 ms
                match = re.match(r'^Chunk durations:.* average (\d+) ms$', line)
                track["chunk_duration_average"] = int(match.group(1))

        return track

    tracks = []

    idx = 1
    for i in range(num_tracks):
        # seek to stream start
        while idx < len(lines) and not lines[idx].startswith('#'):
            idx += 1

        tracks.append(consume_stream(lines[idx:]))
        idx += 1

    return tracks


def mp4box_infox(path: str) -> list[dict]:
    proc = subprocess.run(["MP4Box", "-infox", path], capture_output=True)
    proc.check_returncode()
    return mp4box_parse_infox(proc.stderr.decode("utf-8"))


def needs_interleave(path: str, param: int) -> bool:
    tracks = mp4box_infox(path)
    for track in tracks:
        if track["handler_name"] == "VideoHandler":
            chunk_duration_average = track["chunk_duration_average"]
            if chunk_duration_average < param * 2 / 3 or chunk_duration_average > param * 4 / 3:
                return True
    return False


def on_library_management_file_test(data: FileTestData):
    settings = Settings(library_id=data["library_id"])
    param = int(settings.get_setting("interleave_parameter"))

    path = data["path"]
    ext = os.path.splitext(path)[-1][1:].lower()

    if ext != "mp4":
        return

    if needs_interleave(path, param):
        data["add_file_to_pending_tasks"] = True


def _parse_progress(line):
    percent = 100

    # ISO File Writing: |=================== | (99/100)
    match = re.search(r'\((\d+)/100\)', line)
    if match:
        percent = int(match.group(1))

    return {
        'percent': percent
    }


def on_worker_process(data: ProcessItemData):
    settings = Settings(library_id=data["library_id"])
    param = int(settings.get_setting("interleave_parameter"))

    file_in = data.get("file_in")
    file_out = data.get('file_out')

    ext = os.path.splitext(file_in)[-1][1:].lower()

    if ext != "mp4":
        return

    data['exec_command'] = ['MP4Box', '-inter', str(param), file_in, '-out', file_out]
    data['command_progress_parser'] = _parse_progress