import subprocess
import re
from typing import Dict


class MP4BoxInfoxParser:
    """Parse the output of MP4Box -infox"""

    def __init__(self, logger=None):
        self._logger = logger
        self._state = 'unknown'
        self._result: Dict = {}
        self._track = {}
        self._tags = {}
        self._tracks = []
        self._chapters = []
        self._cache = {}

    def parse(self, output: str) -> dict:
        self._state = 'unknown'
        self._result: Dict = {
            'progressive': False,
        }
        self._track = {}
        self._tags = {}
        self._tracks = []
        self._chapters = []

        for line in output.splitlines():
            line = line.strip()
            if not line:
                self._state = 'unknown'
                continue

            # Note: _parse_track_line can change the state to 'sample'
            if self._state == 'unknown':
                if line.startswith('# Movie Info'):
                    self._state = 'header'
                elif line == 'Chapters:':
                    self._state = 'chapters'
                elif line == 'Meta-Data Tags:':
                    self._state = 'metadata'
                elif line.startswith('# Track'):
                    self._state = 'track'
                    if self._track:
                        self._tracks.append(self._track)
                    self._track = {}
                elif line == 'Computed info from media:':
                    self._state = 'info'

            match self._state:
                case 'header':
                    self._parse_header_line(line)
                case 'chapters':
                    self._parse_chapter_line(line)
                case 'metadata':
                    self._parse_metadata_line(line)
                case 'track':
                    self._parse_track_line(line)
                case 'sample':
                    self._parse_sample_line(line)
                case 'info':
                    self._parse_info_line(line)

        if self._chapters:
            self._result['chapters'] = self._chapters

        if self._tags:
            self._result['tags'] = self._tags

        if self._track:
            self._tracks.append(self._track)

        self._result['tracks'] = self._tracks

        return self._result

    def _match(self, regex: str, string: str) -> re.Match | None:
        if regex not in self._cache:
            self._cache[regex] = re.compile(regex)
        return self._cache[regex].match(string)

    def _parse_header_line(self, line: str):
        match = self._match(r'^# Movie Info - (\d+) tracks? - TimeScale (\d+)', line)
        if match:
            num_tracks, timescale = map(int, match.groups())
            self._result['num_tracks'] = num_tracks
            self._result['timescale'] = timescale
            return

        match = self._match(r'^Duration (\d\d):(\d\d):(\d\d)\.(\d+)', line)
        if match:
            h, m, s, ms = map(int, match.groups())
            self._result['duration'] = h * 3600 + m * 60 + s + ms / 1000
            return

        if line == 'Progressive (moov before mdat)':
            self._result['progressive'] = True
            return

        tokens = line.split(': ')
        if len(tokens) == 2:
            key, value = tokens
            if key == 'Fragmented':
                value = value == 'yes'
            self._result[key] = value
            return

        if self._logger:
            self._logger.error(f"Could not parse header line: '{line}'")

    def _parse_chapter_line(self, line: str):
        if line == 'Chapters:':
            return
        match = self._match(r'^#\d+ - ([^ ]+) - "(.*)"', line)
        if match:
            timestamp, title = match.groups()
            self._chapters.append({
                'timestamp': timestamp,
                'title': title,
            })
            return
        if self._logger:
            self._logger.error(f"Could not parse chapter line: '{line}'")

    def _parse_metadata_line(self, line: str):
        if line == 'Meta-Data Tags:':
            return
        if line == '1 UDTA types:':
            # these come from apple, I have not yet seen something meaningful in there
            return
        if line == 'meta:':
            return

        tokens = line.split(': ')
        if len(tokens) == 2:
            self._tags[tokens[0]] = tokens[1]
            return

        if self._logger:
            self._logger.error(f"Could not parse metadata line: '{line}'")

    def _parse_track_line(self, line: str):
        match = self._match(r'^# Track \d+ Info - ID (\d+) - TimeScale (\d+)', line)
        if match:
            id, timescale = map(int, match.groups())
            self._track['id'] = id
            self._track['timescale'] = timescale
            return

        match = self._match(r'^Media Duration (\d\d):(\d\d):(\d\d)\.(\d+)', line)
        if match:
            h, m, s, ms = map(int, match.groups())
            self._track['duration'] = h * 3600 + m * 60 + s + ms / 1000
            return

        match = self._match(r'^Alternate Group ID (\d+)', line)
        if match:
            id = int(match.group(1))
            self._track['Alternate Group ID'] = id
            return

        tokens = line.split(': ')
        if len(tokens) == 2:
            key, value = tokens
            self._track[key] = value
            return

        if line.startswith('Chapter Labels'):
            self._track[line] = True
            return

        if line.startswith('Sample Description #1'):
            self._state = 'sample'
            return

        if self._logger:
            self._logger.error(f"Could not parse track line: '{line}'")

    def _parse_sample_line(self, line: str):
        match = self._match(r'^([^ ]+) Video - Visual Size', line)
        if match:
            self._track['codec_name'] = match.group(1)
            return

        match = self._match(r'^([^ ]+) text', line)
        if match:
            self._track['codec_name'] = match.group(1)
            return

        match = self._match(r'^Size 0 x 0 - Translation X=0 Y=0 - Layer 0', line)
        if match:
            # subtitle tracks have this
            return

        match = self._match(r'^Visual Sample Entry Info: width=(\d+) height=(\d+) \(depth=(\d+) bits\)', line)
        if match:
            width, height, depth = map(int, match.groups())
            self._track['width'] = width
            self._track['height'] = height
            self._track['bit_depth'] = depth
            return

        match = self._match(r'^MPEG-4 Audio AAC LC \(AOT=2 implicit\) - (\d+) Channel\(s\) - SampleRate (\d+)', line)
        if match:
            channels, sample_rate = map(int, match.groups())
            self._track['channels'] = channels
            self._track['sample_rate'] = sample_rate
            return

        match = self._match(r'^EC-3 stream - Sample Rate (\d+) - ([0-9.]) channel(s) - bitrate (\d+) - ATMOS complexity index type 16', line)
        if match:
            sample_rate, channels, bit_rate = match.groups()
            match = self._match(r'^(\d+)\.(\d+)$', channels)
            if match:
                channels = int(match.group(1)) + int(match.group(2))
            else:
                channels = int(channels)
            self._track['channels'] = channels
            self._track['sample_rate'] = int(sample_rate)
            self._track['bit_rate'] = int(sample_rate)
            return

        match = self._match(r'^Pixel Aspect Ratio ([^ ]+) .*', line)
        if match:
            self._track['Pixel Aspect Ratio'] = match.group(1)
            return

        match = self._match(r'^Chroma format (YUV [^ ]+) - Luma bit depth (\d+) - chroma bit depth (\d+)', line)
        if match:
            self._track['chroma_format'] = match.group(1)
            self._track['luma_bit_depth'] = int(match.group(2))
            self._track['chroma_bit_depth'] = int(match.group(3))
            return

        match = self._match(r'^StreamPriority (\d+)', line)
        if match:
            self._track['StreamPriority'] = int(match.group(1))
            return

        if line == 'Alternate Group ID 1':
            self._track[line] = True
            return

        if line == 'No stream dependencies for decoding':
            self._track[line] = True
            return

        if line == 'All samples are sync':
            self._track[line] = True
            return

        if line == 'Only one sync sample':
            self._track[line] = True
            return

        tokens = line.split(': ')
        if len(tokens) == 2:
            key, value = tokens
            self._track[key] = value
            return

        if self._logger:
            self._logger.error(f"Could not parse sample line: '{line}'")

    def _parse_info_line(self, line):
        if line == 'Computed info from media:':
            return

        match = self._match(r'Average rate ([0-9.]+) (k?bps) - Max Rate ([0-9.]+) (k?bps)', line)
        if match:
            avg, avg_unit, max, max_unit = match.groups()
            avg, max = float(avg), float(max)
            if avg_unit == 'kbps':
                avg *= 1024
            if max_unit == 'kbps':
                max *= 1024
            self._track['average_rate'] = avg
            self._track['max_rate'] = avg
            return

        match = self._match(r'^Total size (\d+) bytes - Total samples duration (\d+) ms .*', line)
        if match:
            size, duration = map(int, match.groups())
            self._track['size'] = size
            self._track['samples_duration'] = duration
            return

        match = self._match(r'Chunk sizes \(bytes\): min (\d+) - max (\d+) - average (\d+)', line)
        if match:
            min, max, avg = map(int, match.groups())
            self._track['chunk_size_min'] = min
            self._track['chunk_size_max'] = max
            self._track['chunk_size_average'] = avg
            return

        match = self._match(r'Chunk durations: min (\d+) ms - max (\d+) ms - average (\d+) ms', line)
        if match:
            min, max, avg = map(int, match.groups())
            self._track['chunk_duration_min'] = min
            self._track['chunk_duration_max'] = max
            self._track['chunk_duration_average'] = avg
            return

        tokens = line.split(': ')
        if len(tokens) == 2:
            key, value = tokens
            self._track[key] = value
            return

        if self._logger:
            self._logger.error(f"Could not parse info line: '{line}'")


class MP4Box:
    @staticmethod
    def probe(path, logger=None) -> dict | None:
        proc = subprocess.run(['MP4Box', '-infox', path], capture_output=True)
        proc.check_returncode()
        return MP4BoxInfoxParser(logger=logger).parse(proc.stderr.decode('utf-8'))

    @staticmethod
    def build_command(file_in: str, file_out: str, param: int) -> list[str]:
        """Build MP4Box command to add interleaving to a file."""
        return ['MP4Box', '-inter', str(param), file_in, '-out', file_out]

    @staticmethod
    def parse_progress(line: str):
        """Parse output of MP4Box interleaving command."""
        percent = 100

        # ISO File Writing: |=================== | (99/100)
        match = re.search(r'\((\d+)/100\)', line)
        if match:
            percent = int(match.group(1))

        return {
            'percent': percent
        }