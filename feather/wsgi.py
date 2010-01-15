try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from feather import http, servers
import greenhouse


class WSGIRequestHandler(http.HTTPRequestHandler):

    wsgiapp = None

    def do_everything(self, request):
        environ = {
            'wsgi.version': (1, 0),
            'wsgi.url_scheme': request.scheme or 'http',
            'wsgi.input': request.content,
            'wsgi.errors': greenhouse.exception_file,
            'wsgi.multithread': False,
            'wsgi.multiprocess': True, #XXX: set this appropriately
            'wsgi.run_once': False,
            'SCRIPT_NAME': '',
            'PATH_INFO': request.path,
            'SERVER_NAME': self.server_address[0],
            'SERVER_PORT': self.server_address[1],
            'REQUEST_METHOD': request.method,
            'SERVER_PROTOCOL': "HTTP/%s.%s" % tuple(request.version),
        }

        if request.querystring:
            environ['QUERY_STRING'] = request.querystring

        if 'content-length' in request.headers:
            environ['CONTENT_LENGTH'] = int(request.headers['content-length'])

        if 'content-type' in request.headers:
            environ['CONTENT_TYPE'] = request.headers['content-type']

        for name, value in request.headers.items():
            environ['HTTP_%s' % name.replace('-', '_').title()] = value

        collector = (StringIO(), False) # (write()en data, headers sent)

        def write(data):
            collector[0].write(data)
            collector[1] = True

        def start_response(status, headers, exc_info=None):
            if exc_info and collector[1]:
                raise exc_info[0], exc_info[1], exc_info[2]
            else:
                exc_info = None

            for i, c in enumerate(status):
                if i and not status[:i].isdigit():
                    break
            self.set_code(int(status[:i - 1]))
            self.add_headers(headers)

            return write

        body = self.wsgiapp(environ, start_response)
        prefix = collector[0].getvalue()

        if prefix:
            body_iterable = iter(body)
            try:
                first_chunk = body_iterable.next()
            except StopIteration:
                first_chunk = ''
            body = itertools.chain((prefix + first_chunk,), body_iterable)

        self.set_body(body)

    do_GET = do_POST = do_PUT = do_HEAD = do_DELETE = do_everything

    def __getattr__(self, name):
        if name.startswith("do_"):
            return do_everything


def serve(address, app):
    class RequestHandler(WSGIRequestHandler):
        wsgiapp = app

    class Connection(http.HTTPConnection):
        request_handler = RequestHandler

    server = servers.TCPServer(address)
    server.connection_handler = Connection
    server.serve()
