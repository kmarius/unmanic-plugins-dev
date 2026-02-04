#!/usr/bin/env python3

import logging
import os

from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_executor.lib import lazy_init
from kmarius_executor.lib.ffmpeg import StreamMapper, Parser

logger = logging.getLogger("Unmanic.Plugin.kmarius_executor")


class Settings(PluginSettings):
    settings = {
        "apply_faststart": True,
    }
    form_settings = {
        "apply_faststart": {
            "label": "Apply faststart for MP4 files",
            "description": "Disable this e.g. if the plugin is followed by the interleave plugin which does the same.",
        }
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


# we use this to pass data from the tester to the processor
kmarius_data = {}


class PluginStreamMapper(StreamMapper):
    def __init__(self, mappings: dict):
        super(PluginStreamMapper, self).__init__(
            logger, ['audio', "video", "subtitle", "data", "attachment"])
        self.mappings = mappings
        self.settings = None

    def set_default_values(self, settings, abspath, probe):
        self.abspath = abspath
        self.set_probe(probe)
        self.set_input_file(abspath)
        self.settings = settings

    def test_stream_needs_processing(self, stream_info: dict):
        stream_type = stream_info.get('codec_type', '').lower()
        if not stream_type in self.mappings:
            # no mappings for this type of stream
            return False
        return stream_info["idx"] in self.mappings[stream_type]

    def custom_stream_mapping(self, stream_info: dict, stream_id: int):
        stream_type = stream_info.get('codec_type', '').lower()
        return self.mappings[stream_type][stream_id]


def on_library_management_file_test(data: dict):
    mydata = lazy_init(data, logger)
    path = data.get("path")

    if mydata["add_file_to_pending_tasks"]:
        data['add_file_to_pending_tasks'] = True
        # pass data to the processor via global variable
        # TODO: do something more robust, this variable gets wiped on plugin reload
        global kmarius_data
        kmarius_data[path] = mydata


def on_worker_process(data: dict):
    settings = Settings(library_id=data.get("library_id"))
    apply_faststart = settings.get_setting("apply_faststart")

    path = data.get("original_file_path")
    if not path in kmarius_data:
        # an unrelated plugin requested processing
        data["exec_command"] = []
        return

    mydata = kmarius_data[path]
    del kmarius_data[path]

    probe = mydata.get("probe")
    path = data.get('file_in')

    mapper = PluginStreamMapper(mydata.get("mappings", {}))
    mapper.set_default_values(None, path, probe)

    needs_remux = mydata.get("needs_remux", False)
    needs_moov = mydata.get("moov_to_front", False)

    if mapper.streams_need_processing() or needs_remux or (needs_moov and apply_faststart):
        mapper.set_input_file(path)

        file_out = data.get('file_out')

        if needs_remux:
            stem, _ = os.path.splitext(file_out)
            file_out = f"{stem}.mp4"
            data['file_out'] = file_out

        mapper.set_output_file(file_out)

        #  "-map", "-0:t", used in old script but fails here
        mapper.main_options += ["-map_metadata", "-1", "-map_chapters", "-1"]

        if apply_faststart:
            mapper.main_options += ["-movflags", "+faststart"]

        ffmpeg_args = mapper.get_ffmpeg_args()

        data['exec_command'] = ['ffmpeg']
        data['exec_command'] += ffmpeg_args

        parser = Parser(logger)
        parser.set_probe(probe)
        data['command_progress_parser'] = parser.parse_progress