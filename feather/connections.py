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

    a few more utility methods can be overridden as well:

    start_timer() will be called when the connection is no longer in a state
    where it is between a request and a response

    cancel_timer() will then be called once a request is received. (the
    start/cancel timer hook was required in feather.http.HTTPConnection to
    implement keep-alive)

    cleanup() to do more connection cleanup. be sure to call the super method
    for this one, as TCPConnection.cleanup is needed
    """

    # set this attribute to something that implements handle()
    request_handler = requests.RequestHandler

    def __init__(self, sock, client_address, server_address,
            killable_registry):
        self.socket = sock
        self.fileno = sock.fileno()
        self.client_address = client_address
        self.server_address = server_address
        self.killable_registry = killable_registry
        self.closing = False
        self.closed = False

    # be sure and implement this in concrete subclasses
    def get_request(self):
        "override to return an object representing a single request"
        raise NotImplementedError()

    @property
    def killable(self):
        return self.fileno in self.killable_registry

    @killable.setter
    def killable(self, value):
        if value:
            self.killable_registry[self.fileno] = self
        else:
            self.killable_registry.pop(self.fileno, None)

    def start_timer(self):
        "override me. will be called to set a keep-alive (or similar) timer"
        pass

    def cancel_timer(self):
        "override me. will be called to cancel the timer from start_timer()"
        pass

    def serve_all(self):
        self.start_timer()

        while not self.closing:
            request = self.get_request()
            self.cancel_timer()

            if request is None:
                # indicates connection terminated by client
                break

            handler = self.request_handler(
                    self.client_address, self.server_address, self)

            # the return value from handler.handle may be a generator or
            # other lazy iterator to allow for large responses that send
            # in chunks and don't block the entire server the whole time
            response = handler.handle(request)
            first = True
            for chunk in response:
                if not first:
                    greenhouse.pause()
                self.socket.sendall(chunk)
                first = False

            self.start_timer()
            greenhouse.pause()

        self.cleanup()

    def cleanup(self):
        "override (call the super method) to add to connection cleanup"
        self.cancel_timer()
        self.killable = False
        self.socket.close()
        self.closed = True
