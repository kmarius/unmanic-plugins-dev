import os

from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_executor.lib import logger, init_task_data, put_task_data, get_task_data, clear_task_data
from kmarius_executor.lib.ffmpeg import StreamMapper, Parser
from kmarius_executor.lib.types import *


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


def on_library_management_file_test(data: FileTestData):
    task_data = init_task_data(data)
    library_id = data.get("library_id")
    path = data.get("path")

    if task_data["add_file_to_pending_tasks"]:
        data['add_file_to_pending_tasks'] = True
        put_task_data(library_id, path, task_data)
    else:
        # there might be leftover data, e.g. if a task is removed from the processing queue
        clear_task_data(library_id, path)


def on_worker_process(data: ProcessItemData):
    library_id = data["library_id"]
    path = data["original_file_path"]

    settings = Settings(library_id=library_id)
    apply_faststart = settings.get_setting("apply_faststart")

    task_data = get_task_data(library_id, path, delete=True)
    if task_data is None:
        # an unrelated plugin requested processing
        data["exec_command"] = []
        return

    file_in = data.get('file_in')
    ffprobe = task_data.get("ffprobe")

    mapper = PluginStreamMapper(task_data["mappings"])
    mapper.set_default_values(None, file_in, ffprobe)

    needs_remux = task_data.get("needs_remux", False)
    needs_faststart = task_data.get("moov_to_front", False)

    if mapper.streams_need_processing() or needs_remux or (needs_faststart and apply_faststart):
        file_out = data.get('file_out')

        if needs_remux:
            stem, _ = os.path.splitext(file_out)
            file_out = f"{stem}.mp4"
            data['file_out'] = file_out

        mapper.set_input_file(file_in)
        mapper.set_output_file(file_out)

        #  "-map", "-0:t", used in old script but fails here
        mapper.main_options += ["-map_metadata", "-1", "-map_chapters", "-1"]

        if apply_faststart:
            mapper.main_options += ["-movflags", "+faststart"]

        ffmpeg_args = mapper.get_ffmpeg_args()

        data['exec_command'] = ['ffmpeg']
        data['exec_command'] += ffmpeg_args

        parser = Parser(logger)
        parser.set_probe(ffprobe)
        data['command_progress_parser'] = parser.parse_progress