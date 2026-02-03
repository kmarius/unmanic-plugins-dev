import json
import subprocess
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
            return MP4Box.probe(path)
        except Exception as e:
            logger.error(e)
            return None


PROVIDERS = [
    FFprobeProvider,
    MediaInfoProvider,
    MP4BoxProvider,
]