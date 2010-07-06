__all__ = ["RequestHandler"]


class RequestHandler(object):
    """an abstract request handler.

    provide a handle() method and a handle_error() method.

    handle() accepts a request object (as returned by
    YourTCPConnectionSubclass.get_request). handle_error() accepts the standard
    3 exception arguments (type, exception, traceback).

    both handle() and handle_error should return a two-tuple of response
    iterable and a metadata object. the metadata object can be anything, it
    will just be passed as the metadata parameter to
    YourTCPConectionSubclass.log_access()

    if the response iterable is longer than 1 string, the connection will pause
    between sending each chunk to allow other coroutines to run.

    it is perfectly allowable to have the response iterable be a generator or
    other lazy iterator so as to not block the whole server while you generate
    a long response and hold the entire thing in memory.

    each string in the response iterable will be sent in a separate
    socket.sendall() call, so keep that in mind -- for instance you may want to
    chunk up large files yourself rather than just returning the file object,
    since the lines may be shorter than a good chunk size.
    """
    def __init__(self, client_address, server_address, connection):
        self.client_address = client_address
        self.server_address = server_address
        self.connection = connection
        self.server = connection.server

    def handle(self, request):
        raise NotImplementedError()

    def handle_error(self, klass, exc, tb):
        raise NotImplementedError()
