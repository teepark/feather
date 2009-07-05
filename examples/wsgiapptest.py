#!/usr/bin/env python

import cgi
import logging
import sys

import feather


HOST = ""
PORT = 9000

def xss_scrub(data):
    return data.replace("&", "&amp;").replace(">", "&gt;").replace("<", "&lt;")

def wsgiapp(environ, start_response):
    if environ['PATH_INFO'] == '/':
        response = '''
            <form action=/handler method=POST>
                <input type=text name=data1 /><br>
                <input type=text name=data2 />
                <input type=submit />
            </form>
        '''
        start_response("200 OK", [('content-type', 'text/html'),
                                  ('content-length', str(len(response)))])
        return [response]
    elif environ['PATH_INFO'] == '/handler' and \
            environ['REQUEST_METHOD'] == 'POST':
        data = dict(cgi.parse_qsl(environ['wsgi.input'].read()))
        data['data1'] = xss_scrub(data['data1'])
        data['data2'] = xss_scrub(data['data2'])
        response = '''<p>data1 was %(data1)s</p>
            <p>data2 was %(data2)s</p>
            <a href="/">back</a>
        ''' % data
        start_response("200 OK", [('content-type', 'text/html'),
                                  ('content-length', str(len(response)))])
        return [response]
    start_response("404 NOT FOUND", [('content-type', 'text/html')])
    return ['nuh-uh']


if __name__ == "__main__":
    if '-v' in sys.argv:
        logging.getLogger("feather").setLevel(logging.DEBUG)
    feather.serve_wsgi_app((HOST, PORT), wsgiapp)
