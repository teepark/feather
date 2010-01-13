import contextlib
import errno
import itertools
import os
import random
import socket
import sys
import traceback
import urlparse

from feather import http, wsgitools
import greenhouse


__all__ = ["Server", "HTTPConnectionHandler", "HTTPWSGIRequestHandler"]

class HTTPWSGIRequestHandler(object):

    wsgiapp = None

    def __init__(self, request, server, connection_handler):
        self.request = request
        self.server = server
        self.connection_handler = connection_handler

    def respond(self):
        environ = wsgitools.make_environ(self.request, self.server.address)
        start_response, collector = wsgitools.make_start_response()

        try:
            result = self.wsgiapp(environ, start_response)
        except:
            raise http.HTTPError(500)

        for key, value in collector['headers']:
            if key.lower() == 'content-length':
                break
        else:
            # if we aren't sending a Content-Length, close the connection
            self.connection_handler.open = False

        # don't put the headers in their own send() call, so prepend
        # them to the first item yielded from the iterable
        result = itertools.chain([collector['prefix'].getvalue()], result)
        firstresult = iter(result).next()

        # after getting the first result from the response iterable,
        # the headers must have been made available
        head = "HTTP/1.1 %s\r\n%s\r\n\r\n" % (collector['status'],
                "\r\n".join("%s: %s" % pair for pair in collector['headers']))

        return itertools.chain([head + firstresult], result)

class HTTPConnectionHandler(object):

    request_handler = HTTPWSGIRequestHandler
    yield_length = 1048576 #1MB

    def __init__(self, sock, address, server):
        self.sock = sock
        self.client_address = address
        self.server = server
        self.open = True
        self.timer = None

    def cancel_timer(self):
        if self.timer:
            self.timer.cancel()
        self.timer = None

    def start_timer(self):
        self.timer = greenhouse.Timer(
                self.server.keepalive_timeout,
                self._timer_hit)

    def _timer_hit(self):
        self.open = False
        self.timer = None

    def send_chunks(self, response_iterable):
        length = 0
        for chunk in response_iterable:
            if not self.open:
                break
            self.sock.sendall(chunk)
            length += len(chunk)
            if length > self.yield_length:
                greenhouse.pause()
                length = 0

    @contextlib.contextmanager
    def no_timeout(self):
        self.cancel_timer()
        yield
        self.start_timer()

    def serve_one_request(self):
        sock = self.sock
        fd = sock.fileno()
        server = self.server

        try:
            # create the file object expecting no body. when we parse the
            # request headers from it we will replace the expected body length
            # with the Content-Length header, if any
            rfile = http.InputFile(sock, 0)
            request = http.parse_request(rfile)
            if not request:
                self.open = False
                return

            req_handler = self.request_handler(request, server, self)

            with contextlib.nested(self.no_timeout(), server.unclosable(self)):
                self.send_chunks(req_handler.respond())

            connheader = request.headers.get('connection', '').lower()
            if connheader == 'close' or (tuple(request.version) < (1, 1) and
                    connheader != 'keep-alive'):
                self.open = False
        except http.HTTPError, error:
            if not self.open:
                return
            short, long = http.responses[error.args[0]]
            sock.sendall("HTTP/1.0 %d %s\r\n"
                    "Connection: close\r\n"
                    "Content-Length: %d\r\n"
                    "Content-Type: text/plain\r\n\r\n"
                    "%s" %
                    (error.args[0], short, len(long), long))
            self.open = False
        except Exception, error:
            self.open = False

    def serve_all_requests(self):
        self.start_timer()

        while self.open:
            self.serve_one_request()

        self.cancel_timer()

        self.server.can_close.pop(self.sock.fileno(), None)
        self.sock.close()

class Server(object):

    connection_handler = HTTPConnectionHandler

    address_family = socket.AF_INET
    socket_type = socket.SOCK_STREAM
    listen_backlog = 128

    keepalive_timeout = 10

    worker_count = 5

    def __init__(self, server_address):
        self.address = server_address
        self.is_setup = False
        self._serversock = greenhouse.Socket(
                self.address_family,
                self.socket_type)
        self._serversock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.openconns = 0
        self.can_close = {}

    def setup(self):
        self._serversock.bind(self.address)
        self._serversock.listen(self.listen_backlog)
        self.is_setup = True

        for i in xrange(self.worker_count - 1):
            if not os.fork():
                # need a new epoll object in each child
                greenhouse.poller.set()
                break

    def serve(self):
        if not self.is_setup:
            self.setup()
        maxopenconns = None
        while 1:
            try:
                clientsock, clientaddr = self._serversock.accept()
                conn_handler = self.connection_handler(
                        clientsock, clientaddr, self)
                greenhouse.schedule(conn_handler.serve_all_requests)
                self.openconns += 1
            except socket.error, err:
                if err.args[0] == errno.EMFILE:
                    maxopenconns = self.openconns

                    # first, give handlers one last chance to close connections
                    greenhouse.pause()

                    # now force-close a socket that is only open for keep-alive
                    if self.openconns == maxopenconns and self.can_close:
                        fd = random.choice(self.can_close.keys())
                        sock, handler = self.can_close.pop(fd)
                        sock.close()
                        handler.open = False
                        self.openconns -= 1
                    continue

                if err.args[0] == errno.ENFILE:
                    greenhouse.pause_for(0.01)
                    continue

                raise
            except KeyboardInterrupt:
                self._serversock.close()
                #sys.exit()

    @contextlib.contextmanager
    def unclosable(self, conn_handler):
        sock = conn_handler.sock
        fd = sock.fileno()
        self.can_close.pop(fd, None)
        yield
        self.can_close[fd] = (sock, conn_handler)
