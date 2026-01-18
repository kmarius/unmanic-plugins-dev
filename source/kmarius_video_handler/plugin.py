#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import subprocess
import re

from kmarius_executor.lib import lazy_init
from unmanic.libs.unplugins.settings import PluginSettings

logger = logging.getLogger("Unmanic.Plugin.kmarius_video_handler")


class Settings(PluginSettings):
    settings = {
        "target_bitrate": 3000,
        "bitrate_cutoff": 4500,
    }
    form_settings = {
        "target_bitrate": {
            "label": "Target bitrate (kbit/s)",
            "description": "Target bitrate passed to the h264 encoder",
        },
        "bitrate_cutoff": {
            "label": "Bitrate cutoff (kbit/s)",
            "description": "Won't re-encode if current bitrate is smaller than this value.",
        },
    }


def _get_bitrate(stream_info, path):
    if "bit_rate" in stream_info:
        return int(stream_info["bit_rate"])
    if "tags" in stream_info:
        tags = stream_info["tags"]
        for key in tags.keys():
            if re.match("BPS.*", key):
                return int(tags[key])
    cmd = ["mkvinfo", "-t", path]
    output = subprocess.run(cmd, capture_output=True)
    stream_index = stream_info["index"]
    for line in str(output.stdout).split("\\n"):
        if line.startswith(f"Statistics for track number {stream_index + 1}:"):
            return int(line.split()[-1])
    return None


# change everything that is not 8bit h264 with a reasonable bit rate
def needs_encoding(stream_info, path, bitrate_cutoff):
    if stream_info["codec_name"] != "h264":
        return True

    bit_rate = _get_bitrate(stream_info, path)
    if bit_rate is None:
        logger.error(f"Could not determine bitrate for {path}")

    if bit_rate is not None and bit_rate > bitrate_cutoff:
        return True

    pixel_fmt = stream_info["pix_fmt"] if "pix_fmt" in stream_info else None
    if pixel_fmt is not None and pixel_fmt != "yuv420p":
        return True

    return False


def video_stream_mapping(stream_info, idx, path, target_bitrate, bitrate_cutoff):
    # remove images
    codec_name = stream_info["codec_name"]
    if codec_name in ["png", "mjpeg"]:
        return {
            'stream_mapping': [],
            'stream_encoding': [],
        }

    if needs_encoding(stream_info, path, bitrate_cutoff):
        stream_encoding = [f'-c:v:{idx}', "libx264", "-pix_fmt",
                           "yuv420p", f"-b:v:{idx}", f"{target_bitrate}"]
        return {
            'stream_mapping': ['-map', '0:v:{}'.format(idx)],
            'stream_encoding': stream_encoding,
        }

    return None


def on_library_management_file_test(data):
    kmarius = lazy_init(data, logger)

    settings = Settings(library_id=data.get('library_id'))
    target_bitrate = settings.get_setting('target_bitrate') * 1000
    bitrate_cutoff = settings.get_setting('bitrate_cutoff') * 1000

    video_streams = kmarius["streams"]["video"]
    video_mappings = {}

    for idx, stream_info in enumerate(video_streams):
        mapping = video_stream_mapping(stream_info, idx, data.get(
            'path'), target_bitrate, bitrate_cutoff)
        if mapping:
            video_mappings[idx] = mapping

    kmarius["mappings"]["video"] = video_mappings
    if len(video_mappings) > 0:
        kmarius["add_file_to_pending_tasks"] = True

    return None
