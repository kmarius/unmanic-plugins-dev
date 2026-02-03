#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os.path

from unmanic.libs.filetest import FileTest
from unmanic.libs.unplugins.settings import PluginSettings

logger = logging.getLogger("Unmanic.Plugin.kmarius_hacks")


class Settings(PluginSettings):
    settings = {
        "test_failed_tasks": False,
        "check_existing_before_test": False,
    }

    form_settings = {
        "test_failed_tasks": {
            "label": "Run file testers on tasks even if they are marked as failed in the history.",
            "description": "This only affects newly spawned file tester threads."
        },
        "check_existing_before_test": {
            "label": "Ensure that files exist before running the test flow.",
            "description": "This only affects newly spawned file tester threads."
        },
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


settings = Settings()
applied = 0
removed = 0

if settings.get_setting("test_failed_tasks"):
    def file_failed_in_history(self, path):
        return False


    if not hasattr(FileTest, "old_file_failed_in_history"):
        logger.info("Patching FileTest.file_failed_in_history")
        FileTest.old_file_failed_in_history = FileTest.file_failed_in_history
        FileTest.file_failed_in_history = file_failed_in_history
        applied += 1
else:
    if hasattr(FileTest, "old_file_failed_in_history"):
        logger.info("Unpatching FileTest.file_failed_in_history")
        FileTest.file_failed_in_history = FileTest.old_file_failed_in_history
        del FileTest.old_file_failed_in_history
        removed += 1

if settings.get_setting("check_existing_before_test"):
    def new_should_file_be_added_to_task_list(self, path):
        if not os.path.exists(path):
            return False, [], 0
        return self.old_should_file_be_added_to_task_list(path)


    if not hasattr(FileTest, "old_should_file_be_added_to_task_list"):
        logger.info("Patching FileTest.should_file_be_added_to_task_list")
        FileTest.old_should_file_be_added_to_task_list = FileTest.should_file_be_added_to_task_list
        FileTest.should_file_be_added_to_task_list = new_should_file_be_added_to_task_list
        applied += 1
else:
    if hasattr(FileTest, "old_should_file_be_added_to_task_list"):
        logger.info("Unpatching FileTest.should_file_be_added_to_task_list")
        FileTest.should_file_be_added_to_task_list = FileTest.old_should_file_be_added_to_task_list
        del FileTest.old_should_file_be_added_to_task_list
        removed += 1

logger.info(f"{applied} {"patch" if applied == 1 else "patches"} applied, {removed} {"patch" if removed == 1 else "patches"} removed")


def render_plugin_api(data: dict):
    # we call this plugin's endpoint after startup to force loading of all plugins
    data["content"] = {}
    data["content_type"] = "application/json"