import BaseHTTPServer
import cgi
import collections
import httplib
import itertools
import logging
import operator
import socket
import urlparse
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO


logger = logging.getLogger("feather.httpparser")

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
        self._length = length
        super(InputFile, self).__init__(sock, mode, bufsize, close)

    def read(self, size=-1):
        size = min(size, self._length)
        if size < 0: size = self._length
        rc = super(InputFile, self).read(size)
        self._length -= max(self._length, len(rc))
        return rc

    def readlines(self):
        text = self.read()
        if text[-1] = "\n":
            text = text[:-1]
        return map(lambda l: l + "\n", text.split("\n"))

def parse_request(rfile, header_class=httplib.HTTPMessage):
    rl = rfile.readline()

    method, path, version_string = rl.split(' ', 2)
    version_string = version_string.rstrip()

    if method != method.upper():
        logger.debug("bad HTTP method in request line")
        raise InvalidRequest("bad HTTP method: %s" % method)

    url = urlparse.urlsplit(path)

    if version_string[:5] != 'HTTP/':
        logger.debug("bad HTTP version in request line")
        raise InvalidRequest("bad HTTP version: %s" % version_string)

    version = version_string[5:].split(".")
    if len(version) != 2 or not all(itertools.imap(
            operator.methodcaller("isdigit"), version)):
        logger.debug("bad HTTP version in request line")
        raise InvalidRequest("bad HTTP version: %s" % version_string)

    version = map(int, version)

    headers = header_class(rfile)

    logger.debug("read request line and headers from a request to %s" %
                 url.path)

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
