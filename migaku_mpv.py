import sys
import os
import time
import shutil
import queue
import json
import subprocess
import collections
import psutil
import pathlib
import webbrowser
import threading
import traceback
import platform
import pysubs2
import codecs
import cchardet as chardet
import requests
import urllib.parse
import urllib.request

from utils.mpv_ipc import MpvIpc
from utils.server import HttpServer, HttpResponse
from utils.ankiexport import AnkiExporter
import utils.browser_support as browser_support


dev_mode = os.path.exists('./dev_flag')

plugin_is_packaged = getattr(sys, 'frozen', False)          # if built with pyinstaller

if plugin_is_packaged:                   
    plugin_dir = os.path.dirname(sys.executable)
else:
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
plugin_dir_name = os.path.basename(plugin_dir)
tmp_dir = os.path.join(plugin_dir, 'tmp')


mpv = None

host = '127.0.0.1'
port = None

media_path = None
audio_track = None
resx = 1920
resy = 1080
sub_font_name = 'Noto Sans CJK JP Regular'
sub_font_size = 55
sub_bottom_margin = 22
sub_outline_size = 3
sub_shadow_offset = 0
subs_json = '[]'
subs_delay = 0

anki_exporter = AnkiExporter()

data_queues = []
data_queues_lock = threading.Lock()

last_subs_request = 0

config = {}
webbrowser_name = None
reuse_last_tab = True
reuse_last_tab_timeout = 1.5
ffmpeg = 'ffmpeg'
ffsubsync = 'ffsubsync'
rubysubs = 'rubysubs'
mpv_external = None
skip_empty_subs = True
subtitle_export_timeout = 0

log_file = None


def path_clean(path):

    if path.startswith('file:'):
        uri_path = urllib.parse.urlparse(path).path
        return urllib.request.url2pathname(uri_path)
    
    return path


### Handlers for GET requests

def get_handler_subs(socket):

    global last_subs_request
    last_subs_request = time.time()

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
        data = q.get()

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

    r = HttpResponse()
    r.send(socket)
    
    if audio_track < 0:
        mpv.show_text('Please select an audio track before opening Migaku MPV if you want to export Anki cards.')
        return

    json_data = data.decode()

    cards = json.loads(json_data)

    is_mass_export = len(cards) > 1

    timestamp = time.time()

    for i, card in enumerate(cards):
        text = card[0]
        unknowns = card[1]
        # ms to seconds
        start = card[2] / 1000.0
        end = card[3] / 1000.0

        r = anki_exporter.export_card(media_path, audio_track, text, start, end, unknowns, len(cards), timestamp)

        if r == -1: # Failure
            mpv.show_text('Exporting card failed.\n\nMake sure Anki is running and that you are using the latest versions of Migaku Dictionary, Migaku Browser Extension and Migaku MPV.', 8.0)
            return
        if r == -2: # Cancelled
            mpv.show_text('Card export cancelled.')
            return
        if r == -3: # Image/Audio exporting failrue
            mpv.show_text('Exporting image/audio failed.')
            return
        if r < 0:
            mpv.show_text('Unknown export error.')
            return

        if is_mass_export:
            mpv.show_text('%d/%d' % (i+1, len(cards)), 10.0)

    if is_mass_export:
        mpv.show_text('Card export finished.')


def post_handler_mpv_control(socket, data):

    mpv.send_json_txt(data.decode())

    r = HttpResponse()
    r.send(socket)


