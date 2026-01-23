#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

from unmanic.libs.filetest import FileTest
from unmanic.libs.unplugins.settings import PluginSettings

logger = logging.getLogger("Unmanic.Plugin.kmarius_hacks")


class Settings(PluginSettings):
    settings = {
        "test_failed_tasks": False,
    }

    form_settings = {
        "test_failed_tasks": {
            "label": "Run file testers on tasks even if they are marked as failed in the history.",
            "description": "This only affects newly spawned file tester threads. Disabling this setting requires a restart."
        }
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


settings = Settings()

if settings.get_setting("test_failed_tasks"):
    def file_failed_in_history(self, path):
        return False

    logger.info("Patching FileTest.file_failed_in_history")
    FileTest.file_failed_in_history = file_failed_in_history


def render_plugin_api(data):
    # we call this plugin's endpoint after startup to force loading of all plugins
    data["content"] = {}
    data["content_type"] = "application/json"