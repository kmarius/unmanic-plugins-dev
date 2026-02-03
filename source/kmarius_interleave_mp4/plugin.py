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
            "label": "Interleave Parameter in ms",
        }
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


def mp4box_parse_infox(output: str) -> list[dict]:
    lines = output.splitlines()
    idx = 0

    match = re.match('^# Movie Info - (\d+) tracks - TimeScale .*$', lines[idx])
    num_tracks = int(match.group(1))
    idx += 1

    def consume_stream(lines: list[str]):
        # Track 6 Info - ID 6 - TimeScale 1000000
        match = re.match('^# Track (\d+) Info - ID (\d+) - TimeScale (\d+)$', lines[0])
        track = {
            "number":    int(match.group(1)),
            "track_id":  int(match.group(2)),
            "timescale": int(match.group(3)),
        }
        for line in lines[1:]:
            line = line.strip()
            logger.info(line)
            if line.startswith('#'):
                # next track header
                break
            if line.startswith('Handler name: '):
                track["handler_name"] = line[len('Handler Name: '):]
            if line.startswith('Chunk durations: '):
                # Chunk durations: min 125 ms - max 1000 ms - average 912 ms
                match = re.match('^Chunk durations:.* average (\d+) ms$', line)
                track["chunk_duration_average"] = int(match.group(1))

        return track

    tracks = []

    for i in range(num_tracks):
        # seek to stream start
        while idx < len(lines) and not lines[idx].startswith('#'):
            idx += 1

        # consume the stream
        tracks.append(consume_stream(lines[idx:]))
        idx += 1

    return tracks


def mp4box_infox(path):
    proc = subprocess.run(["MP4Box", "-infox", path], capture_output=True)
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
    library_id = data["library_id"]
    settings = Settings(library_id=library_id)
    param = settings.get_setting("interleave_parameter")

    # run MP4Box to check interleaving
    path = data["path"]
    ext = os.path.splitext(path)[-1][1:].lower()

    if ext != "mp4":
        return

    if needs_interleave(path, param):
        data["add_file_to_pending_tasks"] = True


def parse_progress(line):
    percent = 100

    # ISO File Writing: |=================== | (99/100)
    match = re.search('\((\d+)/100\)', line)
    if match:
        percent = int(match.group(1))

    return {
        'percent': percent
    }


def on_worker_process(data: ProcessItemData):
    library_id = data["library_id"]
    settings = Settings(library_id=library_id)
    param = settings.get_setting("interleave_parameter")

    file_in = data.get("file_in")
    file_out = data.get('file_out')

    ext = os.path.splitext(file_in)[-1][1:].lower()

    if ext != "mp4":
        return

    data['exec_command'] = ['MP4Box', '-inter', str(param), file_in, '-out', file_out]
    data['command_progress_parser'] = parse_progress