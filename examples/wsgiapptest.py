#!/usr/bin/env python

import cgi

from feather.server import Server, HTTPConnectionHandler, \
        HTTPWSGIRequestHandler


def wsgiapp(environ, start_response):
    if environ['PATH_INFO'] == '/':
        start_response("200 OK", [('content-type', 'text/html')])
        return ['''
            <form action=/handler method=POST>
                <input type=text name=data1 /><br>
                <input type=text name=data2 />
                <input type=submit />
            </form>
        ''']
    elif environ['PATH_INFO'] == '/handler' and \
            environ['REQUEST_METHOD'] == 'POST':
        data = environ['wsgi.input'].read()
        start_response(200, [('content-type', 'text/plain')])
        return ['''
            data1 was %(data1)s
            data2 was %(data2)s
        ''' % dict(cgi.parse_qsl(data))]
    start_response(404, [('content-type', 'text/html')])
    return ['nuh-uh']


if __name__ == "__main__":
    class RequestHandler(HTTPWSGIRequestHandler):
        wsgiapp = staticmethod(wsgiapp)

    class ConnectionHandler(HTTPConnectionHandler):
        request_handler = RequestHandler

    server = Server(("", 9000))
    server.connection_handler = ConnectionHandler
    server.serve()
