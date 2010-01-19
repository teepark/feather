#!/usr/bin/env python

import optparse

import feather.wsgi


DEFAULT_HOST = ""
DEFAULT_PORT = 9000

def wsgiapp(environ, start_response):
    start_response("200, OK", [
            ('content-type', 'text/plain'),
            ('content-length', '13')])
    return ["Hello, World!"]


if __name__ == "__main__":
    parser = optparse.OptionParser()
    parser.add_option("-H", "--host", default=DEFAULT_HOST)
    parser.add_option("-P", "--port", type="int", default=DEFAULT_PORT)

    options, args = parser.parse_args()
    feather.wsgi.serve((options.host, options.port), wsgiapp, debug=True, timeout=1)
