import sys
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO


__all__ = ["make_environ", "make_start_response"]

def make_environ(request, server_address):
    environ = {
        'wsgi.version': (1, 0),
        'wsgi.url_scheme': request.scheme or 'http',
        'wsgi.input': request.rfile,
        'wsgi.errors': sys.stderr,
        'wsgi.multithread': False,
        'wsgi.multiprocess': True,
        'wsgi.run_once': False,
        'SCRIPT_NAME': '',
        'PATH_INFO': request.path,
        'SERVER_NAME': server_address[0],
        'SERVER_PORT': server_address[1],
        'REQUEST_METHOD': request.method,
        'SERVER_PROTOCOL': "HTTP/%s.%s" % tuple(request.version),
    }

    if request.querystring:
        environ['QUERY_STRING'] = request.querystring

    if 'content-length' in request.headers:
        length = int(request.headers['content-length'])
        environ['CONTENT_LENGTH'] = length
        environ['wsgi.input']._length = length

    if 'content-type' in request.headers:
        environ['CONTENT_TYPE'] = request.headers['content-type']

    for name, value in request.headers.items():
        environ['HTTP_%s' % name.replace('-', '_').title()] = value

    return environ

def make_start_response():
    collector = {'prefix': StringIO.StringIO()}

    def start_response(status, headers, exc_info=None):
        if exc_info and collector.get('headers_sent'):
            raise exc_info[0], exc_info[1], exc_info[2]
        else:
            exc_info = None
        collector['status'] = status
        collector['headers'] = headers
        return write

    def write(data):
        collector['prefix'].write(data)
        collector['headers_sent'] = True

    return start_response, collector
