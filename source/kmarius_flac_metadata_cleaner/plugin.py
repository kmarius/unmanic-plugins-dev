#!/usr/bin/env python3

import logging
from mutagen.flac import FLAC
from unmanic.libs.unplugins.settings import PluginSettings

logger = logging.getLogger("Unmanic.Plugin.kmarius_flac_metadata_cleaner")


class Settings(PluginSettings):
    settings = {
        # Vorbis comment keys are case-insensitive; mutagen stores them uppercase
        "tags_to_remove": "COMMENT,DESCRIPTION,SUPPLIER,ENCODED BY",
    }
    form_settings = {
        "tags_to_remove": {
            "label": "Tags to remove",
            "description": "Comma separated list of tags to remove, must be uppercase",
        },
    }


def on_library_management_file_test(data):
    settings = Settings(library_id=data.get('library_id'))
    tags_to_remove = settings.get_setting('tags_to_remove').split(",")
    tags_to_remove = [tag.strip() for tag in tags_to_remove]

    path = data.get("path")

    metadata = FLAC(path)
    for tag in tags_to_remove:
        if tag in metadata:
            data['add_file_to_pending_tasks'] = True
            data["issues"].append({
                "id": "kmarius_flac_metadata_cleaner",
                "message": f"metadata found: {path}"
            })
            break

    return data


def on_worker_process(data):
    settings = Settings(library_id=data.get('library_id'))
    tags_to_remove = settings.get_setting('tags_to_remove').split(",")
    tags_to_remove = [tag.strip() for tag in tags_to_remove]

    path = data.get("file_in")

    metadata = FLAC(path)
    for tag in tags_to_remove:
        if tag in metadata:
            del metadata[tag]
    metadata.save()

    return data