def post_handler_set_subs(socket, data):
    global subs_delay

    r = HttpResponse()
    r.send(socket)

    if rubysubs is None:
        mpv.show_text('Subtitle styling requires rubysubs to be located in the plugin directory.')
        return

    if data:
        path = os.path.join(tmp_dir, 'migaku_parsed_%d.ass' % round(time.time() * 1000))
        json_data = json.loads(data)
        
        subs = pysubs2.SSAFile()

        subs.info = {
            'Title':    'Migaku Parsed',
            'PlayResX': str(resx),
            'PlayResY': str(resy),
            # "ScriptType: v4.00+" automatically added
        }

        font_name = sub_font_name

        font_size = sub_font_size
        font_size = int((resy / 720) * font_size)

        bottom_margin = sub_bottom_margin
        bottom_margin = int((resy / 720) * bottom_margin)

        outline_size = sub_outline_size
        outline_size = int((resy / 720) * outline_size)

        shadow_offset = sub_shadow_offset
        shadow_offset = int((resy / 720) * shadow_offset)

        subs.styles = {
            'Default': pysubs2.SSAStyle(
                fontname=font_name,
                fontsize=font_size,
                primarycolor=pysubs2.Color(255, 255, 255, 0),
                secondarycolor=pysubs2.Color(255, 0, 0, 0),
                outlinecolor=pysubs2.Color(0, 0, 0, 0),
                backcolor=pysubs2.Color(0, 0, 0, 0),
                bold=False,
                italic=False,
                underline=False,
                strikeout=False,
                scalex=100,
                scaley=100,
                spacing=0,
                angle=0,
                borderstyle=1,
                outline=outline_size,
                shadow=shadow_offset,
                alignment=2,
                marginl=0,
                marginr=0,
                marginv=bottom_margin
            ),
        }

        for (start, end, text) in json_data['subs']:
            text = text.replace('\n', '\\N')
            text = text.replace('&nbsp;', '\u00A0')
            subs.events.append(pysubs2.SSAEvent(start=start, end=end, text=text))

        subs.save(path)

        r = subprocess.run([rubysubs, path, path, json_data['parser'], *json_data['parser_args']])
        if r.returncode == 0:
            mpv.command('sub-add', path)
            mpv.command('set_property', 'sub-delay', 0)
            subs_delay = 0
            mpv.command('script-message', '@migakulua', 'remove_inactive_parsed_subs')
        else:
            mpv.show_text('Styling subtitles failed.')



### Managing data streams

def stop_get_data_handlers():

    data_queues_lock.acquire()

    for q in data_queues:
        q.put('q')

    data_queues_lock.release()


def send_subtitle_time(arg):

    time_millis = (int(round(float(arg) * 1000)) + subs_delay) // 10 * 10

    data_queues_lock.acquire()

    for q in data_queues:
        q.put('s' + str(time_millis))

    data_queues_lock.release()



def open_webbrowser_new_tab():
    url = 'http://' + str(host) + ':' + str(port)

    try:
        webbrowser.get(webbrowser_name).open(url, new=0, autoraise=True)
    except:
        mpv.show_text('Warning: Opening the subtitle browser with configured browser failed.\n\nPlease review your config.')
        webbrowser.open(url, new=0, autoraise=True)


def tab_reload_timeout():
    time.sleep(reuse_last_tab_timeout)

    if last_subs_request < (time.time() - (reuse_last_tab_timeout + 0.25)):
        print('BRS: Tab timed out.')
        open_webbrowser_new_tab()


### Called when user presses the migaku key in mpv, transmits info about playing environment

