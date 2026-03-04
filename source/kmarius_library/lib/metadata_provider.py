import json
import subprocess
import os
from typing import Optional

from .ffmpeg.probe import Probe
from .mp4box import MP4Box
from . import logger


class MetadataProvider:
    name = "None"
    """Used as table name and field name in the shared data dict"""

    default_enabled = False

    @staticmethod
    def run_prog(path: str) -> Optional[dict]:
        raise NotImplementedError()

    @staticmethod
    def is_admissible(selfpath: str) -> bool:
        return True

    @classmethod
    def setting_name_enabled(cls):
        return f"cache_{cls.name}"


class FFprobeProvider(MetadataProvider):
    name = "ffprobe"
    default_enabled = True

    @staticmethod
    def run_prog(path: str) -> Optional[dict]:
        probe = Probe(logger)
        if not probe.file(path):
            return None
        return probe.get_probe()


class MediaInfoProvider(MetadataProvider):
    name = "mediainfo"
    default_enabled = False

    @staticmethod
    def run_prog(path: str) -> Optional[dict]:
        try:
            command = ["mediainfo", "--output=JSON", path]
            pipe = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            out, err = pipe.communicate()

            return json.loads(out.decode("utf-8"))
        except Exception as e:
            logger.error(e)
            return None


class MP4BoxProvider(MetadataProvider):
    name = "mp4box"
    default_enabled = False

    @staticmethod
    def run_prog(path: str) -> Optional[dict]:
        try:
            return MP4Box.probe(path, logger=logger)
        except Exception as e:
            logger.error(e)
            return None

    @staticmethod
    def is_admissible(path: str) -> bool:
        ext = os.path.splitext(path)[1][1:].lower()
        return ext == "mp4"


PROVIDERS = [
    FFprobeProvider,
    MediaInfoProvider,
    MP4BoxProvider,
]