from re import A
import subprocess
import requests
import time
import json
import os

from enum import Enum

class Errors(Enum):
    FFMPEG_SCREENSHOT_ERROR = 1
    MPV_SCREENSHOT_ERROR = 2
    SCREENSHOT_ERROR = 3

    FFMPEG_AUDIO_ERROR = 4
    MPV_AUDIO_ERROR = 5
    AUDIO_ERROR = 6

class AnkiExporter():

    def __init__(self):

        self.mpv_executable = 'mpv'
        self.mpv_cwd = os.path.expanduser('~')

        self.tmp_dir = '.'

        self.migaku_dict_host = '127.0.0.1'
        self.migaku_dict_port = 12345

        self.image_format = 'jpg'
        self.audio_format = 'wav'

        self.image_width = None
        self.image_height = None



    def export_card(self, media_file, audio_track, text_primary, text_secondary, time_start, time_end, unknowns=[], bulk_count=1, bulk_timestamp=time.time()):

        if not media_file.startswith('http'):
            media_file = os.path.normpath(media_file)

        file_base = str(int(round(time.time() * 1000)))

        img_name = file_base + '.' + self.image_format
        img_path = self.tmp_dir + '/' + img_name
        img_path = os.path.normpath(img_path)

        audio_name = file_base + '.' + self.audio_format
        audio_path = self.tmp_dir + '/' + audio_name
        audio_path = os.path.normpath(audio_path)

        error, audio_proc = self.make_audio(media_file, audio_track, time_start, time_end, audio_path)
        error, screenshot_proc = self.make_snapshot(media_file, time_start, time_end, img_path)

        try:
            img_file = open(img_path,'rb')
            audio_file = open(audio_path,'rb')
        except Exception:
            return -3      # File generation error

        data = {
            'version':   (None, 2),
            'timestamp': (None, round(bulk_timestamp)),
            'primary':   (None, text_primary),
            'secondary': (None, text_secondary),
            'unknown':   (None, json.dumps(unknowns)),
            'image':     (img_name, img_file),
            'audio':     (audio_name, audio_file),
        }

        if bulk_count > 1:
            data['bulk'] = (None, 'true' if bulk_count > 0 else 'false')
            data['totalToRecord'] = (None, bulk_count)

        try:
            r = requests.post(
                'http://%s:%d/import' % (self.migaku_dict_host, self.migaku_dict_port),
                files=data
            )
        except requests.ConnectionError:
            return -1

        if r.status_code != 200:
            return -1

        if b'cancelled' in r.content:
            return -2

        return 0

    def ffmpeg_audio(self, media_file, audio_track, start, end, out_path):
        args = [
                'ffmpeg',
                '-y', '-loglevel', 'error',
                '-ss', str(start),
                '-to', str(end),
                '-i', media_file,
                '-acodec', 'mp3',
                out_path
                ]

        error = None
        proc = subprocess.Popen(args, cwd=self.mpv_cwd)
        proc.wait()

        # Check that image was saved
        if not os.path.exists(out_path):
            error = Errors.FFMPEG_AUDIO_ERROR
        return error, proc

    def mpv_audio(self, media_file, audio_track, start, end, out_path):
        args = [self.mpv_executable, '--load-scripts=no',                                       # start mpv without scripts
                media_file, '--loop-file=no', '--video=no', '--no-ocopy-metadata', '--no-sub',  # just play audio
                '--aid=' + str(audio_track),
                '--start=' + str(start), '--end=' + str(end),
                '--o=' + out_path]

        error = None
        proc = subprocess.Popen(args, cwd=self.mpv_cwd)
        proc.wait()

        # Check that image was saved
        if not os.path.exists(out_path):
            error = Errors.FFMPEG_SCREENSHOT_ERROR
        return error, proc

    def make_audio(self, media_file, audio_track, start, end, out_path):
        # Default to using ffmpeg for audio
        error, proc = self.ffmpeg_audio(media_file, audio_track, start, end, out_path)
        # Fall back to mpv if ffmpeg fails
        if error == Errors.FFMPEG_AUDIO_ERROR:
            error, proc = self.mpv_audio(media_file, audio_track, start, end, out_path)

        if error:
            error = Errors.AUDIO_ERROR

        return error, proc

    def ffmpeg_screenshot(self, media_file, start, end, out_path):
        args = [
                'ffmpeg',
                '-y', '-loglevel', 'error',
                '-ss', str((start + end) / 2),
                '-i', media_file,
                '-vframes', '1',
                out_path
                ]

        # See https://ffmpeg.org/ffmpeg-filters.html#scale-1 for scaling options

        # None or values smaller than 1 set the axis to auto
        w = self.image_width
        if w is None or w < 1:
            w = -1
        h = self.image_height
        if h is None or h < 1:
            h = -1

        # Only apply filter if any axis is set to non-auto
        if w > 0 or h > 0:
                args[-1:-1] = [
                    '-filter:v',
                    'scale=w=\'min(iw,%d)\':h=\'min(ih,%d)\':force_original_aspect_ratio=decrease'
                    % (w, h)
                ]
        error = None
        proc = subprocess.Popen(args, cwd=self.mpv_cwd)
        proc.wait()

        # Check that image was saved
        if not os.path.exists(out_path):
            error = Errors.FFMPEG_SCREENSHOT_ERROR
        return error, proc

    def mpv_screenshot(self, media_file, start, end, out_path):
        args = [self.mpv_executable, '--load-scripts=no',                                       # start mpv without scripts
                media_file, '--loop-file=no', '--audio=no', '--no-ocopy-metadata', '--no-sub',  # just play video
                '--frames=1',                                                                   # for one frame
                '--start=' + str( (start + end) / 2),                                           # start in the middle
                '--o=' + out_path]

        # See https://ffmpeg.org/ffmpeg-filters.html#scale-1 for scaling options

        # None or values smaller than 1 set the axis to auto
        w = self.image_width
        if w is None or w < 1:
            w = -1
        h = self.image_height
        if h is None or h < 1:
            h = -1

        # Only apply filter if any axis is set to non-auto
        if w > 0 or h > 0:
            # best would be 'min(iw,w)' but mpv doesn't allow passing filters with apostrophes
            scale_arg = '--vf-add=scale=w=%d:h=%d:force_original_aspect_ratio=decrease' % (w, h)
            args.append(scale_arg)

        error = None
        proc = subprocess.Popen(args, cwd=self.mpv_cwd)
        proc.wait()
        # Check that image was saved
        if not os.path.exists(out_path):
            error = Errors.MPV_SCREENSHOT_ERROR

        return error, proc

    def make_snapshot(self, media_file, start, end, out_path):
        # Default to using ffmpeg for screenshots
        error, proc = self.ffmpeg_screenshot(media_file, start, end, out_path)
        # Fall back to mpv if ffmpeg fails
        if error == Errors.FFMPEG_SCREENSHOT_ERROR:
            error, proc = self.mpv_screenshot(media_file, start, end, out_path)

        if error:
            error = Errors.SCREENSHOT_ERROR

        return error, proc
