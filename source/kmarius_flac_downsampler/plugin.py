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
        "tags_to_remove": {
            "target_sample_rate": "Target sample rate",
            "target_sample_fmt": "Sample format (see `ffmpeg -sample_fmts`)",
            "sample_rate_threshold": "Sample rate threshold; rates higher than this will be downsampled",
        },
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

    _, ext = os.path.splitext(data.get("path"))
    if ext.lower() != ".flac":
        return data

    data['exec_command'] = ['ffmpeg', '-i', data.get('file_in'),
                            '-map', '0', '-map_metadata', '0',
                            '-c:v', 'copy',  # keep album covers as is
                            '-sample_fmt', sample_fmt, '-ar', str(sample_rate),
                            data.get('file_out')]

    return data