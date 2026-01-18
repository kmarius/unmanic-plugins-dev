#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

from kmarius_executor.lib import lazy_init
import os

logger = logging.getLogger("Unmanic.Plugin.kmarius_container_handler")


def on_library_management_file_test(data):
    kmarius = lazy_init(data, logger)

    split_file_in = os.path.splitext(data.get("path"))
    extension = split_file_in[1].lstrip(".")

    if extension != "mp4":
        kmarius["needs_remux"] = True
        kmarius["add_file_to_pending_tasks"] = True

    return None
