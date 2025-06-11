from kmarius.lib.ffmpeg import Probe

def streams_from_probe(probe):
    streams = {
        "audio":      [],
        "video":      [],
        "subtitle":   [],
        "data":       [],
        "attachment": []
    }
    for stream_info in probe.get('streams', {}):
        codec_type = stream_info.get('codec_type', '').lower()
        streams[codec_type].append(stream_info)

    # store stream idx in the actual stream info
    for codec_type, streams_infos in streams.items():
        for idx, stream in enumerate(streams_infos):
            stream["idx"] = idx

    return streams


def init(data, logger):
    abspath = data.get('path')
    probe = Probe(logger, allowed_mimetypes=['audio', 'video'])
    if not probe.file(abspath):
        probe = {}
    info = data.get("shared_info")
    info["kmarius"] = {
        "add_file_to_pending_tasks": False,
        "probe":                     probe,
        "streams":                   streams_from_probe(probe),
        "mappings":                  {},
    }


def lazy_init(data, logger):
    shared_info = data.get("shared_info")
    if not "kmarius" in shared_info:
        init(data, logger)
    return shared_info["kmarius"]