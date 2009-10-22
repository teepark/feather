import errno
import itertools
import logging
import socket
import sys
import traceback
import urlparse

import feather.http
import feather.wsgitools
import greenhouse


__all__ = ["Server", "HTTPConnectionHandler", "HTTPWSGIRequestHandler"]

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
            logger.debug("close connection b/c no Content-Length in response")
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
        self.open = True

    def handle(self):
        logger.debug("greenlet with connection %d started" % id(self))
        while self.open:
            try:
                # create the file object expecting no body, when we parse the
                # request headers from it we will replace the expected body
                # length with the Content-Length header, if any
                rfile = feather.http.InputFile(self.sock, 0)
                request = feather.http.parse_request(rfile)
                logger.debug("got and parsed a request from connection %d" %
                             id(self))

                req_handler = self.request_handler(request, self.server, self)

                for chunk in req_handler.respond():
                    self.sock.sendall(chunk)

                connheader = request.headers.get('connection', '').lower()
                if connheader == 'close' or (tuple(request.version) < (1, 1)
                                             and connheader != 'keep-alive'):
                    if connheader == 'close':
                        logger.debug("closing connection - Connection: close")
                    else:
                        logger.debug("HTTP<1.1 and no Connection: keep-alive")
                    self.open = False
            except feather.http.HTTPError, err:
                logger.debug("sending an HTTP %d error response" % err.args[0])
                short, long = feather.http.responses[err.args[0]]
                self.sock.sendall("HTTP/1.0 %d %s\r\n"
                                  "Connection: close\r\n"
                                  "Content-Length: %d\r\n"
                                  "Content-Type: text/plain\r\n\r\n"
                                  "%s" %
                                  (err.args[0], short, len(long), long))
                self.open = False
            except:
                logger.debug("HTTP 500 error response from an exception:")
                logger.debug("".join("  %s" % line for line in
                        traceback.format_exception(*sys.exc_info())))
                self.open = False

        self.sock.close()

class Server(object):

    connection_handler = HTTPConnectionHandler

    address_family = socket.AF_INET
    socket_type = socket.SOCK_STREAM
    listen_backlog = 128

    def __init__(self, server_address):
        self.address = server_address
        self.is_setup = False
        self._serversock = greenhouse.Socket(self.address_family,
                self.socket_type)
        self._serversock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def setup(self):
        logger.info("binding listening socket to %r" % (self.address,))
        self._serversock.bind(self.address)
        self._serversock.listen(self.listen_backlog)
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
            except socket.error, err:
                if err.args[0] in (errno.EMFILE, errno.ENFILE):
                    # hit the limit of open file descriptors
                    logger.info("too many descriptors, closing a socket")
                    continue
                raise
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt caught, closing listen socket")
                self._serversock.close()
                sys.exit()
