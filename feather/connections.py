import datetime
import errno
import socket
import sys

from feather import requests
import greenhouse


__all__ = ["TCPConnection"]


class TCPConnection(object):
    """abstract class for handling a single TCP client connection

    to use, you must override get_request() and the request_handler attribute

    get_request() will need to return an object that represents a single
    request, which will be passed into the request handler's handle() method

    the request_handler attribute should be set to a concrete subclass of
    feather.requests.RequestHandler

    cleanup() can be overridden to do more connection cleanup. be sure to call
    the super method though, as TCPConnection.cleanup is needed

    setup() can similarly be overridden to do setup work for new connections.
    """

    # set this attribute to something that implements handle()
    request_handler = requests.RequestHandler

    def __init__(self, sock, client_address, server):
        self.socket = sock
        self.fileno = sock.fileno()
        self.client_address = client_address
        self.server = server
        self.closing = False
        self.closed = False

    # be sure and implement this in concrete subclasses
    def get_request(self):
        "override to return an object representing a single request"
        raise NotImplementedError()

    def _get_killable(self):
        return self.fileno in self.server.killable
    def _set_killable(self, value):
        if value:
            self.server.killable[self.fileno] = self
        else:
            self.server.killable.pop(self.fileno, None)
    killable = property(_get_killable, _set_killable)

    def setup(self):
        "override to do extra setup for new connections"
        pass

    def serve_all(self):
        self.setup()

        while not self.closing and not self.server.shutting_down:
            self.killable = True

            handler = self.request_handler(
                    self.client_address,
                    (self.server.name, self.server.port),
                    self)

            try:
                request = self.get_request()
            except Exception:
                klass, exc, tb = sys.exc_info()
                self.log_error(klass, exc, tb)
                response, metadata = handler.handle_error(klass, exc, tb)
                klass, exc, tb = None, None, None
            else:
                if request is None:
                    # indicates timeout or connection terminated by client
                    break

                access_time = datetime.datetime.now()

                try:
                    response, metadata = handler.handle(request)
                except Exception:
                    klass, exc, tb = sys.exc_info()
                    self.log_error(klass, exc, tb)
                    response, metadata = handler.handle_error(klass, exc, tb)
                    klass, exc, tb = None, None, None

            # the return value from handler.handle may be a generator or
            # other lazy iterator to allow for large responses that send
            # in chunks and don't block the entire server the whole time
            first = True
            sent = 0
            try:
                # this needs to be in a try block as well since the
                # handler.handle() above could have returned a generator, in
                # which case in iteration here we are re-entering app code
                for chunk in response:
                    if not first:
                        greenhouse.pause()
                    try:
                        self.socket.sendall(chunk)
                    except socket.error, exc:
                        if exc.args[0] == errno.EPIPE:
                            # client disconnected. how rude.
                            self.closing = True
                            break
                        raise
                    sent += len(chunk)
                    first = False
            except Exception:
                self.closing = True
                self.log_error(*sys.exc_info())
            else:
                self.log_access(access_time, request, metadata, sent)

            if not self.closing:
                greenhouse.pause()

        self.cleanup()

    def cleanup(self):
        "override (call the super method) to add to connection cleanup"
        self.killable = False
        self.socket.close()
        self.closed = True
        self.server.descriptor_counter.release()
        self.server.open_conns -= 1

    def log_access(self, access_time, request, metadata, sent):
        pass

    def log_error(self, klass, exc, tb):
        pass
