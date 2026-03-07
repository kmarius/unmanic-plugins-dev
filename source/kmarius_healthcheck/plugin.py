import json
import re
import os
import subprocess
import time
from datetime import datetime
import traceback
import uuid
from typing import Tuple

from unmanic.libs.unmodels import Libraries
from unmanic.libs.unplugins.settings import PluginSettings

from kmarius_healthcheck.lib.types import *
from kmarius_healthcheck.lib import logger
from kmarius_healthcheck.lib import issues as issues_db


class Settings(PluginSettings):
    settings = {
    }
    form_settings = {
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)


def _cropdetect(path: str, ss: int = None, t: int = None) -> Tuple[int, int]:
    command = ['ffmpeg']
    if ss is not None:
        command += ['-ss', str(ss)]
    if t is not None:
        command += ['-t', str(t)]
    command += ['-i', path, '-vf', 'cropdetect', '-f', 'null', '-']

    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = proc.communicate()

    crops = {}
    # rarely the output looks like crop=-XX:-YY:...
    for crop in re.compile(r'crop=-?(\d+):-?(\d+):\d+:\d+').findall(out.decode('utf-8')):
        if crop not in crops:
            crops[crop] = 0
        crops[crop] += 1

    width, height = map(int, max(crops.items(), key=lambda x: x[1])[0])
    return width, height


def _has_black_bars(path: str, probe: dict) -> bool:
    duration = int(float(probe['format']['duration']))

    width, height = None, None
    for stream in probe['streams']:
        if stream['codec_type'] == 'video':
            width = stream['width']
            height = stream['height']
            break

    # detected dimensions often slightly differ from the real ones, but I've never seen it higher than 16 pixels
    thresh = 16

    if duration > 60:
        crop_width, crop_height = _cropdetect(path, ss=30, t=30)
        if not (width - crop_width > thresh or height - crop_height > thresh):
            return False

    # check again 5 minutes in, if possible
    ss, t = 300, 30
    if duration < 330:
        ss = duration - 30
        t = None
        if ss < 0:
            ss = 0

    crop_width, crop_height = _cropdetect(path, ss=ss, t=t)
    return width - crop_width > thresh or height - crop_height > thresh


def _has_video(probe: dict) -> bool:
    for stream in probe['streams']:
        if stream['codec_type'] == 'video':
            return True
    return False


def _has_audio(probe: dict) -> bool:
    for stream in probe['streams']:
        if stream['codec_type'] == 'audio':
            return True
    return False


def _has_multichannel(probe: dict) -> bool:
    for stream in probe['streams']:
        if stream['codec_type'] == 'audio':
            if stream['channels'] > 2:
                return True
    return False


def _is_truncated(mediainfo: dict) -> bool:
    if 'extra' in mediainfo and 'IsTruncated' in mediainfo['extra']:
        return mediainfo['extra']['IsTruncated'] == 'Yes'
    return False


def on_library_management_file_test(data: FileTestData, **kwargs):
    library_id = data['library_id']
    path = data['path']
    probe = data['shared_info'].get('ffprobe')
    mediainfo = data['shared_info'].get('mediainfo')

    # What do we do when the file is changed

    file_issues = []

    if _is_truncated(mediainfo):
        file_issues.append('Truncated')

    if not _has_audio(probe):
        file_issues.append('No audio')

    if not _has_multichannel(probe):
        file_issues.append('Stereo only')

    if not _has_video(probe):
        file_issues.append('No video')

    if _has_black_bars(path, probe):
        file_issues.append('Black bars')

    if not file_issues:
        issues_db.delete(library_id, path, reuse_connection=True)
    else:
        logger.info(f'Issues for {path}: {', '.join(file_issues)}')
        mtime = int(os.path.getmtime(path))
        issues_db.insert(library_id, path, mtime, ','.join(file_issues))


def emit_postprocessor_complete(data: PostprocessorCompleteData, **kwargs):
    # update the timestamp in the database after file processing
    # also handles renames, e.g. if processing changed the container form mkv to mp4
    if data['task_success']:
        library_id = data['library_id']
        path = data['destination_data']['abspath']
        src_path = data['source_data']['abspath']

        mtime = int(os.path.getmtime(path))
        if path == src_path:
            issues_db.update_mtime(mtime, library_id, src_path)
        else:
            issues_db.rename(library_id, src_path, path, mtime)


