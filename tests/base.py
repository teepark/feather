import contextlib
import socket
import traceback
import unittest

from feather import http, wsgi
import greenhouse


greenhouse.add_exception_handler(traceback.print_exception)

GTL = greenhouse.Lock()


class FeatherTest(unittest.TestCase):
    def setUp(self):
        GTL.acquire()

        greenhouse.emulation.unpatch()

        greenhouse.scheduler.state.awoken_from_events.clear()
        greenhouse.scheduler.state.timed_paused.clear()
        greenhouse.scheduler.state.paused[:] = []
        greenhouse.scheduler.state.descriptormap.clear()
        greenhouse.scheduler.state.to_run.clear()

        greenhouse.poller.set()

    def tearDown(self):
        GTL.release()

    @contextlib.contextmanager
    def wsgi_server(self, app, bind_addr="127.0.0.1", port=9999):
        class RequestHandler(wsgi.WSGIHTTPRequestHandler):
            wsgiapp = app

        class Connection(http.HTTPConnection):
            request_handler = RequestHandler

        server = http.HTTPServer((bind_addr, port))
        server.connection_handler = Connection
        server.worker_count = 1
        greenhouse.schedule(server.serve)
        greenhouse.pause()

        yield server

        server.socket.shutdown(socket.SHUT_RDWR)
        greenhouse.pause()

    @contextlib.contextmanager
    def http_server(self, request_handler, bind_addr="127.0.0.1", port=9999):
        handler = request_handler

        class Connection(http.HTTPConnection):
            request_handler = handler

        server = http.HTTPServer((bind_addr, port))
        server.connection_handler = Connection
        server.worker_count = 1
        greenhouse.schedule(server.serve)
        greenhouse.pause()

        yield server

        server.socket.shutdown(socket.SHUT_RDWR)
        greenhouse.pause()
