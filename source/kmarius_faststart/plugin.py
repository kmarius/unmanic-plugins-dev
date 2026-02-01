#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import subprocess

from kmarius_executor.lib import lazy_init

logger = logging.getLogger("Unmanic.Plugin.kmarius_faststart_handler")


def is_moov_at_front(path: str) -> bool:
    command = ["ffprobe", "-v", "trace", path]
    pipe = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, err = pipe.communicate()

    output = out.decode("utf-8")
    moov_idx = output.find("moov")
    mdat_idx = output.find("mdat")

    # apparently the output of ffprobe is not always reliable w.r.t atoms
    if moov_idx == -1 or mdat_idx == -1:
        return False

    return moov_idx < mdat_idx


def on_library_management_file_test(data: dict):
    mydata = lazy_init(data, logger)
    path = data.get("path")

    if mydata.get("add_file_to_pending_tasks", False):
        # we only need to test if no other ffmpeg commands run, because we always move the moov atom
        return data

    _, ext = os.path.splitext(path)
    ext = ext.lstrip(".").lower()

    if ext == "mp4" and not is_moov_at_front(path):
        data["issues"].append({
            'id': "kmarius_faststart_handler",
            'message': f"MOOV atom not at front: {path}",
        })
        mydata["moov_to_front"] = True
        mydata["add_file_to_pending_tasks"] = True