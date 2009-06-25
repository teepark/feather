#!/usr/bin/env python

import feather
from paste.pony import make_pony


HOST = ""
PORT = 9000

def helloworld(environ, start_response):
    start_response(200, [('content-type', 'text/plain')])
    return ["Hello, World!"]

wsgiapp = make_pony(helloworld, None) # 2nd arg just gets thrown away


if __name__ == "__main__":
    feather.serve_wsgi_app((HOST, PORT), wsgiapp)
