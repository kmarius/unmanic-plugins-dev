import subprocess
import re
from . import logger


class MP4Box:

    @staticmethod
    def _parse(output: str) -> dict | None:
        lines = output.splitlines()

        match = re.match(r'^# Movie Info - (\d+) tracks? - TimeScale .*$', lines[0])
        if not match:
            logger.error(f"unexpected mp4box output: {lines[0]}")
            return None
        num_tracks = int(match.group(1))
        tracks = []

        def consume_stream(lines: list[str]):
            # Track 6 Info - ID 6 - TimeScale 1000000
            match = re.match(r'^# Track \d+ Info - ID (\d+) - TimeScale (\d+)$', lines[0])
            if not match:
                logger.error(f"malformed mp4box output: {lines[0]}")
                logger.error(output)
                return None
            track = {
                "id": int(match.group(1)),
                "timescale": int(match.group(2)),
            }
            for line in lines[1:]:
                line = line.strip()
                if line.startswith('#'):
                    # next track header
                    break
                if line.startswith('Handler name: '):
                    track["handler_name"] = line[len('Handler Name: '):]
                if line.startswith('Chunk durations: '):
                    # Chunk durations: min 125 ms - max 1000 ms - average 912 ms
                    match = re.match(r'^Chunk durations:.* average (\d+) ms$', line)
                    if not match:
                        logger.error(f"malformed mp4box output: {line}")
                        logger.error(output)
                        return None
                    track["chunk_duration_average"] = int(match.group(1))

            if "handler_name" not in track:
                track["handler_name"] = "unknown"

            return track

        idx = 1
        for i in range(num_tracks):
            # seek to stream start
            while idx < len(lines) and not lines[idx].startswith('#'):
                idx += 1

            track = consume_stream(lines[idx:])
            if not track:
                return None
            tracks.append(track)
            idx += 1

        return {
            "num_tracks": num_tracks,
            "tracks": tracks,
        }

    @staticmethod
    def probe(path) -> dict | None:
        proc = subprocess.run(["MP4Box", "-infox", path], capture_output=True)
        proc.check_returncode()
        return MP4Box._parse(proc.stderr.decode("utf-8"))

    @staticmethod
    def parse_progress(line: str):
        percent = 100

        # ISO File Writing: |=================== | (99/100)
        match = re.search(r'\((\d+)/100\)', line)
        if match:
            percent = int(match.group(1))

        return {
            'percent': percent
        }