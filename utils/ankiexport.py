import subprocess
import requests
import time
import json
import os


class AnkiExporter():

    def __init__(self):
        
        self.ffmpeg_executable = 'ffmpeg'
        
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
        img_path = os.path.join(self.tmp_dir, img_name)
        img_path = os.path.normpath(img_path)

        audio_name = file_base + '.' + self.audio_format
        audio_path = os.path.join(self.tmp_dir, audio_name)
        audio_path = os.path.normpath(audio_path)

        audio_proc = self.make_audio(media_file, audio_track, time_start, time_end, audio_path)
        screenshot_proc = self.make_snapshot(media_file, time_start, time_end, img_path)
        audio_proc.wait()
        screenshot_proc.wait()

        try:
            img_file = open(img_path,'rb')
            audio_file = open(audio_path,'rb')
        except Exception:
            return -3       # File generation error

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
        


    def make_audio(self, media_file, audio_track, start, end, out_path):
        args = [
            self.ffmpeg_executable,
            '-y', '-loglevel', 'error',
            '-ss', str(start),
            '-i', media_file,
            '-t', str(end-start),
            out_path
        ]

        if audio_track >= 0:
            args[-1:-1] = [
                '-map',
                '0:' + str(audio_track)
            ]

        return subprocess.Popen(args)


    def make_snapshot(self, media_file, start, end, out_path):
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

        return subprocess.Popen(args)
