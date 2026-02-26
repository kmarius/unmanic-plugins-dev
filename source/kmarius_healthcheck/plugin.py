import re
import time
import os
import subprocess
import datetime
from typing import Tuple

from unmanic.libs.unplugins.settings import PluginSettings
from unmanic.libs import common

from kmarius_healthcheck.lib.types import *
from kmarius_healthcheck.lib import logger, PLUGIN_ID

ISSUES_FILE = os.path.join(common.get_home_dir(), ".unmanic", "userdata", PLUGIN_ID, "issues.csv")


class Settings(PluginSettings):
    settings = {
    }
    form_settings = {
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


def _cropdetect(path: str, ss=0, t: int = None) -> Tuple[int, int]:
    command = ["ffmpeg", "-i", path, "-ss", f"{ss}"]
    if t is not None:
        command += ["-t", f"{t}"]
    command += ["-vf", "cropdetect", "-f", "null", "-"]

    pipe = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, err = pipe.communicate()

    crops = {}
    # rarely the output looks like crop=-XX:-YY:...
    for crop in re.compile(r'crop=-?(\d+):-?(\d+):\d+:\d+').findall(out.decode('utf-8')):
        if crop not in crops:
            crops[crop] = 0
        crops[crop] += 1

    crops = list(crops.items())
    crops.sort(key=lambda x: x[1], reverse=True)

    width, height = crops[0][0]
    return int(width), int(height)


def _has_black_bars(path: str, probe: dict) -> bool:
    duration = int(float(probe["format"]["duration"]))

    for stream in probe.get("streams"):
        if stream["codec_type"] == "video":
            width = stream["width"]
            height = stream["height"]
            break

    # detected dimensions are often slightly different, but I've never seen it higher than 16 pixels
    thresh = 16

    if duration > 60:
        crop_width, crop_height = _cropdetect(path, ss=30, t=30)
        if not (width - crop_width > thresh or height - crop_height > thresh):
            return False

    # check again 5 minutes in, if possible
    ss, t = 300, 30
    if duration < 330:
        ss = duration - 30
        t = None
        if ss < 0:
            ss = 0

    crop_width, crop_height = _cropdetect(path, ss=ss, t=t)
    return width - crop_width > thresh or height - crop_height > thresh


def _has_video(probe: dict) -> bool:
    streams = probe.get("streams")
    for stream in streams:
        if stream["codec_type"] == "video":
            return True
    return False


def _has_audio(probe: dict) -> bool:
    streams = probe.get("streams")
    for stream in streams:
        if stream["codec_type"] == "audio":
            return True
    return False


def _has_only_stereo(probe: dict) -> bool:
    streams = probe.get("streams")
    max_channels = 0
    for stream in streams:
        if stream["codec_type"] == "audio":
            channels = stream["channels"]
            if channels > max_channels:
                max_channels = channels
    return max_channels == 2


def _is_truncated(mediainfo: dict) -> bool:
    if "extra" in mediainfo and "IsTruncated" in mediainfo["extra"]:
        return mediainfo["extra"]["IsTruncated"] == "Yes"
    return False


def on_library_management_file_test(data: FileTestData, **kwargs):
    library_id = data["library_id"]
    path = data["path"]
    probe = data["shared_info"].get("ffprobe")
    mediainfo = data["shared_info"].get("mediainfo")

    issues = []

    if _is_truncated(mediainfo):
        issues.append("Truncated")

    if not _has_audio(probe):
        issues.append("No audio")
    else:
        if _has_only_stereo(probe):
            issues.append("Stereo only")

    if not _has_video(probe):
        issues.append("No video")
    else:
        if _has_black_bars(path, probe):
            issues.append("Black bars")

    if issues:
        logger.info(f"Found {len(issues)} issues: {', '.join(issues)}")
        with open(ISSUES_FILE, "a") as file:
            now = datetime.datetime.now().isoformat()
            file.write(f"{now};{library_id};{path};{','.join(issues)}\n")


def render_frontend_panel(data: PanelData, **kwargs):
    pass


def render_plugin_api(data: PluginApiData, **kwargs):
    pass