from BaseHTTPServer import BaseHTTPRequestHandler
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO


responsecodes = BaseHTTPRequestHandler.responses

class HTTPParseError(Exception):
    pass

class HttpRequest(object):
    def __init__(self, props=None, **kwargs):
        self.__dict__.update(props or {})
        self.__dict__.update(kwargs)

class _Parser(BaseHTTPRequestHandler):
    def __init__(self):
        pass

    def parsestring(self, request_txt):
        return self.parse(StringIO(request_txt))

    def parse(self, infile):
        self.rfile = infile
        self.raw_requestline = self.rfile.readline()

        self.parse_request()

        return HttpRequest(
            close_connection=self.close_connection,
            method=self.command,
            path=self.path,
            version=self.request_version,
            headers=self.headers,
            infile=self.rfile,
        )

    def send_error(self, code, message=None):
        raise HTTPParseError(code, message)

def parsestring(request):
    return _Parser().parsestring(request)

def parse(request):
    return _Parser().parse(request)
