#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import subprocess

import re

from kmarius.lib import lazy_init

logger = logging.getLogger("Unmanic.Plugin.kmarius_video_handler")


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
        if line.startswith(f"Statistics for track number {stream_index}:"):
            return int(line.split()[-1])
    return None


# change everything that is not 8bit h264 with a reasonable bit rate
def needs_encoding(stream_info, path):
    codec_name = stream_info["codec_name"]
    if stream_info["codec_name"] != "h264":
        logger.info(f"wrong codec: {codec_name}")
        return True

    bit_rate = _get_bitrate(stream_info, path)
    if bit_rate is not None and bit_rate > 4500000:
        logger.info(f"bitrate too high: {bit_rate}")
        return True

    pixel_fmt = stream_info["pix_fmt"] if "pix_fmt" in stream_info else None
    if pixel_fmt is not None and pixel_fmt != "yuv420p":
        logger.info(f"wrong pixel_fmt: {pixel_fmt}")
        return True

    return False


def video_stream_mapping(stream_info, idx, path):
    # remove images
    codec_name = stream_info["codec_name"]
    if codec_name in ["png", "mjpeg"]:
        logger.info(f"removing image: {codec_name}")
        return {
            'stream_mapping':  [],
            'stream_encoding': [],
        }

    if needs_encoding(stream_info, path):
        stream_encoding = [f'-c:v:{idx}', "libx264",
                           "-pix_fmt", "yuv420p", f"-b:v:{idx}", "3000000"]
        return {
            'stream_mapping':  ['-map', '0:v:{}'.format(idx)],
            'stream_encoding': stream_encoding,
        }

    return None


def on_library_management_file_test(data):
    kmarius = lazy_init(data, logger)

    video_streams = kmarius["streams"]["video"]
    video_mappings = {}

    for idx, stream_info in enumerate(video_streams):
        mapping = video_stream_mapping(stream_info, idx, data.get('path'))
        if mapping:
            video_mappings[idx] = mapping

    kmarius["mappings"]["video"] = video_mappings
    if len(video_mappings) > 0:
        kmarius["add_file_to_pending_tasks"] = True

    return None