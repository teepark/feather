import itertools
import socket
import sys
import urlparse

import http
import greenhouse


class Server(object):

    socket_family = socket.AF_INET
    socket_type = socket.SOCK_STREAM

    request_queue_size = 5

    def __init__(self, addr, handler_class):
        self.address = addr

        self.handler_class = handler_class
        self.handler = self.handler_class(self)

        self.socket = greenhouse.Socket(self.socket_family, self.socket_type)
        self.socket.bind(self.address)
        if self.socket_type is socket.SOCK_STREAM:
            self.socket.listen(self.request_queue_size)

    def serve_forever(self):
        while 1:
            try:
                client, addr = self.socket.accept()
                greenhouse.schedule(self.handle_request, args=(client, addr))
            except KeyboardInterrupt:
                self.socket.close()

    def handle_request(self, client, addr):
        sendback, terminal, data = self.handler.respond(client, addr)
        if sendback:
            for chunk in data:
                client.sendall(chunk)
                greenhouse.pause()
        if terminal:
            client.close()

class WSGIRequestHandler(object):
    def __init__(self, server, wsgiapp):
        self.server = server
        self.wsgiapp = wsgiapp

    def respond(self, clientsock, address):
        request = http.parse(clientsock.makefile('rb'))
        environ = self.make_environ(request)
        start_response, response = self.make_start_response()

        mainbody = self.wsgiapp(environ, start_response)

        response = "HTTP/1.1 %d %s\r\n%s\r\n\r\n" % (
            response['status'],
            http.responsecodes[response['status']][0],
            "\r\n".join("%s: %s" % (h[0].title(), h[1])
                    for h in response['headers'])
            ) + ''.join(response['written'])

        data = itertools.chain([response], mainbody)

        return True, request.close_connection, data

    def make_environ(self, request):
        parsedurl = urlparse.urlsplit(request.path)

        environ = {
            'wsgi.input': request.infile,
            'wsgi.version': (1, 0),
            'wsgi.url_scheme': parsedurl.scheme or 'http',
            'wsgi.errors': sys.stderr,
            'wsgi.multithread': False,
            'wsgi.multiprocess': True,
            'wsgi.run_once': False,
            'SCRIPT_NAME': '',
            'PATH_INFO': parsedurl.path,
            'SERVER_NAME': self.server.address[0],
            'SERVER_PORT': self.server.address[1],
            'REQUEST_METHOD': request.method,
            'SERVER_PROTOCOL': request.version,
        }

        if parsedurl.query:
            environ['QUERY_STRING'] = parsedurl.query

        if 'content-length' in request.headers:
            environ['CONTENT_LENGTH'] = request.headers['content-length']

        if 'content-type' in request.headers:
            environ['CONTENT_TYPE'] = request.headers['content-type']

        for name, value in request.headers.items():
            environ['HTTP_%s' % name.replace('-', '_').title()] = value

        return environ

    def make_start_response(self):
        response = {}

        def write(data):
            response['written'].append(data)

        def start_response(status, response_headers, exc_info=None):
            response['status'] = status
            response['headers'] = response_headers
            response['written'] = []
            return write

        return start_response, response


if __name__ == "__main__":
    def hello_world(environ, start_response):
        start_response(200, [("Content-type", "text/plain")])
        return ["Hello, World!"]

    def wsgi(server):
        return WSGIRequestHandler(server, hello_world)

    server = Server(("", 9000), wsgi)
    server.serve_forever()
