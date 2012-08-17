#!/usr/bin/env python

import logging
import optparse
import os
import sys
import traceback

import feather.wsgi, feather.monitor
import greenhouse

greenhouse.global_exception_handler(traceback.print_exception)
logging.getLogger("feather.https").addHandler(logging.StreamHandler())

here = os.path.dirname(os.path.abspath(__file__))


DEFAULT_HOST = ""
DEFAULT_PORT = 9000

def wsgiapp(environ, start_response):
    start_response("200 OK", [
            ('content-type', 'text/plain'),
            ('content-length', '13')])
    return ["Hello, World!"]


if __name__ == "__main__":
    parser = optparse.OptionParser()
    parser.add_option("-H", "--host", default=DEFAULT_HOST)
    parser.add_option("-P", "--port", type="int", default=DEFAULT_PORT)

    options, args = parser.parse_args()
    feather.wsgi.serve((options.host, options.port), wsgiapp,
            https=True, traceback_body=True, keepalive_timeout=5,
            worker_count=1, keyfile=os.path.join(here, "testkey.pem"),
            certfile=os.path.join(here, "testcert.pem"))
