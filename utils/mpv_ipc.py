import socket
import os
import json
import time
import threading


class MpvIpc_Base():

    def __init__(self, ipc_handle_path):
        self.port_open(ipc_handle_path)

    def close(self):
        self.port_close()

    # Starts a loop that yields received json data
    # Exits when mpv closes the pipe or any errors occur
    def listen(self):
        data = b''
        try:
            while True:
                new_data = self.port_read(1024)
                if new_data == b'':
                    break
                data += new_data
                if data[-1] != 10:
                    continue       
                utf8_data = data.decode('utf-8', errors='ignore')
                for line in utf8_data.split('\n'):
                    if line != '':
                        loaded_data = json.loads(line)
                        yield loaded_data
                data = b''

        except (OSError, BrokenPipeError, EOFError):
            pass

    def send_json_txt(self, data):
        self.port_send(data.encode('utf-8') + b'\n')

    def send_json(self, data):
        self.send_json_txt(json.dumps(data))

    def command(self, command, *args):
        send_args = [command] + list(args)
        self.send_json({ 'command': send_args })

    def show_text(self, text, duration=4.0):
        millis = int(duration * 1000)
        self.command('show-text', text, millis)

    # Plattform specific

    def port_open(self, ipc_handle_path):
        raise NotImplementedError

    def port_close(self):
        raise NotImplementedError

    def port_send(self, data):
        raise NotImplementedError

    def port_read(self, readlen):
        return self.socket.recv(readlen)


class MpvIpc_Unix(MpvIpc_Base):
    
    def port_open(self, ipc_handle_path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.connect(ipc_handle_path)

    def port_close(self):
        try:
            self.socket.shutdown(socket.SHUT_WR)
            self.socket.close()
        except:
            pass

    def port_send(self, data):
        self.socket.send(data)

    def port_read(self, readlen):
        return self.socket.recv(readlen)


class MpvIpc_Windows(MpvIpc_Base):

    def port_open(self, ipc_handle_path):
        import _winapi
        from multiprocessing.connection import PipeConnection

        ipc_handle_path = "\\\\.\\pipe\\" + ipc_handle_path

        for _ in range(10):
            try:
                pipe_handle = _winapi.CreateFile(
                    ipc_handle_path, _winapi.GENERIC_READ | _winapi.GENERIC_WRITE,
                    0, _winapi.NULL, _winapi.OPEN_EXISTING, _winapi.FILE_FLAG_OVERLAPPED, _winapi.NULL
                )
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise OSError('Opening pipe failed')

        self.socket = PipeConnection(pipe_handle)

    def port_close(self):
        self.socket.close()

    def port_send(self, data):
        self.socket.send_bytes(data)

    def port_read(self, readlen):
        return self.socket.recv_bytes(readlen)


if os.name == 'nt':
    MpvIpc = MpvIpc_Windows
else:
    MpvIpc = MpvIpc_Unix
