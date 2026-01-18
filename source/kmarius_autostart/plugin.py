#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

from unmanic.libs.plugins import PluginsHandler
from unmanic.libs.unplugins import PluginExecutor
from unmanic.libs.unplugins.settings import PluginSettings

PLUGIN_ID = "kmarius_autostart"

logger = logging.getLogger(f"Unmanic.Plugin.{PLUGIN_ID}")


# class Settings(PluginSettings):
#     @staticmethod
#     def __build_settings():
#         settings = {}
#         form_settings = {}
#         order = [
#             {
#                 "column": 'name',
#                 "dir":    'asc',
#             },
#         ]
#         for plugin in PluginsHandler().get_plugin_list_filtered_and_sorted(order=order):
#             plugin_id = plugin["plugin_id"]
#             if plugin_id == PLUGIN_ID:
#                 continue
#             setting_name = f"autostart_{plugin_id}"
#             settings.update({
#                 setting_name: False,
#             })
#             form_settings.update({
#                 setting_name: {
#                     "label": f"Autostart '{plugin["name"]}'"
#                 },
#             })
#         return settings, form_settings
#
#     def __init__(self, *args, **kwargs):
#         super(Settings, self).__init__(*args, **kwargs)
#         self.settings, self.form_settings = self.__build_settings()


# plugins_loaded = False
# def _load_plugins():
#     global plugins_loaded
#     if plugins_loaded:
#         return
#     plugins_loaded = True
#
#     settings = Settings()
#     executor = PluginExecutor()
#
#     for setting in settings.get_setting():
#         plugin_id = setting[10:]
#         if settings.get_setting(setting):
#             try:
#                 logger.info(f"Attempting to load {plugin_id}")
#                 executor.get_all_plugin_types_in_plugin(plugin_id)
#             except Exception as _:
#                 pass


def render_plugin_api(data):
    # we don't actually need to load plugins, processing the request will
    # cause all plugins to be loaded, we do this so curl gets a 200 response
    # and the script knows when to stop
    #_load_plugins()
    data["content"] = {}
    data["content_type"] = "application/json"