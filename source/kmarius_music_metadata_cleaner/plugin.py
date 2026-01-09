#!/usr/bin/env python3

import logging
import os
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from unmanic.libs.unplugins.settings import PluginSettings

logger = logging.getLogger("Unmanic.Plugin.kmarius_music_metadata_cleaner")


class Settings(PluginSettings):
    settings = {
        "flac_tags": "COMMENT",
        "mp3_tag_prefixes": "COMM",
        "m4a_tags": "©cmt",
    }
    form_settings = {
        "flac_tags": {
            "label": "Tags to remove from FLAC files",
            "description": "Comma separated list of VorbisComment tags, must be uppercase",
        },
        "mp3_tag_prefixes": {
            "label": "Tag prefixes to remove from MP3 files",
            "description": "Comma separated list of MP3 tag prefixes",
        },
        "m4a_tags": {
            "label": "Tags to remove from M4A files",
            "description": "Comma separated list of M4A tags, must be uppercase",
        },
    }


def on_library_management_file_test(data):
    settings = Settings(library_id=data.get('library_id'))

    path = data.get("path")
    _, ext = os.path.splitext(path)
    ext = ext.lower()

    if ext == ".flac":
        tags_to_remove = settings.get_setting('flac_tags').split(",")
        tags_to_remove = [tag.strip() for tag in tags_to_remove]
        track = FLAC(path)
        for tag in tags_to_remove:
            if tag in track:
                data['add_file_to_pending_tasks'] = True
                data["issues"].append({
                    "id": "kmarius_music_metadata_cleaner",
                    "message": f"metadata found: {path}"
                })
                break
    elif ext == ".mp3":
            tag_prefixes = settings.get_setting('mp3_tag_prefixes').split(",")
            tag_prefixes = [tag.strip() for tag in tag_prefixes]
            tag_prefixes = [tag for tag in tag_prefixes if tag != ""]

            track = MP3(path)
            for tag in track.keys():
                for prefix in tag_prefixes:
                    if tag.startswith(prefix):
                        data['add_file_to_pending_tasks'] = True
                        data["issues"].append({
                            "id": "kmarius_music_metadata_cleaner",
                            "message": f"metadata found: {path}"
                        })
                        break
    elif ext == "m4a":
        tags_to_remove = settings.get_setting('m4a_tags').split(",")
        tags_to_remove = [tag.strip() for tag in tags_to_remove]

        track = MP4(path)
        for tag in tags_to_remove:
            if tag in track:
                data['add_file_to_pending_tasks'] = True
                data["issues"].append({
                    "id": "kmarius_m4a_metadata_cleaner",
                    "message": f"metadata found: {path}"
                })
                break

    return data


def on_worker_process(data):
    settings = Settings(library_id=data.get('library_id'))

    path = data.get("file_in")
    _, ext = os.path.splitext(path)
    ext = ext.lower()

    if ext == ".flac":
        tags_to_remove = settings.get_setting('flac_tags').split(",")
        tags_to_remove = [tag.strip() for tag in tags_to_remove]

        track = FLAC(path)
        for tag in tags_to_remove:
            if tag in track:
                del track[tag]
        track.save()
    elif ext == ".mp3":
        tag_prefixes = settings.get_setting('mp3_tag_prefixes').split(",")
        tag_prefixes = [tag.strip() for tag in tag_prefixes]
        tag_prefixes = [tag for tag in tag_prefixes if tag != ""]

        track = MP3(path)
        for tag in list(track.keys()):
            for prefix in tag_prefixes:
                if tag.startswith(prefix):
                    del track[tag]
                    break
        track.save()
    elif ext == "m4a":
        tags_to_remove = settings.get_setting('m4a_tags').split(",")
        tags_to_remove = [tag.strip() for tag in tags_to_remove]

        track = MP4(path)
        for tag in tags_to_remove:
            if tag in track:
                del track[tag]
        track.save()

    return data