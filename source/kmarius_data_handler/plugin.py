#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

from kmarius.lib import lazy_init

logger = logging.getLogger("Unmanic.Plugin.kmarius_data_handler")


def on_library_management_file_test(data):
    kmarius = lazy_init(data, logger)

    data_streams = kmarius["streams"]["data"]
    data_mappings = {}

    # remove all streams
    for idx, stream_info in enumerate(data_streams):
        data_mappings[idx] = {
            'stream_mapping':  [],
            'stream_encoding': [],
        }

    kmarius["mappings"]["data"] = data_mappings
    if len(data_mappings) > 0:
        kmarius["add_file_to_pending_tasks"] = True

    return None
