import datetime
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

    @property
    def killable(self):
        return self.fileno in self.server.killable

    @killable.setter
    def killable(self, value):
        if value:
            self.server.killable[self.fileno] = self
        else:
            self.server.killable.pop(self.fileno, None)

    def setup(self):
        "override to do extra setup for new connections"
        pass

    def serve_all(self):
        self.setup()

        while not self.closing:
            request = self.get_request()

            if request is None:
                # indicates timeout or connection terminated by client
                break

            handler = self.request_handler(
                    self.client_address, self.server.address, self)

            access_time = datetime.datetime.now()
            sent = 0

            try:
                code, head_len, response = handler.handle(request)
            except:
                klass, exc, tb = sys.exc_info()
                self.log_error(klass, exc, tb)
                code, head_len, response = handler.handle_error(klass, exc, tb)
                klass, exc, tb = None, None, None

            # the return value from handler.handle may be a generator or
            # other lazy iterator to allow for large responses that send
            # in chunks and don't block the entire server the whole time
            first = True
            for chunk in response:
                if not first:
                    greenhouse.pause()
                self.socket.sendall(chunk)
                sent += len(chunk)
                first = False

            self.log_access(access_time, request, code, sent - head_len)

            if not self.closing:
                greenhouse.pause()

        self.cleanup()

    def cleanup(self):
        "override (call the super method) to add to connection cleanup"
        self.killable = False
        self.socket.close()
        self.socket._sock.close() #HACK until greenhouse gets a proper solution
        self.closed = True
        self.server.descriptor_counter.release()

    def log_access(self, access_time, request, code, body_len):
        pass

    def log_error(self, klass, exc, tb):
        pass
