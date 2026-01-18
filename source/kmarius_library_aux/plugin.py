#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os

from kmarius_library.lib import timestamps

logger = logging.getLogger("Unmanic.Plugin.kmarius_library_aux")


def on_library_management_file_test(data):
    if "shared_info" not in data or "kmarius_library" not in data["shared_info"]:
        return data
    library_id = data["library_id"]
    if data["shared_info"]["kmarius_library"]["incremental_scan"][library_id]:
        path = data["path"]
        mtime = int(os.path.getmtime(path))
        logger.info(f"Updating timestamp path={path} library_id={library_id} to {mtime}")
        timestamps.put(library_id, path, mtime)
    return data