import BaseHTTPServer
import httplib
import itertools
import socket
import traceback
import urlparse

from feather import connections, requests


__all__ = ["InputFile", "HTTPError", "HTTPRequest", "HTTPRequestHandler",
        "HTTPConnection"]

responses = BaseHTTPServer.BaseHTTPRequestHandler.responses


class HTTPRequest(object):
    '''a straightforward attribute holder that supports the following names:
    * method
    * version
    * scheme
    * host
    * path
    * querystring
    * headers
    * content
    '''
    __slots__ = [
            "method",
            "version",
            "scheme",
            "host",
            "path",
            "querystring",
            "headers",
            "content"]

    def __init__(self, **kwargs):
        for name in self.__slots__:
            setattr(self, name, kwargs.get(name, None))


class HTTPError(Exception):
    def __init__(self, code=500, body=None, headers=None):
        self.code = code
        self.body = body
        self.headers = headers or []


class InputFile(socket._fileobject):
    "a file object that doesn't attempt to read past a specified length"

    def __init__(self, sock, length, mode='rb', bufsize=-1, close=False):
        self.length = length
        super(InputFile, self).__init__(sock, mode, bufsize, close)

    def read(self, size=-1):
        size = min(size, self.length)
        if size < 0: size = self.length
        rc = super(InputFile, self).read(size)
        self.length -= max(self.length, len(rc))
        return rc

    def readlines(self):
        text = self.read()
        if text[-1] == "\n":
            text = text[:-1]
        return map(self._line_mapper, text.split("\n"))

    @staticmethod
    def _line_mapper(l):
        return l + '\n'


def _strip_first(iterable):
    iterator = iter(iterable)
    try:
        first = iterator.next()
    except StopIteration:
        first = ''
    return first, iterator


class HTTPRequestHandler(requests.RequestHandler):

    TRACEBACK_DEBUG = False

    def __init__(self, *args, **kwargs):
        super(HTTPRequestHandler, self).__init__(*args, **kwargs)
        self._headers = []
        self._code = self._body = None

    def set_code(self, code):
        self._code = code

    def set_body(self, body):
        self._body = body

    def add_header(self, name, value):
        self._headers.append((name, value))

    def add_headers(self, headers):
        self._headers.extend(headers)

    def handle(self, request):
        handler = getattr(self, "do_%s" % request.method, None)

        try:
            if not handler:
                raise HTTPError(405) # Method Not Allowed

            handler(request)

        except HTTPError, error:
            self.translate_http_error(error)

        except NotImplemented:
            self.translate_http_error(HTTPError(405))

        except:
            if self.TRACEBACK_DEBUG:
                self.set_body(traceback.format_exc())
            self.set_code(500)
            self.add_header('Content-type', 'text/plain')

        return self.format_response()

    def _have_header(self, header):
        header = header.lower()
        for name, value in self._headers:
            if name.lower() == header:
                return True
        return False

    def translate_http_error(error):
        self.set_code(error.code)
        if not self._have_header('content-type'):
            self.add_header('Content-type', 'text/plain')
        self.add_headers(error.headers)
        self.set_body(error.body)

    def format_response(self):
        http_version = '.'.join(map(str, self.connection.http_version))
        code = getattr(self._code, 200)
        status, long_status = responses[code]
        if self._body is None:
            self._body = long_status

        # we MUST either send a Content-Length or close the connection
        if not self._have_header('content-length'):
            if isinstance(self._body, str):
                self.add_header('Content-Length', len(self._body))
            else:
                self.add_header('Connection', 'close')
                self.connection.closing = True

        headers = '\r\n'.join('%s: %s' % pair for pair in self._headers)

        head = 'HTTP/%s %d %s\r\n%s\r\n\r\n' % (
                http_version, code, status, headers)

        if isinstance(self._body, str):
            return head + self._body

        # we don't want the headers to go in their own send() call, so prefix
        # them to the first item in the body iterable, then re-prefix that item
        iterator = iter(self._body)
        try:
            first_chunk = iterator.next()
        except StopIteration:
            first_chunk = ''
        return itertools.chain([head + first_chunk], iterator)

    def do_GET(self, request):
        raise NotImplementedError()

    do_POST = do_PUT = do_HEAD = do_DELETE = do_GET


class HTTPConnection(connections.TCPConnection):

    request_handler = HTTPRequestHandler

    # header-parsing class from the stdlib
    header_class = httplib.HTTPMessage

    # we don't support changing the HTTP version inside a connection,
    # because that's just silliness
    http_version = (1, 1)

    keepalive_timeout = 30

    def get_request(self):
        self.killable = False
        content = InputFile(self.socket, 0)
        request_line = content.readline()

        if request_line in ('\n', '\r\n'):
            request_line = content.readline()

        if not request_line:
            self.killable = True
            return None

        method, path, version_string = request_line.split(' ', 2)
        version_string = version_string.rstrip()

        if not method.isalpha() or method != method.upper():
            raise HTTPError(400, "bad HTTP method: %r" % method)

        url = urlparse.urlsplit(path)

        if version_string[:5] != 'HTTP/':
            raise HTTPError(400, "bad HTTP version: %r" % version_string)

        try:
            version = tuple(int(v) for v in version_string[5:].split("."))
        except ValueError:
            raise HTTPError(400, "bad HTTP version: %r" % version_string)

        headers = self.header_class(content)

        return HTTPRequest(
                method=method,
                version=version,
                scheme=url.scheme,
                host=url.netloc,
                path=url.path,
                querystring=url.query,
                fragment=url.fragment,
                headers=headers,
                content=content)
