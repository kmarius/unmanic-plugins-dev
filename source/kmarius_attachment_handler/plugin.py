#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

from kmarius.lib import lazy_init

logger = logging.getLogger("Unmanic.Plugin.kmarius_attachment_handler")


def on_library_management_file_test(data):
    kmarius = lazy_init(data, logger)

    attachment_streams = kmarius["streams"]["attachment"]
    attachment_mappings = {}

    # remove all streams
    for idx, stream_info in enumerate(attachment_streams):
        attachment_mappings[idx] = {
            'stream_mapping':  [],
            'stream_encoding': [],
        }

    kmarius["mappings"]["attachment"] = attachment_mappings

    if len(attachment_mappings) > 0:
        kmarius["add_file_to_pending_tasks"] = True

    return None
