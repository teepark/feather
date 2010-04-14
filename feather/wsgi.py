try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
import inspect

from feather import http
import greenhouse


__all__ = ["WSGIHTTPRequestHandler", "serve"]


# the hoops one has to jump through to let the 'wsgiapp'
# attribute be set on a class without it becoming a bound method
class _wsgiapp_callable(type):
    def __new__(metacls, name, bases, attrs):
        attrs['_wsgiapp_container'] = (attrs['wsgiapp'],)
        return super(_wsgiapp_callable, metacls).__new__(
                metacls, name, bases, attrs)


class WSGIHTTPRequestHandler(http.HTTPRequestHandler):
    """a fully implemented HTTPRequestHandler, ready to run a WSGI app.
    
    subclass and override the wsgiapp attribute to your wsgi application and
    you are off to the races.
    """
    __metaclass__ = _wsgiapp_callable

    wsgiapp = None

    def do_everything(self, request):
        environ = {
            'wsgi.version': (1, 0),
            'wsgi.url_scheme': request.scheme or 'http',
            'wsgi.input': request.content,
            'wsgi.errors': self.server.error_log_file,
            'wsgi.multithread': False,
            'wsgi.multiprocess': self.server.worker_count > 1,
            'wsgi.run_once': False,
            'SCRIPT_NAME': '',
            'PATH_INFO': request.path,
            'SERVER_NAME': self.server_address[0] or "localhost",
            'SERVER_PORT': str(self.server_address[1]),
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
            environ['HTTP_%s' % name.replace('-', '_').upper()] = value

        # the WSGI specification's handling of request headers sucks, so we're
        # going to extend the spec here and provide a useful representation
        environ['feather.headers'] = [tuple(h.rstrip("\r\n").split(":", 1))
                for h in request.headers.headers]

        collector = [StringIO(), False] # (write()en data, headers sent)

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

        body = self._wsgiapp_container[0](environ, start_response)
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
        raise AttributeError(name)


def serve(address,
        wsgiapp,
        keepalive_timeout=30,
        traceback_body=False,
        max_conns=None,
        worker_count=None,
        access_log=None,
        error_log=None):
    "shortcut function to serve a wsgi app on an address"
    app, keepalive, tbbody = wsgiapp, keepalive_timeout, traceback_body

    class RequestHandler(WSGIHTTPRequestHandler):
        wsgiapp = app
        traceback_body = tbbody

    class Connection(http.HTTPConnection):
        request_handler = RequestHandler
        keepalive_timeout = keepalive

    server = http.HTTPServer(address, access_log=access_log,
            error_log=error_log)
    server.connection_handler = Connection
    server.worker_count = worker_count or server.worker_count
    server.max_conns = max_conns or server.max_conns
    server.serve()
