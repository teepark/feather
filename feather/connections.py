from feather import requests


__all__ = ["TCPConnection"]


class TCPConnection(object):

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

    def get_request(self):
        raise NotImplementedError()

    def serve_all(self):
        while not self.closing:
            request = self.get_request()
            handler = self.request_handler(request, client_address,
                    server_address, killable_registry)
            handler.handle(request)

        self.killable_registry.pop(self.fileno, None)
        self.socket.close()
        self.closed = True
