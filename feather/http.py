import BaseHTTPServer
import cgi
import collections
import httplib
import itertools
import operator
import socket
import urlparse
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO


__all__ = ["HTTPRequest", "InputFile", "parse_request"]

responses = BaseHTTPServer.BaseHTTPRequestHandler.responses

class HTTPRequest(object):
    '''a simple dictionary proxy object, but some keys are expected by servers:

    method
    version
    scheme
    host
    path
    querystring
    headers
    rfile
    '''
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

class HTTPError(Exception): pass

class InputFile(socket._fileobject):
    "a file object that doesn't attempt to read past Content-Length"
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

def parse_request(rfile, header_class=httplib.HTTPMessage):
    rl = rfile.readline()
    if rl in ('\n', '\r\n'):
        rl = rfile.readline()
    if not rl:
        return None

    method, path, version_string = rl.split(' ', 2)
    version_string = version_string.rstrip()

    if method != method.upper() or not method.isalpha():
        raise HTTPError(400, "bad HTTP method: %s" % method)

    url = urlparse.urlsplit(path)

    if version_string[:5] != 'HTTP/':
        raise HTTPError(400, "bad HTTP version: %s" % version_string)

    try:
        version = map(int, version_string[5:].split("."))
    except ValueError:
        raise HTTPError(400, "bad HTTP version: %s" % version_string)

    headers = header_class(rfile)

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
