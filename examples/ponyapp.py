#!/usr/bin/env python

from feather.server import Server, WSGIRequestHandler
from paste.pony import make_pony


def helloworld(environ, start_response):
    start_response(200, [('content-type', 'text/plain')])
    return ["Hello, World!"]

wsgiapp = make_pony(helloworld, None) # 2nd arg just gets thrown away


if __name__ == "__main__":
    class RequestHandler(HTTPWSGIRequestHandler):
        wsgiapp = staticmethod(wsgiapp)

    class ConnectionHandler(HTTPConnectionHandler):
        request_handler = RequestHandler

    server = Server(("", 9000))
    server.connection_handler = ConnectionHandler
    server.setup()
    server.serve()
