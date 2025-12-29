#!/usr/bin/env python3

import logging

from mutagen.flac import FLAC

logger = logging.getLogger("Unmanic.Plugin.kmarius_flac_metadata_cleaner")

# Vorbis comment keys are case-insensitive; mutagen stores them uppercase
# TODO: make configurable
tags_to_remove = ["COMMENT", "DESCRIPTION"]


def on_library_management_file_test(data):
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
    path = data.get("file_in")

    metadata = FLAC(path)
    for tag in tags_to_remove:
        if tag in metadata:
            del metadata[tag]
    metadata.save()

    return data
