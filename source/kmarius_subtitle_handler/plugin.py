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
import os

from kmarius_executor.lib import lazy_init
from kmarius_executor.lib.ffmpeg import StreamMapper, Parser, Probe
from unmanic.libs.unplugins.settings import PluginSettings

# Configure plugin logger
logger = logging.getLogger("Unmanic.Plugin.kmarius_subtitle_handler")


class Settings(PluginSettings):
    settings = {
        "languages_to_extract": "eng",
    }

    form_settings = {
        "languages_to_extract": {
            "label": "Subtitle languages to extract (leave empty for all)",
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
                'stream_mapping': [],
                'stream_encoding': [],
            }

        # Find a tag for this subtitle
        subtitle_tag = ''

        if language_tag:
            subtitle_tag = "{}.{}".format(subtitle_tag, language_tag)

        # If there were no tags, just number the file
        if not subtitle_tag:
            subtitle_tag = "{}.{}".format(
                subtitle_tag, stream_info.get('index'))

        # Ensure subtitle tag does not contain whitespace or slashes
        subtitle_tag = re.sub(r'\s|/|\\', '-', subtitle_tag)

        self.sub_streams.append(
            {
                'stream_id': stream_id,
                'subtitle_tag': subtitle_tag,
                'stream_mapping': ['-map', '0:s:{}'.format(stream_id)],
            }
        )

        # Copy the streams to the destination. This will actually do nothing...
        return {
            'stream_mapping': ['-map', '0:s:{}'.format(stream_id)],
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


def on_library_management_file_test(data: dict):
    mydata = lazy_init(data, logger)

    subtitle_streams = mydata["streams"]["subtitle"]
    subtitle_mappings = {}

    # remove all streams
    for idx, stream_info in enumerate(subtitle_streams):
        subtitle_mappings[idx] = {
            'stream_mapping': [],
            'stream_encoding': [],
        }

    mydata["mappings"]["subtitle"] = subtitle_mappings
    if len(subtitle_mappings) > 0:
        mydata["add_file_to_pending_tasks"] = True


def on_worker_process(data: dict):
    settings = Settings(library_id=data.get('library_id'))

    # Default to no FFMPEG command required. This prevents the FFMPEG command from running if it is not required
    data['exec_command'] = []
    data['repeat'] = False

    # Get the path to the file
    path = data.get('file_in')

    probe = Probe(logger, allowed_mimetypes=['video'])
    if not probe.file(path):
        return

    mapper = PluginStreamMapper()
    mapper.set_settings(settings)
    mapper.set_probe(probe)

    original_stem, _ = os.path.splitext(data.get('original_file_path'))
    original_file_directory = os.path.dirname(data.get('original_file_path'))

    if mapper.streams_need_processing():
        mapper.set_input_file(path)

        # Get generated ffmpeg args
        ffmpeg_args = mapper.get_ffmpeg_args()

        # Append STR extract args
        for sub_stream in mapper.sub_streams:
            stream_mapping = sub_stream.get('stream_mapping', [])
            subtitle_tag = sub_stream.get('subtitle_tag')
            subtitle_path = os.path.join(original_file_directory, f"{original_stem}.{subtitle_tag}.srt")

            ffmpeg_args += stream_mapping
            ffmpeg_args += ["-y", subtitle_path]

        # Apply ffmpeg args to command
        data['exec_command'] = ['ffmpeg']
        data['exec_command'] += ffmpeg_args

        # Set the parser
        parser = Parser(logger)
        parser.set_probe(probe)
        data['command_progress_parser'] = parser.parse_progress