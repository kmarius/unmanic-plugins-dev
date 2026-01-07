#!/usr/bin/env python3

import logging
from mutagen.mp3 import MP3
from unmanic.libs.unplugins.settings import PluginSettings

logger = logging.getLogger("Unmanic.Plugin.kmarius_mp3_metadata_cleaner")


class Settings(PluginSettings):
    settings = {
        "tag_prefixes": "COMM",
    }
    form_settings = {
        "tag_prefixes": {
            "label": "Tag prefixes",
            "description": "Comma separated list of tags to remove, all tags starting with one of the prefixes is removed.",
        },
    }


def on_library_management_file_test(data):
    settings = Settings(library_id=data.get('library_id'))
    tag_prefixes = settings.get_setting('tag_prefixes').split(",")
    tag_prefixes = [tag.strip() for tag in tag_prefixes]

    path = data.get("path")

    metadata = MP3(path)
    for tag in metadata.keys():
        for prefix in tag_prefixes:
            if tag.startswith(prefix):
                data['add_file_to_pending_tasks'] = True
                data["issues"].append({
                    "id": "kmarius_mp3_metadata_cleaner",
                    "message": f"metadata found: {path}"
                })
                break

    return data


def on_worker_process(data):
    settings = Settings(library_id=data.get('library_id'))
    tag_prefixes = settings.get_setting('tag_prefixes').split(",")
    tag_prefixes = [tag.strip() for tag in tag_prefixes]

    path = data.get("file_in")

    metadata = MP3(path)
    keys = list(metadata.keys())
    for tag in keys:
        for prefix in tag_prefixes:
            tag.startswith(prefix)
            del metadata[tag]
            break
    metadata.save()

    return data
