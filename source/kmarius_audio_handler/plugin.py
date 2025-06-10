#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

from kmarius.lib import lazy_init

logger = logging.getLogger("Unmanic.Plugin.kmarius_audio_handler")


def stream_is_eng(stream_info):
    return stream_info.get("tags", {}).get("language", "").lower() == "eng"


# try to find an english language stream and return its index. If there are multiple, returns one with the most channels
def search_eng_idx(streams):
    eng_idx = None
    eng_channels = None
    for idx, stream_info in enumerate(streams):
        if stream_is_eng(stream_info):
            channels = stream_info.get("channels", 0)
            if eng_idx is None or channels > eng_channels:
                eng_idx = idx
                eng_channels = channels
    return eng_idx


# convert non-aac streams to aac
def audio_stream_mapping(stream_info, idx):
    # TODO: convert > 6 channels to 6?
    codec_name = stream_info["codec_name"]
    if codec_name != "aac":
        logger.info(f"converting audio stream {idx} from {codec_name}")
        stream_encoding = ['-c:a:{}'.format(idx), "aac"]
        if 'channels' in stream_info:
            channels = int(stream_info.get('channels'))
            if int(channels) > 6:
                channels = 6
            calculated_bitrate = channels * 64
            stream_encoding += [
                f'-ac:a:{idx}', f'{channels}', f'-b:a:{idx}',
                f"{calculated_bitrate}k"
            ]
        return {
            'stream_mapping':  ['-map', '0:a:{}'.format(idx)],
            'stream_encoding': stream_encoding,
        }
    return None


def on_library_management_file_test(data):
    kmarius = lazy_init(data, logger)

    # TODO: add functionality for foreign language films

    audio_streams = kmarius["streams"]["audio"]
    audio_mappings = {}

    # try to find an english language stream
    eng_idx = search_eng_idx(audio_streams)

    for idx, stream_info in enumerate(audio_streams):
        # remove non-eng streams if there is an english one
        if eng_idx is None or idx == eng_idx:
            mapping = audio_stream_mapping(stream_info, idx)
        else:
            mapping = {
                'stream_mapping':  [],
                'stream_encoding': [],
            }
        if mapping:
            audio_mappings[idx] = mapping

    kmarius["mappings"]["audio"] = audio_mappings
    if len(audio_mappings) > 0:
        kmarius["add_file_to_pending_tasks"] = True

    return None
