#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os

from unmanic.libs.unplugins.settings import PluginSettings
from kmarius.lib import load_timestamp, store_timestamp

logger = logging.getLogger("Unmanic.Plugin.kmarius_incremental")

# TODO: add override setting
class Settings(PluginSettings):
    settings = {}

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)

def on_library_management_file_test(data):
    path = data.get("path")

    file_stat = os.stat(path)
    disk_timestamp = int(file_stat.st_mtime)
    stored_timestamp = load_timestamp(path)

    if stored_timestamp == disk_timestamp:
        logger.info(f"file unchanged: {path}")
        data['add_file_to_pending_tasks'] = False

    return


def on_postprocessor_task_results(data):
    # TODO: there could be multiple files here
    path = data["destination_files"][0]

    if data["task_processing_success"] and data["file_move_processes_success"]:
        file_stat = os.stat(path)
        timestamp = int(file_stat.st_mtime)
        store_timestamp(path, timestamp)

    return