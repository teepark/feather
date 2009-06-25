import itertools
import logging
import socket
import urlparse

import greenhouse
import feather.http
import feather.wsgitools

logger = logging.getLogger("feather.server")

class HTTPWSGIRequestHandler(object):

    wsgiapp = None

    def __init__(self, request, server, connection_handler):
        self.request = request
        self.server = server
        self.connection_handler = connection_handler

    def respond(self):
        environ = feather.wsgitools.make_environ(self.request,
                                                 self.server.address)
        start_response, collector = feather.wsgitools.make_start_response()

        try:
            result = self.wsgiapp(environ, start_response)
        except:
            raise feather.http.HTTPError(500)

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
        # the headers have to have been made available
        head = "HTTP/1.1 %s\r\n%s\r\n\r\n" % (collector['status'],
                "\r\n".join("%s: %s" % pair for pair in collector['headers']))

        return itertools.chain([head + firstresult], result)

class HTTPConnectionHandler(object):

    request_handler = HTTPWSGIRequestHandler

    def __init__(self, sock, address, server):
        self.sock = sock
        self.client_address = address
        self.server = server

    def handle(self):
        while 1:
            try:
                rfile = feather.http.InputFile(self.sock, 0)
                request = feather.http.parse_request(rfile)

                req_handler = self.request_handler(request, self.server, self)

                for chunk in req_handler.respond():
                    self.sock.sendall(chunk)

                connheader = request.headers.get('connection').lower()
                if connheader == 'close' or (request.version < (1, 1) and
                                             connheader != 'keep-alive'):
                    break
            except feather.http.HTTPError, err:
                short, long = feather.http.responses[err.args[0]]
                self.sock.sendall("HTTP/1.0 %d %s\r\n"
                                  "Connection: close\r\n"
                                  "Content-Length: %d\r\n"
                                  "Content-Type: text/plain\r\n\r\n"
                                  "%s" %
                                  (err.args[0], short, len(long), long))
                break
            except:
                break

        self.sock.close()

    def handle_one_request(self):
        request = feather.http.request(sock.makefile('rb'))

        for chnk in self.request_handler(request, self.server, self).respond():
            self.sock.sendall(chnk)

        connheader = request.headers.get('connection').lower()
        if connheader == 'close' or (request.version < (1, 1) and
                                     connheader != 'keep-alive'):
            self.open = False

class Server(object):

    connection_handler = HTTPConnectionHandler

    address_family = socket.AF_INET
    socket_type = socket.SOCK_STREAM
    request_queue_size = 5

    def __init__(self, server_address):
        self.address = server_address
        self.is_setup = False
        self._serversock = greenhouse.Socket(self.address_family,
                self.socket_type)

    def setup(self):
        logger.info("binding listening socket to %r" % (self.address,))
        self._serversock.bind(self.address)
        self._serversock.listen(self.request_queue_size)
        self.is_setup = True

    def serve(self):
        if not self.is_setup:
            self.setup()
        while 1:
            try:
                logger.debug("listening for a new connection")
                clientsock, clientaddr = self._serversock.accept()
                conn_handler = self.connection_handler(clientsock, clientaddr,
                                                       self)
                greenhouse.schedule(conn_handler.handle)
                logger.debug("passed off new connection %d to a new greenlet" %
                             id(conn_handler))
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt caught, closing listen socket")
                self._serversock.close()
                raise
