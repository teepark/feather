import BaseHTTPServer
import httplib
import itertools
import logging
import socket
import ssl
import time
import traceback
import urlparse

from feather import connections, requests, servers
import greenhouse


__all__ = ["SizeBoundFile", "HTTPError", "HTTPRequest", "HTTPRequestHandler",
        "HTTPConnection"]

responses = BaseHTTPServer.BaseHTTPRequestHandler.responses


class HTTPRequest(object):
    '''a straightforward attribute holder that supports the following names:

    method
        GET, POST, PUT, HEAD, DELETE, etc.

    version
        the HTTP version as a tuple of integers. generally (1, 0) or (1, 1)

    scheme
        string of either "http" or "https"

    host
        the server host - tried to get first from Host: header, then from host
        in the path, then (if the path was relative) takes it from the server

    path
        the accessed path from the first line of the request

    querystring
        the full querystring from the path

    fragment
        the fragment portion of the url

    headers
        an object representing the HTTP headers. unless overridden,
        HTTPConnection provides an instance of httplib.HTTPMessage

    content
        a file-like object from which you can read[line[s]]() the body of the
        request

    remote_ip
        the IP address from which the connection has been made. if a reverse
        proxy is in use this won't correspond to the client's real IP address,
        but the proxy is probably adding a header indicating that.
    '''
    __slots__ = [
            "request_line",
            "method",
            "version",
            "scheme",
            "host",
            "path",
            "querystring",
            "fragment",
            "headers",
            "content",
            "remote_ip"]

    def __init__(self, **kwargs):
        for name in self.__slots__:
            setattr(self, name, kwargs.get(name, None))


class HTTPError(Exception):
    """raise this in an HTTPRequestHandler instance/subclass to bail out and
    send an error response
    """
    def __init__(self, code=500, body=None, headers=None):
        self.code = code
        self.body = body
        self.headers = headers or []


class SizeBoundFile(greenhouse.io.sockets.SocketFile):
    """a file object that doesn't attempt to read past a specified length.

    unless overridden, HTTPConnection uses this as request.content
    """
    def __init__(self, sock, length, mode='rb', bufsize=-1):
        self.length = length
        self._ignore_length = False
        self.collected = 0
        super(SizeBoundFile, self).__init__(sock, mode, bufsize)

    def _reset_collected(self):
        self.collected = len(self._rbuf.getvalue())

    def _read_chunk(self, size):
        if self._ignore_length:
            return super(SizeBoundFile, self)._read_chunk(size)

        # make the self.length+1st byte behave like EOF
        size = max(min(self.length - self.collected, size), 0)
        if size:
            data = super(SizeBoundFile, self)._read_chunk(size)
        else:
            data = ''
        self.collected += len(data)
        return data


