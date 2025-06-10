#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    Written by:               Josh.5 <jsunnex@gmail.com>
    Date:                     18 April 2021, (1:41 AM)

    Copyright:
        Copyright (C) 2021 Josh Sunnex

        This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
        Public License as published by the Free Software Foundation, version 3.

        This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the
        implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
        for more details.

        You should have received a copy of the GNU General Public License along with this program.
        If not, see <https://www.gnu.org/licenses/>.

"""
import logging
import re

from kmarius.lib import lazy_init
from kmarius.lib.ffmpeg import StreamMapper, Parser
from unmanic.libs.unplugins.settings import PluginSettings
import os
from kmarius.lib.ffmpeg import Probe

# Configure plugin logger
logger = logging.getLogger("Unmanic.Plugin.kmarius_subtitle_handler")


class Settings(PluginSettings):
    settings = {
        "languages_to_extract":              "",
        "include_title_in_output_file_name": True
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)

        self.form_settings = {
            "languages_to_extract":              {
                "label": "Subtitle languages to extract (leave empty for all)",
            },
            "include_title_in_output_file_name": {
                "label": "Include title in output file name",
            },
        }


class PluginStreamMapper(StreamMapper):
    def __init__(self):
        super(PluginStreamMapper, self).__init__(logger, ['subtitle'])
        self.sub_streams = []
        self.settings = None
        self.languages = []

    def set_settings(self, settings):
        self.settings = settings

        # update languages list
        language_list = self.settings.get_setting('languages_to_extract')
        language_list = re.sub(r'\s', '-', language_list)
        languages = list(filter(None, language_list.lower().split(',')))
        self.languages = [language.strip() for language in languages]

    def test_stream_needs_processing(self, stream_info: dict):
        """Any text based will need to be processed"""

        if stream_info.get('codec_name', '').lower() not in ['srt', 'subrip', 'mov_text']:
            return False

        # If no languages specified, extract all
        if len(self.languages) == 0:
            return True

        language_tag = stream_info.get('tags').get('language', '').lower()

        return language_tag in self.languages

    def custom_stream_mapping(self, stream_info: dict, stream_id: int):
        stream_tags = stream_info.get('tags', {})

        # e.g. 'eng', 'fra'
        language_tag = stream_tags.get('language', '').lower()
        # e.g. 'English', 'French'
        title_tag = stream_tags.get('title', '')

        # Skip stream
        if len(self.languages) > 0 and language_tag not in self.languages:
            return {
                'stream_mapping':  [],
                'stream_encoding': [],
            }

        # Find a tag for this subtitle
        subtitle_tag = ''

        if language_tag:
            subtitle_tag = "{}.{}".format(subtitle_tag, language_tag)

        if title_tag and self.settings.get_setting('include_title_in_output_file_name'):
            subtitle_tag = "{}.{}".format(subtitle_tag, title_tag)

        # If there were no tags, just number the file
        if not subtitle_tag:
            subtitle_tag = "{}.{}".format(
                subtitle_tag, stream_info.get('index'))

        # Ensure subtitle tag does not contain whitespace or slashes
        subtitle_tag = re.sub(r'\s|/|\\', '-', subtitle_tag)

        self.sub_streams.append(
            {
                'stream_id':      stream_id,
                'subtitle_tag':   subtitle_tag,
                'stream_mapping': ['-map', '0:s:{}'.format(stream_id)],
            }
        )

        # Copy the streams to the destination. This will actually do nothing...
        return {
            'stream_mapping':  ['-map', '0:s:{}'.format(stream_id)],
            'stream_encoding': ['-c:s:{}'.format(stream_id), 'copy'],
        }

    def get_ffmpeg_args(self):
        """
        Overwrite default function. We only need the first lot of args.

        :return:
        """
        args = []

        # Add generic options first
        args += self.generic_options

        # Add the input file
        # This class requires at least one input file specified with the input_file attribute
        if not self.input_file:
            raise Exception("Input file has not been set")
        args += ['-i', self.input_file]

        # Add other main options
        args += self.main_options

        # Add advanced options. This includes the stream mapping and the encoding args
        args += self.advanced_options

        return args


def on_library_management_file_test(data):
    kmarius = lazy_init(data, logger)

    subtitle_streams = kmarius["streams"]["subtitle"]
    subtitle_mappings = {}

    # remove all streams
    for idx, stream_info in enumerate(subtitle_streams):
        subtitle_mappings[idx] = {
            'stream_mapping':  [],
            'stream_encoding': [],
        }

    kmarius["mappings"]["subtitle"] = subtitle_mappings
    if len(subtitle_mappings) > 0:
        kmarius["add_file_to_pending_tasks"] = True

    return None


def on_worker_process(data):
    # Default to no FFMPEG command required. This prevents the FFMPEG command from running if it is not required
    data['exec_command'] = []
    data['repeat'] = False

    # Get the path to the file
    abspath = data.get('file_in')

    probe = Probe(logger, allowed_mimetypes=['video'])
    if not probe.file(abspath):
        return

    if data.get('library_id'):
        settings = Settings(library_id=data.get('library_id'))
    else:
        settings = Settings()

    if True:
        mapper = PluginStreamMapper()
        mapper.set_settings(settings)
        mapper.set_probe(probe)

        split_original_file_path = os.path.splitext(
            data.get('original_file_path'))
        original_file_directory = os.path.dirname(
            data.get('original_file_path'))

        if mapper.streams_need_processing():
            # Set the input file
            mapper.set_input_file(abspath)

            # Get generated ffmpeg args
            ffmpeg_args = mapper.get_ffmpeg_args()

            # Append STR extract args
            for sub_stream in mapper.sub_streams:
                stream_mapping = sub_stream.get('stream_mapping', [])
                subtitle_tag = sub_stream.get('subtitle_tag')

                ffmpeg_args += stream_mapping
                ffmpeg_args += [
                    "-y",
                    os.path.join(original_file_directory, "{}{}.srt".format(
                        split_original_file_path[0], subtitle_tag)),
                ]

            # Apply ffmpeg args to command
            data['exec_command'] = ['ffmpeg']
            data['exec_command'] += ffmpeg_args

            # Set the parser
            parser = Parser(logger)
            parser.set_probe(probe)
            data['command_progress_parser'] = parser.parse_progress
    return data
