import sys
import os
import time
import shutil
import queue
import json
import subprocess
import psutil
import pathlib
import webbrowser
import threading
import traceback
import platform
from threading import Lock
import pysubs2

from utils.mpv_ipc import MpvIpc
from utils.server import HttpServer, HttpResponse
from utils.ankiexport import AnkiExporter
import utils.browser_support as browser_support


plugin_is_packaged = getattr(sys, 'frozen', False)          # if built with pyinstaller

if plugin_is_packaged:                   
    plugin_dir = os.path.dirname(sys.executable)
else:
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
plugin_dir_name = os.path.basename(plugin_dir)
tmp_dir = plugin_dir + '/tmp'


mpv = None

host = '127.0.0.1'
port = 2222

media_path = None
audio_track = None
subs_json = '[]'
subs_delay = 0.0

anki_exporter = AnkiExporter()

data_queues = []
data_queues_lock = Lock()

config = {}
webbrowser_name = None
reuse_last_tab = True
ffmpeg = 'ffmpeg'
skip_empty_subs = True
subtitle_export_timeout = 7.5

log_file = None


### Handlers for GET requests

def get_handler_subs(socket):

    r = HttpResponse(content=subs_json.encode(), content_type='text/html')
    r.send(socket)


def get_handler_data(socket):

    r = HttpResponse(content_type='text/event-stream', headers={'Cache-Control': 'no-cache'})
    r.send(socket)

    q = queue.Queue()

    data_queues_lock.acquire()
    data_queues.append(q)
    data_queues_lock.release()

    keep_listening = True
    while keep_listening:
        data = q.get()              # Todo: Break if socket dies (Periodic check via timeout?)
                                    #       This breaks reuse_last_tab if load occurs shortly after a tab is closed!
                                    #       Could also be circumvented by checking if the write after put(r) was ok
        if len(data) < 1:
            keep_listening = False
        else:
            cmd = data[0]

            if cmd in ['s', 'r']:
                send_msg = 'data: ' + data + '\r\n\r\n'
                try:
                    socket.sendall(send_msg.encode())
                except:
                    keep_listening = False
            else:
                keep_listening = False

        q.task_done()

    data_queues_lock.acquire()
    data_queues.remove(q)
    data_queues_lock.release()


### Handlers for POST requests

def post_handler_anki(socket, data):

    json_data = json.loads(data)
    
    if audio_track < 0:
        mpv.show_text('Please select an audio track before opening Migaku MPV if you want to export Anki cards.')

    elif len(json_data) == 4:
        text = json_data[0]
        unknowns = json_data[1]
        start = json_data[2]
        end = json_data[3]

        anki_exporter.export_card(media_path, audio_track, text, start, end, unknowns)

    r = HttpResponse()
    r.send(socket)


def post_handler_mpv_control(socket, data):

    mpv.send_json_txt(data)

    r = HttpResponse()
    r.send(socket)


### Managing data streams

def stop_get_data_handlers():

    data_queues_lock.acquire()

    for q in data_queues:
        q.put('q')

    data_queues_lock.release()


def send_subtitle_time(arg):

    time_millis = int(round(float(arg) * 1000)) + subs_delay

    data_queues_lock.acquire()

    for q in data_queues:
        q.put('s' + str(time_millis))

    data_queues_lock.release()


### Called when user presses the migaku key in mpv, transmits info about playing environment

# TODO: Split this
def load_and_open_migaku(mpv_cwd, mpv_pid, mpv_media_path, mpv_audio_track, mpv_sub_info, mpv_subs_delay):
    global subs_json
    global media_path
    global audio_track
    global subs_delay

    mpv_executable = psutil.Process(int(mpv_pid)).cmdline()[0]
    anki_exporter.mpv_cwd = mpv_cwd
    anki_exporter.mpv_executable = mpv_executable

    media_path = mpv_media_path
    audio_track = int(mpv_audio_track)

    subs_delay = int(round(float(mpv_subs_delay) * 1000))


    if mpv_sub_info == '' or mpv_sub_info == None:
        mpv.show_text('Please select a subtitle track.')
        return

    sub_path = None

    if '*' in mpv_sub_info:
        internal_sub_info = mpv_sub_info.split('*')
        if len(internal_sub_info) == 2:
            ffmpeg_track = internal_sub_info[0]
            sub_codec = internal_sub_info[1]
            if sub_codec in ['srt', 'ass']:
                if not ffmpeg:
                    mpv.show_text('Using internal subtitles requires ffmpeg to be located in the plugin directory.')
                    return
                sub_path = tmp_dir + '/' + str(pathlib.Path(media_path).stem) + '.' + sub_codec
                args = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-i', media_path, '-map', '0:' + ffmpeg_track, sub_path]
                try:
                    subprocess.run(args, timeout=subtitle_export_timeout)
                    if not os.path.isfile(sub_path):
                        raise FileNotFoundError
                except TimeoutError:
                    mpv.show_text('Exporting internal subtitle track timed out.')
                    return
                except:
                    mpv.show_text('Exporting internal subtitle track failed.')
                    return
            else:
                mpv.show_text('Selected internal subtitle track is not supported.\n\nOnly SRT and ASS tracks are supported.')
                return
    else:
        sub_path = mpv_sub_info

    if not sub_path:    # Should not happen
        return

    if not os.path.isfile(sub_path):
        mpv.show_text('The subtitle file "%s" was not found.' % sub_path)
        return

    # Parse subs and generate json for frontend
    subs = pysubs2.load(sub_path, encoding="utf-8")     # TODO: check if extension is correct and catch exceptions when reading!
    subs_list = []

    for s in subs:
        text = s.plaintext
        if not skip_empty_subs or text.strip():
            sub_start = max(s.start + subs_delay, 0)
            sub_end = max(s.end + subs_delay, 0)
            subs_list.append( { 'text': text, 'start': sub_start, 'end': sub_end } )

    # some subtitle formats are allowed to be out of order. Whyyy...
    subs_list.sort(key=lambda x: x['start'])

    subs_json = json.dumps(subs_list)


    # Open or refresh frontend
    url = 'http://' + str(host) + ':' + str(port)

    data_queues_lock.acquire()

    finalize_queues = data_queues

    if reuse_last_tab and len(data_queues) > 0:
        data_queues[-1].put('r')
        finalize_queues = finalize_queues[:-1]
    else:
        try:
            webbrowser.get(webbrowser_name).open(url, new=0, autoraise=True)
        except:
            mpv.show_text('Warning: Opening the subtitle browser with configured browser failed.\n\nPlease review your config.')
            webbrowser.open(url, new=0, autoraise=True)

    for q in finalize_queues:
        q.put('q')

    data_queues_lock.release()


