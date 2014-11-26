#!/usr/bin/env python
# vim: fileencoding=utf8:et:sw=4:ts=8:sts=4

import logging
import os
import sys
import traceback

from feather import http, websocket
import greenhouse


HOST = "127.0.0.1"
PORT = 9000


class WebSocketHandler(websocket.WebSocketHandler):
    def allow(self, request):
        if request.path == '/ws':
            return 101, []
        return 404, []

    def handle(self, incoming_messages):
        for msg in incoming_messages:
            if isinstance(msg, str):
                msg = msg.decode('utf8')
            yield u'echo: %s' % (msg,)


class RequestHandler(http.HTTPRequestHandler):
    websocket_handler = WebSocketHandler

    def do_GET(self, request):
        self.set_code(200)
        self.add_header('content-type', 'text/html')
        self.set_body("""
<script type='text/javascript'>
var sock = new WebSocket('ws://localhost:9000/ws', []);
</script>
""")


class Connection(http.HTTPConnection):
    request_handler = RequestHandler


def main(env, argv):
    logging.getLogger().addHandler(logging.StreamHandler())
    greenhouse.global_exception_handler(traceback.print_exception)
    server = http.HTTPServer((HOST, PORT))
    server.connection_handler = Connection
    server.serve()
    return 0


if __name__ == '__main__':
    exit(main(os.environ, sys.argv))
