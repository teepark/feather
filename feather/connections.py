from feather import requests


__all__ = ["TCPConnection"]


class TCPConnection(object):

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

    def serve_all(self):
        while not self.closing:
            request = self.get_request()

            handler = self.request_handler(request, client_address,
                    server_address, self)

            # the return value from handler.handler may be a generator or
            # other lazy iterator, to allow for large responses that send
            # in chunks and don't block the entire server the whole time
            response = handler.handle(request)
            for chunk in response:
                self.socket.sendall(chunk)
                # even if there is only one chunk (probably the usual case),
                # we yield once between responses on the same connection
                greenhouse.pause()

        self.cleanup()

    def cleanup(self):
        self.killable = False
        self.socket.close()
        self.closed = True