def exception_hook(exc_type, exc_value, exc_traceback):
    print('--------------')
    print('UNHANDLED EXCEPTION OCCURED:\n')
    print('Platform:', platform.platform())
    print('Python:', sys.version.replace('\n', ' '))
    traceback_strs = traceback.format_exception(exc_type, exc_value, exc_traceback)
    traceback_str = ''.join(traceback_strs)
    print(traceback_str)
    print('EXITING')
    
    # What folllows is pretty dirty, but all threads need to die and I'm lazy right now
    # TODO

    try:
        sys.stdout.flush()
        sys.stderr.flush()

        if log_file:
            log_file.flush()
            log_file.close()
    except:
        pass

    os._exit(1)


def exception_hook_threads(args):
    exception_hook(args.exc_type, args.exc_value, args.exc_traceback)


def main():
    global log_file
    global mpv
    global host
    global port
    global reuse_last_tab
    global webbrowser_name
    global ffmpeg
    global skip_empty_subs

    sys.excepthook = exception_hook
    threading.excepthook = exception_hook_threads

    # Redirect stdout/stderr to log file if built for release
    if plugin_is_packaged:
        log_file = open(plugin_dir + '/log.txt', 'w', encoding='utf8')
        sys.stdout = log_file
        sys.stderr = log_file

    # Check command line args
    if len(sys.argv) != 2 and len(sys.argv) != 3:
        print('Invalid arguments.\nUsage: %s mpv-ipc-handle [config path]')
        return

    config_path = plugin_dir + '/migaku_mpv.cfg'
    if len(sys.argv) >= 3:
        config_path = sys.argv[2]

    # Make temp dir
    os.makedirs(tmp_dir, exist_ok=True)

    # Load config
    config_f = open(config_path, 'r', encoding="utf-8")
    for line in config_f:
        line = line.strip()
        if line.startswith('#'):
            continue
        equals_pos = line.find('=')
        if equals_pos < 0:
            continue
        key = line[0:equals_pos].strip()
        if key == '':
            continue
        value = line[equals_pos+1:].strip()
        config[key] = value
    config_f.close()
    print('CFG:', config)

    host = config.get('host', '127.0.0.1')
    try:
        port = int(config.get('port', '2222'))
    except:
        port = 2222

    reuse_last_tab = config.get('reuse_last_tab', 'yes').lower() == 'yes'

    browser = config.get('browser', 'default')
    if browser.lower() == 'default':
        browser = None
    else:
        browser = browser_support.expand_browser_name(browser)
    print('BRS:', browser)
    webbrowser_name = browser

    browser_downloads_dir = config.get('browser_downloads_directory', '~/Downloads')
    browser_downloads_dir = browser_downloads_dir.replace('%userprofile%', '~')
    browser_downloads_dir = os.path.expanduser(browser_downloads_dir)
    anki_exporter.dl_dir = browser_downloads_dir

    if 'ffmpeg' in config:
        ffmpeg = config.get('ffmpeg', 'ffmpeg')
    else:
        check_path = plugin_dir + '/ffmpeg'
        if os.name == 'nt':
            check_path = check_path + '.exe'
        if os.path.isfile(check_path):
            ffmpeg = check_path
        else:
            ffmpeg = shutil.which('ffmpeg')     # Set to none when ffmpeg is not found

    skip_empty_subs = config.get('skip_empty_subs', 'yes').lower() == 'yes'
    try:
        subtitle_export_timeout = float(config.get('subtitle_export_timeout', '7.5'))
    except:
        port = 7.5

    # Init mpv IPC
    mpv = MpvIpc(sys.argv[1])

    # Setup server
    server = HttpServer(host, port)
    server.set_get_file_server('/', plugin_dir + '/migaku_mpv.html')
    for path in ['/icons/migakufavicon.png', '/icons/anki.png', '/icons/bigsearch.png']:
        server.set_get_file_server(path, plugin_dir + path)
    server.set_get_handler('/subs', get_handler_subs)
    server.set_get_handler('/data', get_handler_data)
    server.set_post_handler('/anki', post_handler_anki)
    server.set_post_handler('/mpv_control', post_handler_mpv_control)
    server.open()

    # Main loop, exits when IPC connection closes
    for data in mpv.listen():
        print('MPV:', data)
        if ('event' in data) and (data['event'] == 'client-message'):
            event_args = data.get('args', [])
            if len(event_args) >= 2 and event_args[0] == '@migaku':
                cmd = event_args[1]
                if cmd == 'sub-start':
                    send_subtitle_time(event_args[2])
                elif cmd == 'open':
                    load_and_open_migaku(*event_args[2:7+1])

    # Close server
    server.close()
    stop_get_data_handlers()

    # Close mpv IPC
    mpv.close()

    # Rempve temp dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
