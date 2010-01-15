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
    pass


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

    head_string = '''HTTP/%(http_version)s %(code)d %(status)s
        %(headers)s

        '''.replace('\n', '\r\n').replace('\r\n        ', '\r\n')

    def format(self, code, status, headers, body_iterable):
        headers = '\r\n'.join('%s: %s' % pair for pair in headers)
        http_version = ".".join(map(str, self.connection.http_version))

        head = self.head_string % locals()

        # we don't want the headers to count as a separate chunk, so
        # prefix them to the first body chunk and rebuild the iterable
        first_chunk, body = _strip_first(body_iterable)
        return itertools.chain((head, first_chunk), body)

    def error(self, code):
        status, long_status = responses[code]
        body = (long_status,)
        raise HTTPError(code, status, [('content-type', 'text/plain')], body)

    def handle(self, request):
        handler = getattr(self, "do_%s" % request.method, None)

        try:
            if not handler:
                self.error(405) # Method Not Allowed

            return handler(request)

        except self.RespondingRightNow, response_error:
            return self.format(*(response_error.args))

        except NotImplementedError:
            self.error(405)

        except:
            status, long = responses[500]
            body_text = self.TRACEBACK_DEBUG and traceback.format_exc() or long
            return self.format(500, status, [('content-type', 'text/plain')],
                    (body_text,))

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
