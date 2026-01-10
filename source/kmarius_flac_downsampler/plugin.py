#!/usr/bin/env python3

import logging
import os

from kmarius_flac_downsampler.lib.ffmpeg import Probe
from unmanic.libs.unplugins.settings import PluginSettings

logger = logging.getLogger("Unmanic.Plugin.kmarius_flac_downsampler")


class Settings(PluginSettings):
    settings = {
        "target_sample_rate": 44100,
        "target_sample_fmt": 's16',
        "sample_rate_threshold": 48000,
    }
    form_settings = {
        "target_sample_rate": {
            "label": "Fallback sample rate",
            "description": "Sample rate to use if the input is not a multiple of 48000 or 44100."
        },
        "target_sample_fmt": {
            "label": "Sample format",
            "description": "See `ffmpeg -sample_fmts`",
        },
        "sample_rate_threshold": {
            "label": "Sample rate threshold; ",
            "description": "Rates higher than this value will be downsampled."
        }
    }


def on_library_management_file_test(data):
    settings = Settings(library_id=data.get('library_id'))
    thresh = settings.get_setting('sample_rate_threshold')

    path = data.get("path")
    _, ext = os.path.splitext(path)
    if ext.lower() != ".flac":
        return data

    probe = Probe(logger, allowed_mimetypes=['audio'])
    if not probe.file(path):
        return None

    for stream_info in probe.get('streams', {}):
        if 'sample_rate' in stream_info:
            if int(stream_info['sample_rate']) > thresh:
                data['add_file_to_pending_tasks'] = True
                data["issues"].append({
                    "id": "kmarius_flac_downsampler",
                    "message": f"sample rate too high: {path}"
                })

    return data


def on_worker_process(data):
    settings = Settings(library_id=data.get('library_id'))
    sample_rate = settings.get_setting('target_sample_rate')
    sample_fmt = settings.get_setting('target_sample_fmt')

    path = data.get('file_in')
    _, ext = os.path.splitext(path)
    if ext.lower() != ".flac":
        return data

    probe = Probe(logger, allowed_mimetypes=['audio'])
    if not probe.file(path):
        return data

    for stream_info in probe.get('streams', {}):
        if 'sample_rate' in stream_info:
            current_sample_rate = int(stream_info['sample_rate'])
            if current_sample_rate % 44100 == 0:
                sample_rate = 44100
            elif current_sample_rate % 48000 == 0:
                sample_rate = 48000

    data['exec_command'] = ['ffmpeg', '-i', path,
                            '-map', '0', '-map_metadata', '0',
                            '-c:v', 'copy',  # keep album covers as is
                            "-af", "aresample=resampler=soxr",
                            '-sample_fmt', sample_fmt, '-ar', str(sample_rate),
                            data.get('file_out')]

    return data