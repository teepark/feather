from __future__ import with_statement

import os
import unittest
import urllib2

from feather import http
import greenhouse
from base import FeatherTest


class HTTPServerTests(FeatherTest):

    class HelloWorldHandler(http.HTTPRequestHandler):
        def do_GET(self, request):
            self.set_code(200)
            self.add_header('Content-Length', '13')
            self.add_header('X-Foo', 'bar')
            self.set_body('Hello, World!')

    def test_basic(self):
        greenhouse.emulation.patch()

        with self.http_server(self.HelloWorldHandler, port=4545):
            self.assertEqual(
                    urllib2.urlopen("http://localhost:4545/").read(),
                    "Hello, World!")

        self.assertRaises(
                urllib2.URLError,
                urllib2.urlopen,
                "http://localhost:4545/")

    def test_headers(self):
        greenhouse.emulation.patch()

        with self.http_server(self.HelloWorldHandler, port=4545):
            response = urllib2.urlopen("http://localhost:4545/")
            self.assertEqual(response.headers['content-length'], '13')
            self.assertEqual(response.headers['X-Foo'], 'bar')

    def test_keepalive(self):
        with self.http_server(self.HelloWorldHandler, port=6767):
            sock = greenhouse.Socket()
            sock.connect(("", 6767))

            sock.send("GET / HTTP/1.1\r\nHost: localhost:6767\r\n\r\n")
            response = sock.recv(8192)
            self.assertEqual(response.split("\r\n\r\n")[1], "Hello, World!")

            sock.send("GET / HTTP/1.1\r\nHost: localhost:6767\r\n\r\n")
            response = sock.recv(8192)
            self.assertEqual(response.split("\r\n\r\n")[1], "Hello, World!")

    def test_no_keepalive_without_content_length(self):
        class Handler(http.HTTPRequestHandler):
            def do_GET(self, request):
                self.set_code(200)
                self.set_body(['Hello, World!'])

        with self.http_server(Handler, port=9989):
            sock = greenhouse.Socket()
            sock.connect(("", 9989))

            sock.send("GET / HTTP/1.1\r\nHost: localhost:6767\r\n\r\n")
            response = sock.recv(8192)
            self.assertEqual(response.split("\r\n\r\n")[1], "Hello, World!")

            sock.send("GET / HTTP/1.1\r\nHost: localhost:6767\r\n\r\n")
            sock.settimeout(0.1)
            response = sock.recv(8192)
            self.assertEqual(response, "")


class FakeSocket(object):
    def __init__(self, starting_data=None):
        self.data = starting_data or ""
        self._readable = greenhouse.Event()
        if starting_data:
            self._readable.set()
        self._fileno = os.pipe()[0]

    def recv(self, amount, flags=None):
        if not self.data:
            self._readable.wait()

        if amount >= len(self.data):
            self._readable.clear()

        return_val = self.data[:amount]
        self.data = self.data[amount:]
        return return_val

    def send(self, data):
        if data:
            self._readable.set()
        self.data += data

    def fileno(self):
        return self._fileno

    def settimeout(self, *args):
        pass

    def gettimeout(self):
        return None


class SizeBoundFileTests(FeatherTest):

    def test_basic_read(self):
        sock = FakeSocket("foobar")
        rfile = http.SizeBoundFile(sock, 0)
        rfile._ignore_length = True
        self.assertEqual(rfile.read(6), "foobar")

    def test_basic_readline(self):
        sock = FakeSocket("foobar\r\n")
        rfile = http.SizeBoundFile(sock, 0)
        rfile._ignore_length = True
        self.assertEqual(rfile.readline(), "foobar\r\n")

    def test_limited_read_all(self):
        sock = FakeSocket("foobarspameggs")
        rfile = http.SizeBoundFile(sock, 10)
        self.assertEqual(rfile.read(), "foobarspam")

    def test_limited_readline(self):
        data = '''foo
bar
spam
eggs
'''
        sock = FakeSocket(data)
        rfile = http.SizeBoundFile(sock, 9)
        self.assertEqual("".join(rfile.readlines()), data[:9])

    def test_limited_readlines(self):
        data = '''foo
bar
spam
eggs
'''
        sock = FakeSocket(data)
        rfile = http.SizeBoundFile(sock, len(data))
        self.assertEqual("".join(rfile.readlines()), data)

    def test_chunked_read(self):
        sock = FakeSocket("foobar")
        rfile = http.SizeBoundFile(sock, 10)

        @greenhouse.schedule
        def f():
            sock.send("spameggs")

        self.assertEqual(rfile.read(), "foobarspam")

    def test_chunked_readline(self):
        sock = FakeSocket("foobar")
        rfile = http.SizeBoundFile(sock, 100)

        @greenhouse.schedule
        def f():
            sock.send("spam")
            greenhouse.pause()
            sock.send("\r\n")

        self.assertEqual(rfile.readline(), "foobarspam\r\n")

    def test_chunked_readlines(self):
        data = '''foo
bar
spam
eggs
'''
        sock = FakeSocket()

        @greenhouse.schedule
        def f():
            for line in data.split("\n"):
                greenhouse.pause()
                sock.send(line + "\n")

        rfile = http.SizeBoundFile(sock, len(data))
        self.assertEqual("".join(rfile.readlines()), data)


class HTTP10ParsingTests(FeatherTest):
    def parse(self, text, client_addr=("127.0.0.1", 8989)):
        sock = FakeSocket(text.replace("\n", "\r\n"))
        server = type('Server', (), {'killable': {}})()
        conn = http.HTTPConnection(sock, client_addr, server)
        request = conn.get_request()
        return request, conn.closing

    def test_simple_get(self):
        request, closing = self.parse('''GET / HTTP/1.0
Host: localhost

''')

        self.assertEqual(request.request_line, "GET / HTTP/1.0\r\n")
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.version, (1, 0))
        self.assertEqual(request.scheme, "http")
        self.assertEqual(request.host, "localhost")
        self.assertEqual(request.path, "/")
        self.assertEqual(request.querystring, "")
        self.assertEqual(request.fragment, "")
        self.assertEqual(request.headers.items(), [('host', 'localhost')])
        assert closing

    def test_different_headers(self):
        request, closing = self.parse('''GET / HTTP/1.0
Host: localhost
User-Agent: crappy-test/1.0

''')

        self.assertEqual(
                sorted(request.headers.items()),
                [('host', 'localhost'), ('user-agent', 'crappy-test/1.0')])

    def test_repeated_header(self):
        request, closing = self.parse('''GET / HTTP/1.0
Host: localhost
X-FooBar: spam
X-FooBar: eggs
X-FooBar: meatloaf

''')

        self.assertEqual(request.headers['X-FooBar'], 'spam, eggs, meatloaf')
        self.assertEqual(
                request.headers.getallmatchingheaders('x-foobar'),
                ["X-FooBar: spam\r\n", "X-FooBar: eggs\r\n",
                    "X-FooBar: meatloaf\r\n"])


if __name__ == '__main__':
    unittest.main()
