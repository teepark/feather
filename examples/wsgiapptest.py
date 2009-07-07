#!/usr/bin/env python

import cgi
import logging
import optparse
import sys

import feather


DEFAULT_HOST = ""
DEFAULT_PORT = 9000

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
    elif environ['PATH_INFO'].startswith('/handler') and \
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
    start_response("404 NOT FOUND", [('content-type', 'text/html'),
                                     ('content-length', '6')])
    return ['nuh-uh']


if __name__ == "__main__":
    parser = optparse.OptionParser(add_help_option=False)
    parser.add_option("-v", "--verbose", action="store_true")
    parser.add_option("-p", "--port", type="int", default=DEFAULT_PORT)
    parser.add_option("-h", "--host", default=DEFAULT_HOST)

    options, args = parser.parse_args()
    if options.verbose:
        logging.getLogger("feather").setLevel(logging.DEBUG)
    feather.serve_wsgi_app((options.host, options.port), wsgiapp)
