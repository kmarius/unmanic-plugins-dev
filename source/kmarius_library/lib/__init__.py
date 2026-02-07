import logging

PLUGIN_ID = "kmarius_library"

logger = logging.getLogger(f"Unmanic.Plugin.{PLUGIN_ID}")


def prune_timestamps(library_id: int, fraction: float, set_last_update=True):
    raise NotImplementedError()


def prune_metadata(fraction: float):
    raise NotImplementedError()