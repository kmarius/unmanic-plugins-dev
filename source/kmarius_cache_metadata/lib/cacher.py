from .ffmpeg.probe import Probe

import logging

logger = logging.getLogger("Unmanic.Plugin.kmarius_cache_metadata")


class Cacher:
    identifier = "None"
    """Used as table name and field name in the shared data dict"""

    @staticmethod
    def run_prog(path: str) -> dict:
        raise NotImplementedError()

    @classmethod
    def setting_name(cls):
        return f"cache_{cls.identifier}"


class FFprobeCacher(Cacher):
    identifier = "ffprobe"

    @staticmethod
    def run_prog(path: str) -> dict:
        probe = Probe(logger)
        if not probe.file(path):
            return {}
        return probe.get_probe()


class MediaInfoCacher(Cacher):
    identifier = "mediainfo"

    @staticmethod
    def run_prog(path: str) -> dict:
        return {
            "path": path,
            "data": "mediainfo",
        }


CACHERS = [FFprobeCacher, MediaInfoCacher]