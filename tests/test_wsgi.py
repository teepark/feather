import unittest
import urllib2

import greenhouse
from base import FeatherTest


class WSGIServerTests(FeatherTest):
    def hello_world(self, environ, start_response):
        start_response("200 OK", [('Content-Length', '13')])
        return ["Hello, World!"]

    def hello_world_no_content_length(self, environ, start_response):
        start_response("200 OK", [])
        return ["Hello, World!"]

    def test_basic(self):
        with self.wsgi_server(self.hello_world, port=8989):
            self.assertEqual(
                    urllib2.urlopen("http://localhost:8989/").read(),
                    "Hello, World!")

        self.assertRaises(
                urllib2.URLError,
                urllib2.urlopen,
                "http://localhost:8989/")

    def test_write(self):
        def app(environ, start_response):
            write = start_response("200, OK", [])
            write("written\n")
            return ["returned"]

        with self.wsgi_server(app, port=8888):
            self.assertEqual(
                    urllib2.urlopen("http://localhost:8888/").read(),
                    "written\nreturned")

    def test_headers(self):
        def app(environ, start_response):
            start_response("200 OK", [
                ("X-Foo", "bar"),
                ("X-Spam", "eggs"),
            ])
            return [""]

        with self.wsgi_server(app, port=9999):
            response = urllib2.urlopen("http://localhost:9999/")
            self.assertEqual(response.headers['X-Foo'], 'bar')
            self.assertEqual(response.headers['X-Spam'], 'eggs')

    def test_keepalive(self):
        with self.wsgi_server(self.hello_world, port=5678):
            sock = greenhouse.Socket()
            sock.connect(("", 5678))

            sock.send("GET / HTTP/1.1\r\nHost: localhost:5678\r\n\r\n")
            response = sock.recv(8192)
            self.assertEqual(response.split("\r\n\r\n")[1], "Hello, World!")

            sock.send("GET / HTTP/1.1\r\nHost: localhost:5678\r\n\r\n")
            response = sock.recv(8192)
            self.assertEqual(response.split("\r\n\r\n")[1], "Hello, World!")

    def test_no_keepalive_without_content_length(self):
        with self.wsgi_server(self.hello_world_no_content_length, port=2345):
            sock = greenhouse.Socket()
            sock.connect(("", 2345))

            sock.send("GET / HTTP/1.1\r\nHost: localhost:5678\r\n\r\n")
            response = sock.recv(8192)
            self.assertEqual(response.split("\r\n\r\n")[1], "Hello, World!")

            sock.send("GET / HTTP/1.1\r\nHost: localhost:5678\r\n\r\n")
            response = sock.recv(8192)
            self.assertEqual(response, "")


if __name__ == '__main__':
    unittest.main()