class HTTPRequestHandler(requests.RequestHandler):
    """the main application entry-point, this class handles a single request

    subclass this and provide do_METHOD methods for every HTTP method you wish
    to support (do_GET and do_POST is a good place to start).

    do_* methods should set response data with HTTPRequestHandler methods
    set_code, set_body, add_header, add_headers.
    """
    traceback_body = False

    def __init__(self, *args, **kwargs):
        super(HTTPRequestHandler, self).__init__(*args, **kwargs)
        self._headers = []
        self._code = self._body = None

    def set_code(self, code):
        '''set the integer HTTP response code

        200 for successful, also the default
        '''
        self._code = code

    def set_body(self, body):
        '''set the value of the body of the HTTP response

        the argument may be either a string or an iterable of strings. in the
        latter case it may be a generator or other lazy iterator to allow a
        long response to be generated and sent gradually without blocking the
        whole server process.
        '''
        self._body = body

    def add_header(self, name, value):
        'add a single header to those queued for the HTTP response'
        self._headers.append((name, value))

    def add_headers(self, headers):
        'add multiple (name, value) pairs to the queued HTTP response headers'
        self._headers.extend(headers)

    def has_header(self, header, required_value=None):
        '''indicate whether one or more headers with name `header` are queued

        with `required_value`, further limit the search to the provided value
        '''
        header = header.lower()
        for name, value in self._headers:
            if (name.lower() == header
                    and (required_value is None
                        or value.lower() == required_value.lower())):
                return True
        return False

    def pop_header(self, header):
        'remove and return all headers with name `header`'
        header = header.lower()
        removed, offset = [], 0
        for index, (name, value) in enumerate(self._headers[:]):
            if name.lower() == header:
                removed.append(self._headers.pop(index - offset))
                offset += 1
        return removed

    def _translate_http_error(self, error):
        self.set_code(error.code)
        self.add_headers(error.headers)
        self.pop_header('content-type')
        self.add_header('Content-Type', 'text/plain')
        self.set_body(error.body)

    def _format_response(self):
        http_version = '.'.join(map(str, self.connection.http_version))
        code = self._code or 200
        status, long_status = responses[code]
        if self._body is None:
            self._body = long_status

        closed = self.has_header('connection', 'close')

        # any time the connection is about to be closed, send the header
        if self.connection.closing and not closed:
            self.add_header('Connection', 'close')
            closed = True

        # we MUST send a Content-Length, Transfer-Encoding 'chunked',
        # or close the connection
        if not self.has_header('content-length') \
                and not self.has_header('transfer-encoding', 'chunked'):
            if isinstance(self._body, str):
                self.add_header('Content-Length', str(len(self._body)))
            else:
                if not closed:
                    closed = True
                    self.add_header('Connection', 'close')
                self.connection.closing = True

        if not self.connection.keepalive_timeout and not closed:
            self.add_header('Connection', 'close')

        headers = '\r\n'.join('%s: %s' % (k, v.replace('\n', '\n '))
                for k, v in self._headers)

        head = 'HTTP/%s %d %s\r\n%s\r\n\r\n' % (
                http_version, code, status, headers)

        if isinstance(self._body, str):
            return ((head + self._body,), (code, len(head)))

        # we don't want the headers to go in their own send() call, so prefix
        # them to the first item in the body iterable, then re-prefix that item
        iterator = iter(self._body)
        try:
            first_chunk = iterator.next()
        except StopIteration:
            first_chunk = ''
        return (itertools.chain([head + first_chunk], iterator),
            (code, len(head)))

    def handle(self, request):
        handler = getattr(self, "do_%s" % request.method, None)

        try:
            if handler is None or handler(request) is NotImplemented:
                raise HTTPError(405) # Method Not Allowed

        except HTTPError, error:
            self._translate_http_error(error)

        except NotImplementedError:
            self._translate_http_error(HTTPError(405))

        return self._format_response()

    def handle_error(self, klass, exc, tb):
        if self.traceback_body:
            self.set_body(traceback.format_exception(klass, exc, tb))
        self.set_code(500)
        self.add_header('Content-Type', 'text/plain')
        return self._format_response()


