#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os

from unmanic.libs.unplugins.settings import PluginSettings
from typing import Optional

try:
    from kmarius_cache_metadata.lib import cache
    from kmarius_cache_metadata.lib.metadata_provider import PROVIDERS
    from kmarius_cache_metadata.plugin_types import *
except ImportError:
    from lib import cache
    from lib.metadata_provider import PROVIDERS
    from plugin_types import *

logger = logging.getLogger("Unmanic.Plugin.kmarius_cache_metadata")

cache.init([p.name for p in PROVIDERS])


class Settings(PluginSettings):
    settings = {
        p.setting_name(): True for p in PROVIDERS
    }
    form_settings = {
        p.setting_name(): {
            'label': f'Enable {p.name} caching',
        } for p in PROVIDERS
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


def update_cached_data(providers, path):
    mtime = int(os.path.getmtime(path))

    for p in providers:
        if cache.exists(p.name, path, mtime):
            continue

        res = p.run_prog(path)

        if res:
            cache.put(p.name, path, mtime, res)
            logger.info(f"Updating {p.name} data - {path}")


def on_library_management_file_test(data: FileTestData) -> Optional[FileTestData]:
    settings = Settings(library_id=data.get('library_id'))

    if not "shared_info" in data:
        data["shared_info"] = {}

    path = data["path"]
    mtime = int(os.path.getmtime(path))

    for p in PROVIDERS:
        if not settings.get_setting(p.setting_name()):
            continue

        res = cache.lookup(p.name, path, mtime)

        if res is None:
            logger.info(f"No cached {p.name} data found, refreshing - {path}")
            res = p.run_prog(path)
        else:
            logger.info(f"Cached {p.name} data found - {path}")

        if res:
            logger.info(f"Set shared {p.name} data - {path}")
            data["shared_info"][p.name] = res
            cache.put(p.name, path, mtime, res)

    return data


def on_postprocessor_task_results(data: TaskResultData) -> Optional[TaskResultData]:
    if data["task_processing_success"] and data["file_move_processes_success"]:
        settings = Settings(library_id=data["library_id"])

        providers = []
        for p in PROVIDERS:
            if settings.get_setting(p.setting_name()):
                providers.append(p)

        for path in data["destination_files"]:
            try:
                update_cached_data(providers, path)
            except Exception as e:
                logger.error(e)
    return data