# TODO: Split this
def load_and_open_migaku(mpv_cwd, mpv_pid, mpv_media_path, mpv_audio_track, mpv_sub_info, mpv_subs_delay, mpv_resx, mpv_resy):
    global subs_json
    global media_path
    global audio_track
    global subs_delay
    global resx
    global resy

    if port is None:
        mpv.show_text('Not ready...')
        return

    mpv_executable = psutil.Process(int(mpv_pid)).cmdline()[0]
    if os.path.split(mpv_executable)[-1].lower() in ['mpv', 'mpv.exe']:
        anki_exporter.mpv_cwd = mpv_cwd
        anki_exporter.mpv_executable = mpv_executable
    else:
        print('Using external mpv')
        if not mpv_external:
            mpv.show_text('Please set mpv_external in the config file.')
            return
        anki_exporter.mpv_cwd = None
        anki_exporter.mpv_executable = mpv_external

    media_path = mpv_media_path
    audio_track = int(mpv_audio_track)

    subs_delay = int(round(float(mpv_subs_delay) * 1000))

    resx = int(mpv_resx)
    resy = int(mpv_resy)


    if mpv_sub_info == '' or mpv_sub_info == None:
        mpv.show_text('Please select a subtitle track.')
        return

    if 'migaku_parsed' in mpv_sub_info:
        mpv.show_text('Please select a subtitle track that was not created by Migaku.')
        return

    sub_path = None

    if '*' in mpv_sub_info:
        internal_sub_info = mpv_sub_info.split('*')
        if len(internal_sub_info) == 2:
            ffmpeg_track = internal_sub_info[0]
            sub_codec = internal_sub_info[1]
            if sub_codec in ['subrip', 'ass']:
                if not ffmpeg:
                    mpv.show_text('Using internal subtitles requires ffmpeg to be located in the plugin directory.')
                    return
                mpv.show_text('Exporting internal subtitle track...', duration=150.0)    # Next osd message will close it
                if sub_codec == 'subrip':
                    sub_extension = 'srt'
                else:
                    sub_extension = sub_codec
                sub_path = tmp_dir + '/' + str(pathlib.Path(media_path).stem) + '.' + sub_extension
                args = [ffmpeg, '-y', '-loglevel', 'error', '-i', media_path, '-map', '0:' + ffmpeg_track, sub_path]
                try:
                    timeout = subtitle_export_timeout if subtitle_export_timeout > 0 else None
                    subprocess.run(args, timeout=timeout)
                    if not os.path.isfile(sub_path):
                        raise FileNotFoundError
                except TimeoutError:
                    mpv.show_text('Exporting internal subtitle track timed out.')
                    return
                except:
                    mpv.show_text('Exporting internal subtitle track failed.')
                    return
            else:
                mpv.show_text('Selected internal subtitle track is not supported.\n\nOnly SRT and ASS tracks are supported.\n\nSelected track is ' + sub_codec)
                return
    else:
        sub_path = mpv_sub_info

    if not sub_path:    # Should not happen
        return

    # Support drag & drop subtitle files on some systems
    sub_path = path_clean(sub_path)

    # Web subtitle?
    is_websub = False
    if sub_path.startswith('edl://'):
        i = sub_path.rfind('http')
        if i >= 0:
            url = sub_path[i:]
            
            try:
                response = requests.get(url)
                tmp_sub_path = os.path.join(tmp_dir, 'websub_%d.vtt' % round(time.time() * 1000))
                with open(tmp_sub_path, 'wb') as f:
                    f.write(response.content)
            
                sub_path = tmp_sub_path
                is_websub = True
            except Exception:
                mpv.show_text('Downloading web subtitles failed.')
                return

    elif sub_path.startswith('http'):
        try:            
            response = requests.get(sub_path)
            tmp_sub_path = os.path.join(tmp_dir, 'websub_%d' % round(time.time() * 1000))
            with open(tmp_sub_path, 'wb') as f:
                f.write(response.content)
            
            sub_path = tmp_sub_path
        except Exception:
            mpv.show_text('Downloading web subtitles failed.')
            return

    if not os.path.isfile(sub_path):
        print('SUBS Not found:', sub_path)
        mpv.show_text('The subtitle file "%s" was not found.' % sub_path)
        return

    # Determine subs encoding
    subs_encoding = 'utf-8'
    
    try:
        subs_f = open(sub_path, 'rb')
        subs_data = subs_f.read()
        subs_f.close()

        boms_for_enc = [
            ('utf-32',      (codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)),
            ('utf-16',      (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)),
            ('utf-8-sig',   (codecs.BOM_UTF8,)),
        ]

        for enc, boms in boms_for_enc:
            if any(subs_data.startswith(bom) for bom in boms):
                subs_encoding = enc
                print('SUBS: Detected encoding (bom):', enc)
                break
        else:
            chardet_ret = chardet.detect(subs_data)
            subs_encoding = chardet_ret['encoding']
            print('SUBS: Detected encoding (chardet):', chardet_ret)
    except:
        print('SUBS: Detecting encoding failed. Defaulting to utf-8')

    # Parse subs and generate json for frontend
    try:
        with open(sub_path, encoding=subs_encoding, errors='replace') as fp:
            subs = pysubs2.SSAFile.from_file(fp)
    except:
        mpv.show_text('Loading subtitle file "%s" failed.' % sub_path)
        return

    subs.sort()
    subs_list = []

    for s in subs:
        text = s.plaintext.strip()

        # Temporary to correct pysubs2 parsing mistakes
        if is_websub:
            text = text.split('\n\n')[0]

        if not skip_empty_subs or text.strip():
            sub_start = max(s.start + subs_delay, 0) // 10 * 10
            sub_end = max(s.end + subs_delay, 0) // 10 * 10
            subs_list.append( { 'text': text, 'start': sub_start, 'end': sub_end } )

    subs_json = json.dumps(subs_list)


    # Open or refresh frontend
    mpv.show_text('Opening in Browser...', 2.0)

    open_new_tab = False

    data_queues_lock.acquire()

    finalize_queues = data_queues

    if reuse_last_tab and len(data_queues) > 0:
        data_queues[-1].put('r')
        finalize_queues = finalize_queues[:-1]
        t = threading.Thread(target=tab_reload_timeout)
        t.start()
    else:
        open_new_tab = True

    for q in finalize_queues:
        q.put('q')

    data_queues_lock.release()

    if open_new_tab:
        open_webbrowser_new_tab()


