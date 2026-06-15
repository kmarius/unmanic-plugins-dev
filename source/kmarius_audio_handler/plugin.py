from typing import Optional

from kmarius_audio_handler.lib import logger
from kmarius_audio_handler.lib.types import FileTestData
from kmarius_executor.lib import init_task_data


def check_stream_lang(stream_info: dict, lang: str) -> bool:
    return stream_info.get('tags', {}).get('language', '').lower() == lang


# try to find an english language stream and return its index. If there are multiple, returns one with the most channels
def search_eng_idx(streams: dict) -> Optional[int]:
    lang_idx = None
    lang_channels = None
    for idx, stream_info in enumerate(streams):
        if check_stream_lang(stream_info, 'eng'):
            channels = stream_info.get('channels', 0)
            if lang_idx is None or channels > lang_channels:
                lang_idx = idx
                lang_channels = channels
    return lang_idx


# convert non-aac streams to aac
def audio_stream_mapping(stream_info: dict, idx: int) -> Optional[dict]:
    codec_name = stream_info['codec_name']
    if codec_name in ['aac', 'opus']:
        return None
    logger.info(f'converting audio stream {idx} from {codec_name}')
    channels = int(stream_info.get('channels'))
    if channels > 6:
        bit_rate = '384k'
    elif channels == 6:
        bit_rate = '256k'
    else:
        bit_rate = '128k'
    stream_encoding = [
        f'-c:a:{idx}', 'libopus',
        f'-b:a:{idx}', f'{bit_rate}',
        f'-filter:a:{idx}', 'aformat=channel_layouts=7.1|5.1|stereo'
    ]
    return {
        'stream_mapping': ['-map', f'0:a:{idx}'],
        'stream_encoding': stream_encoding,
    }


def on_library_management_file_test(data: FileTestData, **kwargs):
    task_data = init_task_data(data)

    # TODO: add functionality for foreign language films

    audio_streams = task_data['streams']['audio']
    audio_mappings = {}

    # try to find an english language stream
    eng_idx = search_eng_idx(audio_streams)

    for idx, stream_info in enumerate(audio_streams):
        # remove non-eng streams if there is an english one
        if eng_idx is None or idx == eng_idx:
            mapping = audio_stream_mapping(stream_info, idx)
        else:
            mapping = {
                'stream_mapping': [],
                'stream_encoding': [],
            }
        if mapping:
            audio_mappings[idx] = mapping

    task_data['mappings']['audio'] = audio_mappings
    if audio_mappings:
        task_data['add_file_to_pending_tasks'] = True