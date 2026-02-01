#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

from kmarius_executor.lib import lazy_init
import os

logger = logging.getLogger("Unmanic.Plugin.kmarius_container_handler")


def on_library_management_file_test(data: dict):
    mydata = lazy_init(data, logger)

    _, ext = os.path.splitext(data.get("path"))
    ext = ext.lower().lstrip(".")

    if ext != "mp4":
        mydata["needs_remux"] = True
        mydata["add_file_to_pending_tasks"] = True