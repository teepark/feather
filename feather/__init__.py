import sys

import feather.server


def serve_wsgi_app(address, app):
    """serve a wsgi app on a particular (host, port) pair
    """
    class RequestHandler(feather.server.HTTPWSGIRequestHandler):
        wsgiapp = staticmethod(app)

    class ConnectionHandler(feather.server.HTTPConnectionHandler):
        request_handler = RequestHandler

    server = feather.server.Server(address)
    server.connection_handler = ConnectionHandler
    server.serve()
