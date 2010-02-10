__all__ = ["RequestHandler"]


class RequestHandler(object):
    """an abstract request handler.

    provide a handle() function that accepts a request object (as returned by
    YourTCPConnectionSubclass.get_request) and returns an iterable of strings.
    each string in the iterable will be sent in a separate socket.sendall()
    call, so if it is short enough be sure it is of length 1.

    it is perfectly allowable to have the returned iterable be a generator or
    other lazy iterator so as to not block the whole server while you generate
    a long response.
    """
    def __init__(self, client_address, server_address, connection):
        self.client_address = client_address
        self.server_address = server_address
        self.connection = connection

    def handle(self, request):
        raise NotImplementedError()
