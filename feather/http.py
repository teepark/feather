import BaseHTTPServer
import httplib
import socket
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
    * rfile
    '''
    __slots__ = [
            "method",
            "version",
            "scheme",
            "host",
            "path",
            "querystring",
            "headers",
            "rfile"]

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
        return map(lambda l: l + "\n", text.split("\n"))


class HTTPRequestHandler(requests.RequestHandler):
    pass


class HTTPConnection(connections.TCPConnection):

    header_class = httplib.HTTPMessage

    def get_request(self):
        rfile = InputFile(self.socket, 0)
        request_line = rfile.readline()

        if request_line in ('\n', '\r\n'):
            request_line = rfile.readline()

        if not request_line:
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

        headers = self.header_class(rfile)

        return HTTPRequest(
                method=method,
                version=version,
                scheme=url.scheme,
                host=url.netloc,
                path=url.path,
                querystring=url.query,
                fragment=url.fragment,
                headers=headers,
                rfile=rfile)