def emit_scan_complete(data: ScanCompleteData, **kwargs):
    # check against the library database and remove all issues of files not in the library
    from kmarius_library.lib import timestamps
    library_id = data['library_id']
    # we could attach the timestamps database a perform a join
    paths = issues_db.query(library_id=library_id, columns=['path'])
    for path, in paths:
        if timestamps.get(library_id, path) is None:
            issues_db.delete(library_id, path)


def render_frontend_panel(data: PanelData, **kwargs):
    data['content_type'] = 'text/html'

    libraries = []
    for lib in Libraries().select().where(Libraries.enable_remote_only == False):
        libraries.append(f'''{{
            id: {lib.id},
            name: '{lib.name}',
        }},
        ''')
    libraries_str = f'''
    let LIBRARIES = [
        {'\n'.join(libraries)}
    ];
    '''

    with open(os.path.abspath(os.path.join(os.path.dirname(__file__), 'static', 'index.html'))) as file:
        content = file.read()
        data['content'] = content.replace('{cache_buster}', str(uuid.uuid4())).replace('let LIBRARIES = [];',
                                                                                       libraries_str)


def _data_source(arguments: dict) -> dict:
    # logger.info(json.dumps(arguments, indent=2))

    resolved = None
    if 'show_resolved' in arguments and arguments['show_resolved']:
        resolved = int(arguments['show_resolved'])

    library_id = None
    if 'library_id' in arguments and arguments['library_id']:
        library_id = int(arguments['library_id'])

    offset = int(arguments['start'])
    limit = int(arguments['length'])

    order = {
        'column': 0,
        'dir': True,
    }
    if 'order[0][column]' in arguments:
        order = {
            'column': int(arguments['order[0][column]']),
            'dir': arguments['order[0][dir]'],
        }

    # we only allow filtering columns name and issue, the global search field defaults to name
    # don't bother parsing these arrays for now
    search = []
    if 'columns[0][search][value]' in arguments:
        value = arguments['columns[0][search][value]']
        if value:
            search.append({'column': 0, 'value': value})
    if 'columns[1][search][value]' in arguments:
        value = arguments['columns[1][search][value]']
        if value:
            search.append({'column': 1, 'value': value})
    if 'search[value]' in arguments:
        value = arguments['search[value]']
        if value:
            search.append({'column': 0, 'value': value})

    def factory(cur, row):
        name, issues, last_update, resolved, path, rowid = row
        return {
            'DT_RowData': {
                'rowid': rowid,
                'path': path,
            },
            'name': name,
            'issues': issues,
            'date': datetime.fromtimestamp(last_update).strftime('%Y-%m-%d %H:%M:%S'),
            'resolved': bool(resolved),
        }

    data, total, filtered = issues_db.query(library_id=library_id, offset=offset, limit=limit,
                                            order=order, search=search, resolved=resolved,
                                            columns=['name', 'issues', 'last_update', 'resolved', 'path', 'rowid'],
                                            fetch_total=True, row_factory=factory)

    return {
        'draw': int(arguments['draw']),
        'recordsTotal': total,
        'recordsFiltered': filtered,
        'data': data,
    }


def _resolve(body: dict):
    issues_db.resolve(body['resolve'], body['rowid'])


def render_plugin_api(data: PluginApiData, **kwargs):
    data['content_type'] = 'application/json'
    data['content'] = {}

    arguments = data['arguments']
    for key, vals in arguments.items():
        if vals:
            arguments[key] = vals[0].decode('utf-8')
        else:
            arguments[key] = None

    body = data['body']
    if body and body.startswith(b'{'):
        body = json.loads(body.decode('utf-8'))

    try:
        match (data['path'], data['method']):
            case ('/data-source', 'GET'):
                data['content'] = _data_source(arguments)
            case ('/resolve', 'POST'):
                _resolve(body)
            case path, method:
                data['content'] = {
                    'success': False,
                    'error': f'unknown path: {method} {path}',
                }

    except Exception as e:
        trace = traceback.format_exc()
        logger.error(trace)
        data['content'] = {
            'success': False,
            'error': str(e),
            'trace': trace,
        }