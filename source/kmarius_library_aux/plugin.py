import logging
import os

from kmarius_library.lib import timestamps

logger = logging.getLogger("Unmanic.Plugin.kmarius_library_aux")


def on_library_management_file_test(data: dict):
    if "shared_info" not in data or "kmarius_library" not in data["shared_info"]:
        return data
    library_id = data["library_id"]
    settings = data["shared_info"]["kmarius_library"]
    if settings.get_setting("incremental_scan_enabled"):
        path = data["path"]
        mtime = int(os.path.getmtime(path))
        if not settings.get_setting("quiet_incremental_scan"):
            logger.info(f"Updating timestamp path={path} library_id={library_id} to {mtime}")
        timestamps.put(library_id, path, mtime)
    return data