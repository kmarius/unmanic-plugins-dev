#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os

from unmanic.libs.unplugins.settings import PluginSettings
from typing import Optional

try:
    from lib import exists, lookup, put, cacher, init_database
    from lib.plugin_types import *
except ImportError:
    from kmarius_cache_metadata.lib import exists, lookup, put, cacher, init_database
    from kmarius_cache_medadata.lib.plugin_types import *

logger = logging.getLogger("Unmanic.Plugin.kmarius_cache_metadata")

init_database([c.identifier for c in cacher.CACHERS])


class Settings(PluginSettings):
    settings = {
        'cache_' + c.identifier: True for c in cacher.CACHERS
    }
    form_settings = {
        'cache_' + c.identifier: {
            'label': f'Enable {c.identifier} caching',
        } for c in cacher.CACHERS
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


def update_cached_data(cachers, path):
    file_stat = os.stat(path)
    disk_timestamp = int(file_stat.st_mtime)

    for c in cachers:
        identifier = c.identifier

        if exists(identifier, path, disk_timestamp):
            continue

        res = c.run_prog(path)

        if res is not None:
            put(identifier, path, disk_timestamp, res)
            logger.info(f"Updating {identifier} data - {path}")


def on_library_management_file_test(data: FileTestData) -> Optional[FileTestData]:
    settings = Settings(library_id=data.get('library_id'))

    path = data.get("path")

    file_stat = os.stat(path)
    disk_timestamp = int(file_stat.st_mtime)

    enabled_cachers = []

    for c in cacher.CACHERS:
        if settings.get_setting(c.setting_name()):
            enabled_cachers.append(c)

    for c in enabled_cachers:
        identifier = c.identifier

        res = lookup(identifier, path, disk_timestamp)

        if res is None:
            logger.info(f"No cached {identifier} data found, refreshing - {path}")
            res = c.run_prog(path)
        else:
            logger.info(f"Cached {identifier} data found - {path}")

        if res is not None:
            if not "shared_info" in data:
                data["shared_info"] = {}
            logger.info(f"Set shared {identifier} data - {path}")
            data["shared_info"][identifier] = res
            put(identifier, path, disk_timestamp, res)

    return data


def on_postprocessor_task_results(data: TaskResultData) -> Optional[TaskResultData]:
    if data["task_processing_success"] and data["file_move_processes_success"]:
        settings = Settings(library_id=data["library_id"])

        cachers = []
        for c in cacher.CACHERS:
            if settings.get_setting(c.setting_name()):
                cachers.append(c)

        for path in data["destination_files"]:
            try:
                update_cached_data(cachers, path)
            except Exception as e:
                logger.error(e)
    return data