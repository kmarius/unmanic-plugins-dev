#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from unmanic.libs.unplugins.settings import PluginSettings


class Settings(PluginSettings):
    settings = {}

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)