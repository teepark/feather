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
        with self.http_server(self.HelloWorldHandler, port=4545):
            self.assertEqual(
                    urllib2.urlopen("http://localhost:4545/").read(),
                    "Hello, World!")

        self.assertRaises(
                urllib2.URLError,
                urllib2.urlopen,
                "http://localhost:4545/")

    def test_headers(self):
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
            response = sock.recv(8192)
            self.assertEqual(response, "")



if __name__ == '__main__':
    unittest.main()
