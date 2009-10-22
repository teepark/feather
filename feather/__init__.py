import logging
import sys

import feather.server


def serve_wsgi_app(address, app):
    class RequestHandler(feather.server.HTTPWSGIRequestHandler):
        wsgiapp = staticmethod(app)

    class ConnectionHandler(feather.server.HTTPConnectionHandler):
        request_handler = RequestHandler

    server = feather.server.Server(address)
    server.connection_handler = ConnectionHandler
    server.serve()

logger = logging.getLogger("feather")
logger.addHandler(logging.StreamHandler(sys.stdout))
logger.setLevel(logging.INFO)
