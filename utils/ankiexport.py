import subprocess
import socket
import time
import json
import os


class AnkiExporter():

    def __init__(self):
        
        self.mpv_executable = 'mpv'
        self.mpv_cwd = ''
        
        self.dl_dir = os.path.expanduser('~/Downloads')

        self.migaku_dict_host = '127.0.0.1'
        self.migaku_dict_port = 12345



    def export_card(self, media_file, audio_track, text, time_start, time_end, unknowns=[]):

        file_base = str(int(round(time.time() * 1000)))

        img_name = file_base + '.jpg'
        img_path = self.dl_dir + '/' + img_name

        audio_name = file_base + '.wav'
        audio_path = self.dl_dir + '/' + audio_name

        self.make_audio(media_file, audio_track, time_start, time_end, audio_path)
        self.make_snapshot(media_file, time_start, time_end, img_path)

        self.make_request({ 'card': [[audio_name, img_name], text, unknowns] })


    def make_request(self, data):

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
        args = [self.mpv_executable,
                media_file, '--loop-file=no', '--video=no', '--no-ocopy-metadata', '--no-sub',  # just play audio
                '--aid=' + str(audio_track), '--audio-channels=mono', '--oac=pcm_s16le', 
                '--start=' + str(start), '--end=' + str(end),
                '-o=' + out_path]

        subprocess.run(args, cwd=self.mpv_cwd)


    def make_snapshot(self, media_file, start, end, out_path):
        args = [self.mpv_executable,
                media_file, '--loop-file=no', '--audio=no', '--no-ocopy-metadata', '--no-sub',  # just play video
                '--frames=1', '--ovc=mjpeg', '--ovcopts-add=compression_level=6',               # make a jpg
                '-start=' + str( (start + end) / 2),                                            # start in the middle
                '--vf-add=scale=400:-2',
                '-o=' + out_path]

        subprocess.run(args, cwd=self.mpv_cwd)
