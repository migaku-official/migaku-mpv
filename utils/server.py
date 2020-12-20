import socket
import threading




class HttpResponse():

    STATUS_FOR_CODE = {
        100: 'Continue',
        101: 'Switching Protocols',
        200: 'OK',
        201: 'Created',
        202: 'Accepted',
        203: 'Non-Authoritative Information',
        204: 'No Content',
        205: 'Reset Content',
        206: 'Partial Content',
        300: 'Multiple Choices',
        301: 'Moved Permanently',
        302: 'Found',
        303: 'See Other',
        304: 'Not Modified',
        305: 'Use Proxy',
        307: 'Temporary Redirect',
        400: 'Bad Request',
        401: 'Unauthorized',
        402: 'Payment Required',
        403: 'Forbidden',
        404: 'Not Found',
        405: 'Method Not Allowed',
        406: 'Not Acceptable',
        407: 'Proxy Authentication Required',
        408: 'Request Time-out',
        409: 'Conflict',
        410: 'Gone',
        411: 'Length Required',
        412: 'Precondition Failed',
        413: 'Request Entity Too Large',
        414: 'Request-URI Too Large',
        415: 'Unsupported Media Type',
        416: 'Requested range not satisfiable',
        417: 'Expectation Failed',
        500: 'Internal Server Error',
        501: 'Not Implemented',
        502: 'Bad Gateway',
        503: 'Service Unavailable',
        504: 'Gateway Time-out',
        505: 'HTTP Version not supported',
    }


    def __init__(self, code=200, content=None, content_type=None, headers={}):

        self.code = code
        if code not in self.STATUS_FOR_CODE:
            raise ValueError

        self.content = content
        self.content_type = content_type
        self.headers = headers


    def header_text(self):
        ret = []

        ret.append('HTTP/1.1 %d %s' % (self.code, self.STATUS_FOR_CODE[self.code]))
    
        if self.content:
            ret.append('Content-Length: ' + str(len(self.content)))
        if self.content_type:
            ret.append('Content-Type: ' + self.content_type)

        for header_name in self.headers.keys():
            ret.append(header_name + ': ' + self.headers[header_name])

        return '\r\n'.join(ret) + '\r\n\r\n'


    def send(self, socket):

        socket.send(self.header_text().encode())
        if self.content:
            socket.send(self.content)



class HttpServer():

    def __init__(self, host, port):

        self.host = host
        self.port = port

        self.server_socket = None
        self.is_closing = False

        self.get_file_servers = {}
        self.get_handlers = {}
        self.post_handlers = {}


    def open(self):

        if self.server_socket is not None:
            return

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.server_socket.bind((self.host, self.port))

        self.server_socket.listen(5)

        self.is_closing = False
        self.listener_thread = threading.Thread(target=self.client_listener)
        self.listener_thread.start()        
        

    def close(self):

        if self.server_socket is None:
            return

        self.is_closing = True
        try:
            self.server_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.server_socket.close()
        self.listener_thread.join()
        self.server_socket = None


    def set_get_file_server(self, uri, serve_path):

        self.get_file_servers[uri] = serve_path


    def set_get_handler(self, uri, handler):

        self.get_handlers[uri] = handler

    
    def set_post_handler(self, uri, handler):

        self.post_handlers[uri] = handler


    def client_listener(self):

        while not self.is_closing:
            try:
                client_socket, client_address = self.server_socket.accept()
            except:
                continue

            handler_thread = threading.Thread(target=self.client_handler, args=(client_socket, client_address))
            handler_thread.start()


    def client_handler(self, socket, address):

        try:
            recv_data = socket.recv(1024).decode()
            header_line_end = recv_data.find('\r')
            header_line_segs = recv_data[:header_line_end].split()
            method = header_line_segs[0]
            uri = header_line_segs[1]
        except:
            socket.close()
            return

        if method == 'GET':
            serve_path = self.get_file_servers.get(uri)
            if serve_path:
                f = open(serve_path, 'rb')
                serve_content = f.read()
                f.close()
                r = HttpResponse(content=serve_content, content_type='text/html')
                r.send(socket)                
            else:
                handler = self.get_handlers.get(uri)
                if handler:
                    handler(socket)

        elif method == 'POST':
            handler = self.post_handlers.get(uri)
            if handler:
                contents = None

                header_end = recv_data.find('\r\n\r\n')

                if header_end >= 0:
                    i = recv_data.find('Content-Length:')
                    if i >= 0 and i < header_end:
                        j = recv_data.find('\r\n', i)
                        try:
                            contents_length = int(recv_data[i+16:j].strip())

                            if contents_length >= 0:
                                contents = recv_data[header_end+4:]

                            remaining_read_len = contents_length - 1024

                            while remaining_read_len > 0:
                                contents += socket.recv(1024).decode()
                                remaining_read_len -= 1024
                        except:
                            pass
            
                handler(socket, contents)

        socket.close()
