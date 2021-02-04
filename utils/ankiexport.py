import subprocess
import socket
import time
import json
import os


class AnkiExporter():

    def __init__(self):
        
        self.mpv_executable = 'mpv'
        self.mpv_cwd = os.path.expanduser('~')
        
        self.dl_dir = os.path.expanduser('~/Downloads')

        self.migaku_dict_host = '127.0.0.1'
        self.migaku_dict_port = 12345

        self.image_format = 'jpg'
        self.audio_format = 'wav'

        self.image_width = None
        self.image_height = None



    def export_card(self, media_file, audio_track, text, time_start, time_end, unknowns=[], is_bulk=False):

        if not media_file.startswith('http'):
            media_file = os.path.normpath(media_file)

        file_base = str(int(round(time.time() * 1000)))

        img_name = file_base + '.' + self.image_format
        img_path = self.dl_dir + '/' + img_name
        img_path = os.path.normpath(img_path)

        audio_name = file_base + '.' + self.audio_format
        audio_path = self.dl_dir + '/' + audio_name
        audio_path = os.path.normpath(audio_path)

        self.make_audio(media_file, audio_track, time_start, time_end, audio_path)
        self.make_snapshot(media_file, time_start, time_end, img_path)

        self.make_request({ 'card': [[audio_name, img_name], text, unknowns, is_bulk] })


    def make_request(self, data):

        print('ANKI:', data)

        request_data = json.dumps(data)

        request = 'GET / HTTP/1.1\r\nContent-Length: %d\r\n\r\n' % len(request_data)
        request += request_data

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((self.migaku_dict_host, self.migaku_dict_port))
            s.send(request.encode())
            s.close()
        except:
            pass

        


    def make_audio(self, media_file, audio_track, start, end, out_path):
        args = [self.mpv_executable, '--load-scripts=no',                                       # start mpv without scripts
                media_file, '--loop-file=no', '--video=no', '--no-ocopy-metadata', '--no-sub',  # just play audio
                '--aid=' + str(audio_track),
                '--start=' + str(start), '--end=' + str(end),
                '--o=' + out_path]

        subprocess.run(args, cwd=self.mpv_cwd)


    def make_snapshot(self, media_file, start, end, out_path):
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

        subprocess.run(args, cwd=self.mpv_cwd)
