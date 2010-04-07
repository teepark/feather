__all__ = ["RequestHandler"]


class RequestHandler(object):
    """an abstract request handler.

    provide a handle() function that accepts a request object (as returned by
    YourTCPConnectionSubclass.get_request) and returns a two-tuple of response
    iterable and a metadata object. the metadata object can be anything, it
    will just be passed as the metadata parameter to connection.log_access()

    each string in the response iterable will be sent in a separate
    socket.sendall() call, so if it is short enough be sure it is of length 1.

    if the response iterable is longer than 1 string, the connection will pause
    between sending each chunk to allow other coroutines to run.

    it is perfectly allowable to have the response iterable be a generator or
    other lazy iterator so as to not block the whole server while you generate
    a long response and hold the entire thing in memory.
    """
    def __init__(self, client_address, server_address, connection):
        self.client_address = client_address
        self.server_address = server_address
        self.connection = connection
        self.server = connection.server

    def handle(self, request):
        raise NotImplementedError()