def resync_subtitle(resync_sub_path, resync_reference_path, resync_reference_track):
    if ffmpeg is None:
        mpv.show_text('Subtitle syncing requires ffmpeg to be located in the plugin directory.')
        return

    # Support drag & drop subtitle files on some systems
    resync_sub_path = path_clean(resync_sub_path)

    mpv.show_text('Syncing subtitles to reference track. Please wait...', duration=150.0)    # Next osd message will close it

    path_ext_split = os.path.splitext(resync_sub_path)  # [path_without_extension, extension_with_dot]

    out_base_path = path_ext_split[0] + '-resynced'     # Out path without index or extension
    out_path = out_base_path + path_ext_split[1]
    
    # If the out path already exists count up until free file is found
    try_i = 1
    while os.path.exists(out_path):
        out_path = out_base_path + '-' + str(try_i) + path_ext_split[1]
        try_i += 1

    # Run actual syncing in thread
    def sync_thread_func():
        r = subprocess.run([ffsubsync, resync_reference_path, '-i', resync_sub_path, '-o', out_path, '--reftrack', resync_reference_track, '--ffmpeg-path', os.path.dirname(ffmpeg)])

        if r.returncode == 0:
            mpv.command('sub-add', out_path)
            mpv.show_text('Syncing finished.')
        else:
            mpv.show_text('Syncing failed.')
    
    t = threading.Thread(target=sync_thread_func)
    t.start()



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


def install_except_hooks():
    sys.excepthook = exception_hook

    if hasattr(threading, 'excepthook'):
        threading.excepthook = exception_hook_threads

    else:
        run_old = threading.Thread.run

        LegacyExceptHookArgs = collections.namedtuple('LegacyExceptHookArgs', 'exc_type exc_value exc_traceback thread')

        def run_new(*args, **kwargs):
            try:
                run_old(*args, **kwargs)
            except:
                exception_hook_threads(LegacyExceptHookArgs(*sys.exc_info(), None))

        threading.Thread.run = run_new


def find_executable(name, config_name=None):

    if config_name is None:
        config_name = name

    # Check if defined in config and exists
    if config_name in config:
        config_exe_path = config.get(config_name, config_name)
        if os.path.isfile(config_exe_path):
            return config_exe_path

    check_paths = [
        os.path.join(plugin_dir, name, name),
        os.path.join(plugin_dir, name),
    ]

    # On Windows also check for .exe files
    if platform.system() == 'Windows':
        for cp in check_paths.copy():
            check_paths.append(cp + '.exe')

    for cp in check_paths:
        if os.path.isfile(cp):
            return cp
    
    return shutil.which(name)   # Set to none when not found



