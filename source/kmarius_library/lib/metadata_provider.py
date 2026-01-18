import json
import subprocess
from typing import Optional

from .ffmpeg.probe import Probe

import logging

logger = logging.getLogger("Unmanic.Plugin.kmarius_cache_metadata")


class MetadataProvider:
    name = "None"
    """Used as table name and field name in the shared data dict"""

    @staticmethod
    def run_prog(path: str) -> Optional[dict]:
        raise NotImplementedError()

    @classmethod
    def setting_name(cls):
        return f"cache_{cls.name}"


class FFProbeProvider(MetadataProvider):
    name = "ffprobe"

    @staticmethod
    def run_prog(path: str) -> Optional[dict]:
        probe = Probe(logger)
        if not probe.file(path):
            return None
        return probe.get_probe()


class MediaInfoProvider(MetadataProvider):
    name = "mediainfo"

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


PROVIDERS = [
    FFProbeProvider,
    MediaInfoProvider
]