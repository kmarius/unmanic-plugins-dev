#!/usr/bin/env python3

import logging
import os
from typing import override

from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from unmanic.libs.unplugins.settings import PluginSettings

PLUGIN_ID = "kmarius_audio_metadata_cleaner"

logger = logging.getLogger(f"Unmanic.Plugin.{PLUGIN_ID}")


class Settings(PluginSettings):
    settings = {
        "flac_tags": "COMMENT,DESCRIPTION",
        "mp3_tags": "COMM",
        "mp4_tags": "©cmt",
    }
    form_settings = {
        "flac_tags": {
            "label": "Tags to remove for FLAC files",
            "description": "Comma separated list of tags to remove, must be uppercase",
        },
        "mp3_tags": {
            "label": "Tag prefixes",
            "description": "Comma separated list of tags to remove, all tags starting with one of these prefixes is removed.",
        },
        "mp4_tags": {
            "label": "Tags to remove",
            "description": "Comma separated list of tags to remove",
        },
    }
    _cache = {}

    @override
    def get_setting(self, key=None):
        if not key:
            return super().get_setting()
        if key not in self._cache:
            setting = super().get_setting(key)
            tokens = setting.split(",")
            tokens = [token.strip() for token in tokens]
            tokens = [token for token in tokens if token != ""]
            self._cache[key] = tokens
        return self._cache[key]


_library_settings = {}


def get_settings_object(library_id: int) -> Settings:
    if library_id not in _library_settings:
        _library_settings[library_id] = Settings(library_id=library_id)
    return _library_settings[library_id]


def on_library_management_file_test(data):
    settings = get_settings_object(data.get('library_id'))

    path = data.get("path")
    ext = os.path.splitext(path)[1].lower()

    if ext == ".flac":
        flac_tags = settings.get_setting('flac_tags')

        metadata = FLAC(path)
        for tag in flac_tags:
            if tag in metadata:
                data['add_file_to_pending_tasks'] = True
                data["issues"].append({
                    "id": PLUGIN_ID,
                    "message": f"metadata found: {path}"
                })
                break

    elif ext == ".mp3":
        mp3_tags = settings.get_setting('mp3_tags')

        metadata = MP3(path)
        for tag in metadata.keys():
            for prefix in mp3_tags:
                if tag.startswith(prefix):
                    data['add_file_to_pending_tasks'] = True
                    data["issues"].append({
                        "id": PLUGIN_ID,
                        "message": f"metadata found: {path}"
                    })
                    break

    elif ext == ".m4a":
        mp4_tags = settings.get_setting('mp4_tags')

        metadata = MP4(path)
        for tag in mp4_tags:
            if tag in metadata:
                data['add_file_to_pending_tasks'] = True
                data["issues"].append({
                    "id": PLUGIN_ID,
                    "message": f"metadata found: {path}"
                })
                break

    return data


def on_worker_process(data):
    settings = get_settings_object(data.get('library_id'))

    path = data.get("file_in")
    ext = os.path.splitext(path)[1].lower()

    if ext == ".flac":
        flac_tags = settings.get_setting('flac_tags')

        metadata = FLAC(path)
        modified = False
        for tag in flac_tags:
            if tag in metadata:
                del metadata[tag]
                modified = True
        if modified:
            metadata.save()

    elif ext == ".mp3":
        mp3_tags = settings.get_setting('mp3_tags')

        metadata = MP3(path)
        modified = True
        for tag in list(metadata.keys()):
            for prefix in mp3_tags:
                if tag.startswith(prefix):
                    del metadata[tag]
                    modified = True
                    break
        if modified:
            metadata.save()

    elif ext == ".m4a":
        mp4_tags = settings.get_setting('mp4_tags')

        metadata = MP4(path)
        modified = False
        for tag in mp4_tags:
            if tag in metadata:
                del metadata[tag]
                modified = True
        if modified:
            metadata.save()

    return data