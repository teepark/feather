#!/usr/bin/env python
# vim: fileencoding=utf8:et:sta:ai:sw=4:ts=4:sts=4

import logging
import optparse
import os
import traceback

from feather import wsgi, monitor
import greenhouse

greenhouse.global_exception_handler(traceback.print_exception)
logging.getLogger("feather").addHandler(logging.StreamHandler())


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9000


def app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return ["Hello World, from %d!" % os.getpid()]


def main():
    parser = optparse.OptionParser()
    parser.add_option("-H", "--host", default=DEFAULT_HOST)
    parser.add_option("-P", "--port", type="int", default=DEFAULT_PORT)

    options, args = parser.parse_args()

    server = wsgi.server(
            (options.host, options.port),
            app,
            traceback_body=True,
            keepalive_timeout=1)

    mon = monitor.Monitor(server, 5)

    mon.serve()


if __name__ == '__main__':
    main()
