#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re

from unmanic.libs.unplugins.settings import PluginSettings

from typing import Optional, override

from .lib.metadata_provider import MetadataProvider

try:
    from kmarius_library import logger
    from kmarius_library.lib import cache, timestamps
    from kmarius_library.lib.metadata_provider import PROVIDERS
    from kmarius_library.plugin_types import *
except ImportError:
    from . import logger
    from lib import cache, timestamps
    from lib.metadata_provider import PROVIDERS
    from plugin_types import *

cache.init([p.name for p in PROVIDERS])
timestamps.init()


class Settings(PluginSettings):
    @staticmethod
    def __build_settings():
        settings = {
            "ignored_path_patterns":    "",
            "allowed_extensions":       '',
            "incremental_scan_enabled": True,
            "caching_enabled":          True,
        }
        form_settings = {
            "ignored_path_patterns":    {
                "input_type": "textarea",
                "label":      "Regular expression patterns of pathes to ignore - one per line"
            },
            "allowed_extensions":       {
                "label":       "Search library only for extensions",
                "description": "A comma separated list of allowed file extensions."
            },
            "incremental_scan_enabled": {
                "label": "Enable incremental scans (ignore unchanged files)",
            },
            "caching_enabled":          {
                "label": "Enable metadata caching"
            },
        }

        settings.update({
            p.setting_name(): p.default_enabled for p in PROVIDERS
        })

        form_settings.update({
            p.setting_name(): {
                'label':       f'Enable {p.name} caching',
                "sub_setting": True,
                'display':     'hidden',
            } for p in PROVIDERS
        })

        return settings, form_settings

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)
        self.settings, self.form_settings = self.__build_settings()

    @override
    def get_form_settings(self):
        form_settings = super(Settings, self).get_form_settings()
        if not self.settings_configured:
            # FIXME: in staging, settings_configured is not populated at this point and the corresponding method is private
            self._PluginSettings__import_configured_settings()
        if self.settings_configured:
            caching_enabled = self.settings_configured.get("caching_enabled")
            if caching_enabled:
                for setting, val in form_settings.items():
                    if setting.startswith("cache_"):
                        del val["display"]
        return form_settings


def update_cached_metadata(providers: list[MetadataProvider], path: str):
    try:
        mtime = int(os.path.getmtime(path))

        for p in providers:
            if cache.exists(p.name, path, mtime):
                continue

            res = p.run_prog(path)

            if res:
                cache.put(p.name, path, mtime, res)
                logger.info(f"Updating {p.name} data - {path}")
    except Exception as e:
        logger.error(e)


def update_timestamp(library_id: int, path: str):
    try:
        mtime = int(os.path.getmtime(path))
        logger.info(f"Updating timestamp path={path} library_id={library_id} to {mtime}")
        timestamps.put(library_id, path, mtime)
    except Exception as e:
        logger.error(e)


def is_extension_allowed(path: str, settings: Settings) -> bool:
    allowed_extensions = settings.get_setting('allowed_extensions').split(',')
    ext = os.path.splitext(path)[-1][1:].lower()
    if ext and ext in allowed_extensions:
        return True
    return False


def is_path_ignored(path: str, settings: Settings) -> bool:
    regex_patterns = settings.get_setting('ignored_path_patterns')
    for regex_pattern in regex_patterns.splitlines():
        if not regex_pattern:
            continue
        pattern = re.compile(regex_pattern.strip())
        if pattern.search(path):
            return True
    return False


def is_file_unchanged(library_id: int, path: str) -> bool:
    mtime = int(os.path.getmtime(path))
    stored_timestamp = timestamps.get(library_id, path)
    if stored_timestamp == mtime:
        return True
    return False


def init_shared_data(data):
    if not "shared_info" in data:
        data["shared_info"] = {}
    shared_info = data["shared_info"]
    if not "kmarius_library" in shared_info:
        shared_info["kmarius_library"] = {
            "incremental_scan": {}
        }


def on_library_management_file_test(data: FileTestData) -> Optional[FileTestData]:
    settings = Settings(library_id=data.get('library_id'))
    path = data["path"]
    library_id = data["library_id"]

    if not is_extension_allowed(path, settings):
        data['add_file_to_pending_tasks'] = False
        return data

    if is_path_ignored(path, settings):
        data['add_file_to_pending_tasks'] = False
        return data

    init_shared_data(data)

    if settings.get_setting("incremental_scan_enabled"):
        if is_file_unchanged(library_id, path):
            data['add_file_to_pending_tasks'] = False
            data["issues"].append({
                'id':      "kmarius_library",
                'message': f"file unchanged: {path}, library_id={library_id}"
            })
            return data
        data["shared_info"]["kmarius_library"]["incremental_scan"][library_id] = True

    if settings.get_setting("caching_enabled"):
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
        incremental_scan_enabled = settings.get_setting("incremental_scan_enabled")
        caching_enabled = settings.get_setting("caching_enabled")

        library_id = data["library_id"]

        metadata_providers = []

        if caching_enabled:
            for p in PROVIDERS:
                if settings.get_setting(p.setting_name()):
                    metadata_providers.append(p)

        for path in data["destination_files"]:
            if is_extension_allowed(path, settings):
                if caching_enabled:
                    update_cached_metadata(metadata_providers, path)
                if incremental_scan_enabled:
                    # TODO: it could be desirable to not add this file to the db and have it checked again
                    update_timestamp(library_id, path)
    return data