def main():
    global log_file
    global mpv
    global host
    global port
    global reuse_last_tab
    global reuse_last_tab_timeout
    global webbrowser_name
    global ffmpeg
    global ffsubsync
    global rubysubs
    global mpv_external
    global skip_empty_subs
    global sub_font_name
    global sub_font_size
    global sub_bottom_margin
    global sub_outline_size
    global sub_shadow_offset
    global subtitle_export_timeout

    install_except_hooks()

    # Redirect stdout/stderr to log file if built for release
    if not dev_mode:
        print('Redirecting stout and stderr to log.txt...')
        log_file = open(plugin_dir + '/log.txt', 'w', encoding='utf8')
        sys.stdout = log_file
        sys.stderr = log_file

    print('ARGS:', sys.argv)

    # Check command line args
    if len(sys.argv) != 2 and len(sys.argv) != 3:
        print('ARGS: Usage: %s mpv-ipc-handle [config path]' % sys.argv[0])
        return

    config_path = plugin_dir + '/migaku_mpv.cfg'
    if len(sys.argv) >= 3:
        config_path = sys.argv[2]

    # Clear/create temp dir
    shutil.rmtree(tmp_dir, ignore_errors=True)
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
        try_port_min = int(config.get('port', '2222'))
    except:
        try_port_min = 2222
    try:
        try_port_max = int(config.get('port_max', '2233'))
        if try_port_max < try_port_min:
            try_port_max = try_port_min
    except:
        try_port_max = 2233
    try_ports = range(try_port_min, try_port_max+1)
    

    reuse_last_tab = config.get('reuse_last_tab', 'yes').lower() == 'yes'
    try:
        reuse_last_tab_timeout = float(config.get('reuse_last_tab_timeout', '1.5'))
    except:
        reuse_last_tab_timeout = 1.5

    browser = config.get('browser', 'default')
    if browser.lower() == 'default':
        browser = None
    else:
        browser = browser_support.expand_browser_name(browser)
    print('BRS:', browser)
    webbrowser_name = browser

    anki_exporter.tmp_dir = tmp_dir

    anki_w = None
    anki_h = None
    try:
        anki_w = int(config.get('anki_image_width', 'auto'))
    except:
        pass
    try:
        anki_h = int(config.get('anki_image_height', 'auto'))
    except:
        pass
    anki_exporter.image_width = anki_w
    anki_exporter.image_height = anki_h

    anki_exporter.image_format = config.get('anki_image_format', 'jpg')
    anki_exporter.audio_format = config.get('anki_audio_format', 'wav')

    print('ANKI:', vars(anki_exporter))


    ffmpeg = find_executable('ffmpeg')
    ffsubsync = find_executable('ffsubsync')
    rubysubs = find_executable('rubysubs')
    mpv_external = find_executable('mpv', 'mpv_external')
    print('EXES:', { 'ffmpeg': ffmpeg, 'ffsubsync': ffsubsync, 'rubysubs': rubysubs, 'mpv_external': mpv_external })

    skip_empty_subs = config.get('skip_empty_subs', 'yes').lower() == 'yes'
    try:
        subtitle_export_timeout = float(config.get('subtitle_export_timeout', '0'))
    except:
        subtitle_export_timeout = 0

    sub_font_name = config.get('sub_font_name', 'Noto Sans CJK JP')
    sub_font_size = int(config.get('sub_font_size', '55'))
    sub_bottom_margin = int(config.get('sub_bottom_margin', '22'))
    sub_outline_size = int(config.get('sub_outline_size', '3'))
    sub_shadow_offset = int(config.get('sub_shadow_offset', '0'))

    # Init mpv IPC
    mpv = MpvIpc(sys.argv[1])

    # Setup server
    server = HttpServer(host, try_ports)
    server.set_get_file_server('/', plugin_dir + '/migaku_mpv.html')
    for path in ['/icons/migakufavicon.png', '/icons/anki.png', '/icons/bigsearch.png']:
        server.set_get_file_server(path, plugin_dir + path)
    server.set_get_handler('/subs', get_handler_subs)
    server.set_get_handler('/data', get_handler_data)
    server.set_post_handler('/anki', post_handler_anki)
    server.set_post_handler('/mpv_control', post_handler_mpv_control)
    server.set_post_handler('/set_subs', post_handler_set_subs)
    server.open()

    port = server.port

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
                    load_and_open_migaku(*event_args[2:9+1])
                elif cmd == 'resync':
                    resync_subtitle(*event_args[2:4+1])

    # Close server
    server.close()
    stop_get_data_handlers()

    # Close mpv IPC
    mpv.close()

    # Rempve temp dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
