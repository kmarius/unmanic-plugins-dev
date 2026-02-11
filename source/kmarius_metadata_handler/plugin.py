import json
import subprocess

from kmarius_executor.lib import init_task_data
from kmarius_metadata_handler.lib.types import FileTestData


def on_library_management_file_test(data: FileTestData):
    shared_info = data["shared_info"]
    task_data = init_task_data(data)
    ffprobe = shared_info["ffprobe"]
    mediainfo = shared_info.get("mediainfo")

    path = data["path"]

    # check file itself for metadata
    tags = ffprobe.get("format", {}).get("tags", {})
    if "title" in tags or "comment" in tags:
        task_data["has_metadata"] = True

    if mediainfo is None:
        command = ["mediainfo", "--output=JSON", path]
        pipe = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out, err = pipe.communicate()
        mediainfo = json.loads(out.decode("utf-8"))

    has_track_metadata = False
    for track in mediainfo.get("media", {}).get("track", []):
        # TODO: we are removing title, name, comment, handler_name, vendor_id and should probably als check these here
        if "Title" in track or "Comment" in track:
            has_track_metadata = True
            break

    if has_track_metadata:
        task_data["has_metadata"] = True

        # check all streams for metadata
        streams = {}
        for stream_info in ffprobe.get('streams'):
            stream_type = stream_info.get('codec_type', '').lower()
            if not stream_type in streams:
                streams[stream_type] = []
            streams[stream_type].append(stream_info)

        chars = {
            'video': 'v',
            'audio': 'a',
            'subtitle': 's',
            'data': 'd',
            'attachment': 'a',
        }

        mappings = task_data["mappings"]
        for stream_type in streams.keys():
            if not stream_type in mappings:
                mappings[stream_type] = {}
            if not stream_type in chars:
                continue
            stream_mapping = mappings[stream_type]
            c = chars[stream_type]
            for i, stream_info in enumerate(streams[stream_type]):
                if i in stream_mapping:
                    mapping = stream_mapping[i]
                    # len == 0 means streams are removed
                    if len(mapping["stream_encoding"]) > 0:
                        mapping["stream_encoding"] += [
                            f"-metadata:s:a:{i}", "title=",
                            f"-metadata:s:a:{i}", "name=",
                            f"-metadata:s:a:{i}", "comment=",
                            f"-metadata:s:a:{i}", "handler_name=",
                            f"-metadata:s:a:{i}", "vendor_id=",
                        ]
                else:
                    stream_mapping[i] = {
                        'stream_mapping': ['-map', f'0:{c}:{i}'],
                        'stream_encoding': [
                            f"-c:{c}:{i}", "copy",
                            f"-metadata:s:a:{i}", "title=",
                            f"-metadata:s:a:{i}", "name=",
                            f"-metadata:s:a:{i}", "comment=",
                            f"-metadata:s:a:{i}", "handler_name=",
                            f"-metadata:s:a:{i}", "vendor_id=",
                        ],
                    }

    if task_data.get("has_metadata", False):
        task_data["add_file_to_pending_tasks"] = True
        data["issues"].append({
            "id": "kmarius_metadata_handler",
            "message": f"metadata found: {path}"
        })