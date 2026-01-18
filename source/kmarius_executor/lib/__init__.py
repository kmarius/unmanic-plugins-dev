from kmarius_executor.lib.ffmpeg import Probe


def streams_from_probe(probe_info):
    streams = {
        "audio":      [],
        "video":      [],
        "subtitle":   [],
        "data":       [],
        "attachment": []
    }
    for stream_info in probe_info.get('streams', {}):
        codec_type = stream_info.get('codec_type', '').lower()
        streams[codec_type].append(stream_info)

    # store stream idx in the actual stream info
    for codec_type, streams_infos in streams.items():
        for idx, stream in enumerate(streams_infos):
            stream["idx"] = idx

    return streams


def init(data, logger):
    if "shared_info" not in data:
        data["shared_info"] = {}
    shared_info = data["shared_info"]

    path = data["path"]

    if "ffprobe" not in shared_info:
        probe = Probe(logger, allowed_mimetypes=['audio', 'video'])
        if not probe.file(path):
            shared_info["ffprobe"] = {}
        else:
            shared_info["ffprobe"] = probe.get_probe()

    probe_info = shared_info["ffprobe"]

    shared_info["kmarius"] = {
        "add_file_to_pending_tasks": False,
        "probe":                     probe_info,
        "streams":                   streams_from_probe(probe_info),
        "mappings":                  {},
    }


def lazy_init(data, logger):
    shared_info = data.get("shared_info", {})
    if "kmarius" not in shared_info:
        init(data, logger)
    return shared_info["kmarius"]
