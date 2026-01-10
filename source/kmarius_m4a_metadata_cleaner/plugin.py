#!/usr/bin/env python3

import logging
import os

from mutagen.mp4 import MP4
from unmanic.libs.unplugins.settings import PluginSettings

logger = logging.getLogger("Unmanic.Plugin.kmarius_m4a_metadata_cleaner")


class Settings(PluginSettings):
    settings = {
        "tags_to_remove": "©cmt",
    }
    form_settings = {
        "tags_to_remove": {
            "label": "Tags to remove",
            "description": "Comma separated list of tags to remove",
        },
    }


def on_library_management_file_test(data):
    settings = Settings(library_id=data.get('library_id'))
    tags_to_remove = settings.get_setting('tags_to_remove').split(",")
    tags_to_remove = [tag.strip() for tag in tags_to_remove]

    path = data.get("path")
    _, ext = os.path.splitext(path)
    if ext.lower() != ".m4a":
        return data

    metadata = MP4(path)
    for tag in tags_to_remove:
        if tag in metadata:
            data['add_file_to_pending_tasks'] = True
            data["issues"].append({
                "id": "kmarius_m4a_metadata_cleaner",
                "message": f"metadata found: {path}"
            })
            break

    return data


def on_worker_process(data):
    settings = Settings(library_id=data.get('library_id'))
    tags_to_remove = settings.get_setting('tags_to_remove').split(",")
    tags_to_remove = [tag.strip() for tag in tags_to_remove]

    path = data.get("file_in")
    _, ext = os.path.splitext(path)
    if ext.lower() != ".m4a":
        return data

    metadata = MP4(path)
    modified = False
    for tag in tags_to_remove:
        if tag in metadata:
            del metadata[tag]
            modified = True
    if modified:
        metadata.save()

    return data