class HTTPConnection(connections.TCPConnection):
    """TCPConnection that speaks HTTP

    the main point of this class is to implement get_request so that it parses
    an HTTP request from the socket so the request_handler's handle() method
    receives an instance of HTTPRequest.

    there is not much overriding to be done at this level, but there are a few
    attributes that might be useful to change:

    request_handler
        this must be your HTTPRequestHandler subclass

    keepalive_timeout
        time in seconds before an inactive connection is closed. set to 0 to
        disable keepalive entirely

    http_version
        HTTP version number for responses as a tuple of ints. default is (1, 1)

    header_class
        callable that accepts a file-like object and returns a representation
        of the HTTP headers which will be used as request.headers. must not
        read more input than necessary. the default of httplib.HTTPMessage is a
        good one
    """
    request_handler = HTTPRequestHandler

    # header-parsing class from the stdlib
    header_class = httplib.HTTPMessage

    # we don't support changing the HTTP version inside a connection
    http_version = (1, 1)

    keepalive_timeout = 30

    def __init__(self, *args, **kwargs):
        super(HTTPConnection, self).__init__(*args, **kwargs)
        if self.keepalive_timeout:
            self.socket.settimeout(self.keepalive_timeout)

    def get_request(self):
        content = SizeBoundFile(self.socket, 0)
        content._ignore_length = True
        try:
            request_line = content.readline()
        except socket.timeout:
            return None

        if request_line in ('\n', '\r\n'):
            try:
                request_line = content.readline()
            except socket.timeout:
                return None

        if not request_line:
            return None

        try:
            method, path, version_string = request_line.split(' ', 2)
        except ValueError:
            return None
        version_string = version_string.rstrip()

        if not method.isalpha() or method != method.upper():
            return None

        url = urlparse.urlsplit(path)

        if version_string[:5] != 'HTTP/':
            return None

        try:
            version = tuple(int(v) for v in version_string[5:].split("."))
        except ValueError:
            return None

        headers = self.header_class(content)
        content._ignore_length = False
        content._reset_collected()

        if version < (1, 1):
            self.closing = True
        else:
            for name, val in headers.items():
                if name.lower() == 'connection' and val.lower() == 'close':
                    self.closing = True
                    break

        scheme = url.scheme or "http"
        host = headers.get('host') or url.netloc or self.server.host

        if 'content-length' in headers:
            content.length = int(headers['content-length'])

        return HTTPRequest(
                request_line=request_line,
                method=method,
                version=version,
                scheme=scheme,
                host=host,
                path=url.path,
                querystring=url.query,
                fragment=url.fragment,
                headers=headers,
                content=content,
                remote_ip=self.client_address[0])

    @staticmethod
    def format_datetime(dt):
        month = {
            "01": "Jan",
            "02": "Feb",
            "03": "Mar",
            "04": "Apr",
            "05": "May",
            "06": "Jun",
            "07": "Jul",
            "08": "Aug",
            "09": "Sep",
            "10": "Oct",
            "11": "Nov",
            "12": "Dec",
            }[dt.strftime("%m")]
        tz = -time.altzone / 36
        neg = tz < 0
        tz = str(-tz).zfill(4)
        if neg:
            tz = "-%s" % tz
        return dt.strftime("%d/%%s/%Y:%H:%M:%S %%s") % (month, tz)

    def _get_browser_ip(self, request):
        if 'x-forwarded-for' in request.headers:
            return request.headers['x-forwarded-for'].strip()
        if 'x-real-ip' in request.headers:
            return request.headers['x-real-ip'].strip()
        return request.remote_ip

    def log_access(self, access_time, request, metadata, sent):
        code, head_len = metadata
        body_len = sent - head_len
        self.server.access_log.info(self.server.access_log_format % {
            'ip': self._get_browser_ip(request),
            'time': self.format_datetime(access_time),
            'request_line': request.request_line.rstrip(),
            'resp_code': code,
            'body_len': body_len,
            'referer': request.headers.get("http-referer", "-"),
            'user_agent': request.headers.get("user-agent", "-"),
        })

    def log_error(self, klass, exc, tb):
        self.server.error_log.error(
                "".join(traceback.format_exception(klass, exc, tb)))


class HTTPServer(servers.TCPServer):
    """
    """
    connection_handler = HTTPConnection

    access_log_format = '%(ip)s - - [%(time)s] "%(request_line)s" ' + \
            '%(resp_code)d %(body_len)d "%(referer)s" "%(user_agent)s"'

    def __init__(self, *args, **kwargs):
        super(HTTPServer, self).__init__(*args, **kwargs)
        self.access_log = logging.getLogger("feather.http.access")
        self.error_log = logging.getLogger("feather.http.errors")


class HTTPSServer(HTTPServer):
    def __init__(self, *args, **kwargs):
        self.certfile = kwargs.pop('certfile', None)
        self.keyfile = kwargs.pop('keyfile', None)
        self.cert_reqs = kwargs.pop('cert_reqs', ssl.CERT_NONE)
        self.ssl_version = kwargs.pop('ssl_version', ssl.PROTOCOL_TLSv1)
        self.ca_certs = kwargs.pop('ca_certs', None)
        self.ciphers = kwargs.pop('ciphers', None)

        super(HTTPSServer, self).__init__(*args, **kwargs)

        self.access_log = logging.getLogger("feather.https.access")
        self.error_log = logging.getLogger("feather.https.errors")

    def init_socket(self):
        super(HTTPSServer, self).init_socket()
        self.socket = greenhouse.wrap_socket(self.socket,
                keyfile=self.keyfile,
                certfile=self.certfile,
                server_side=True,
                cert_reqs=self.cert_reqs,
                ssl_version=self.ssl_version,
                ca_certs=self.ca_certs,
                do_handshake_on_connect=True,
                suppress_ragged_eofs=True,
                ciphers=self.ciphers)
