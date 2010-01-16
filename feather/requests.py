__all__ = ["RequestHandler"]


class RequestHandler(object):
    def __init__(self, client_address, server_address, connection):
        self.client_address = client_address
        self.server_address = server_address
        self._connection = connection

    def handle(self, request):
        raise NotImplementedError()
