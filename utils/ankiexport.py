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

    class ExportError(Exception):
        pass

    def __init__(self):

        self.mpv_executable = 'mpv'
        self.ffmpeg_executable = 'ffmpeg'
        self.mpv_cwd = os.path.expanduser('~')

        self.migaku_anki_host = '127.0.0.1'
        self.migaku_anki_port = 44432

        self.image_format = 'jpg'
        self.audio_format = 'wav'

        self.image_width = None
        self.image_height = None


    def export_card(self, media_file, audio_track, text_primary, text_secondary, time_start, time_end, unknowns=[], bulk_id=0, bulk_count=1, bulk_timestamp=time.time()):

        print("MAKE CARD", media_file, text_primary) 

        if not media_file.startswith('http'):
            media_file = os.path.normpath(media_file)

        try:
            r = requests.get(F'http://{self.migaku_anki_host}:{self.migaku_anki_port}/info')
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise self.ExportError('Could not connect to Anki.\nMake sure Anki is running and the latest Migaku add-on is installed.')

        info = r.json()
        col_path = info['col_media_path']
        
        file_base = 'migaku-local-' + str(int(round(time.time() * 1000)))

        img_name = file_base + '.' + self.image_format
        img_path = os.path.join(col_path, img_name)
        img_path = os.path.normpath(img_path)

        audio_name = file_base + '.' + self.audio_format
        audio_path = os.path.join(col_path, audio_name)
        audio_path = os.path.normpath(audio_path)

        error = self.make_audio(media_file, audio_track, time_start, time_end, audio_path)
        error = self.make_screenshot(media_file, time_start, time_end, img_path)

        if not os.path.exists(img_path) or not os.path.exists(audio_path):
            raise self.ExportError('Generating image/audio failed.')

        data = {
            'version':              2,
            'timestamp':            round(bulk_timestamp),
            'sentence':             text_primary,
            'sentence_translation': text_secondary,
            'unknown_words':        unknowns,
            'image':                img_name,
            'sentence_audio':       audio_name,
            'batch_count':          bulk_count,
            'batch_id':             bulk_id,
        }

        try:
            r = requests.post(
                F'http://{self.migaku_anki_host}:{self.migaku_anki_port}/sendcard',
                json=data,
            )
            r.raise_for_status()
        except requests.exceptions.RequestException:
            raise self.ExportError('Communication failed.\nMake sure the latest Migaku add-on is installed.')

        status = r.json()['status']

        if status == 'not_connected':
            raise self.ExportError('Connection to browser extension failed.')

        if status == 'cancelled':
            raise self.ExportError('Cancelled.')


    def ffmpeg_audio(self, media_file, audio_track, start, end, out_path):
        args = [
                self.ffmpeg_executable,
                '-y', '-loglevel', 'error',
                '-ss', str(start),
                '-to', str(end),
                '-i', media_file,
                '-map', '0:' + str(audio_track)
                '-acodec', 'mp3',
                out_path
                ]

        error = None
        try:
            proc = subprocess.Popen(args, cwd=self.mpv_cwd)
            proc.wait()
        except FileNotFoundError:
            pass

        # Check that image was saved
        if not os.path.exists(out_path):
            error = Errors.FFMPEG_AUDIO_ERROR
        return error

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
        return error

    def make_audio(self, media_file, audio_track, start, end, out_path):
        # Default to using ffmpeg for audio
        error = self.ffmpeg_audio(media_file, audio_track, start, end, out_path)
        # Fall back to mpv if ffmpeg fails
        if error == Errors.FFMPEG_AUDIO_ERROR:
            print("AUDIO: Falling back to mpv")
            error = self.mpv_audio(media_file, audio_track, start, end, out_path)

        if error:            
            error = Errors.AUDIO_ERROR

        return error


    def ffmpeg_screenshot(self, media_file, start, end, out_path):
        args = [
                self.ffmpeg_executable,
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
        try:
            proc = subprocess.Popen(args, cwd=self.mpv_cwd)
            proc.wait()
        except FileNotFoundError:
            pass

        # Check that image was saved
        if not os.path.exists(out_path):
            error = Errors.FFMPEG_SCREENSHOT_ERROR
        return error

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

        return error

    def make_screenshot(self, media_file, start, end, out_path):
        # Default to using ffmpeg for screenshots
        error = self.ffmpeg_screenshot(media_file, start, end, out_path)
        # Fall back to mpv if ffmpeg fails
        if error == Errors.FFMPEG_SCREENSHOT_ERROR:
            print("SCREENSHOT: Falling back to mpv")
            error = self.mpv_screenshot(media_file, start, end, out_path)

        if error:
            error = Errors.SCREENSHOT_ERROR

        return error
