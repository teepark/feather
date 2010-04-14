#!/usr/bin/env python

import optparse
import traceback

from feather import servers, connections, requests
import greenhouse


DEFAULT_HOST = ""
DEFAULT_PORT = 9000

connected = {}

class RequestHandler(requests.RequestHandler):
    def handle(self, request):
        self.connection.broadcast("%s: %s" % (
                self.connection.username, request.rstrip('\r\n')))
        return [], None


class ConnectionHandler(connections.TCPConnection):
    request_handler = RequestHandler

    def __init__(self, *args, **kwargs):
        super(ConnectionHandler, self).__init__(*args, **kwargs)
        self.sockfile = self.socket.makefile('r')

    def get_request(self):
        request = self.sockfile.readline()
        if not request:
            self.closing = True
            return None
        return request

    def setup(self):
        super(ConnectionHandler, self).setup()

        self.socket.sendall("** input your name (20 chars or less):\r\n")
        name = self.sockfile.readline().rstrip('\r\n')

        if len(name) > 20:
            self.closing = True
            self.socket.sendall("** nope sucka, that's too long.\r\n")
        elif name in connected:
            self.closing = True
            self.socket.sendall("** sorry, name %s is taken.\r\n" % name)
        else:
            connected[name] = self
            self.username = name
            self.broadcast("** %s has entered the room." % name)

    def broadcast(self, msg):
        for username, connection in connected.items():
            if username != self.username:
                connection.socket.sendall(msg + "\r\n")

    def cleanup(self):
        if hasattr(self, "username"):
            self.broadcast("** %s has left the building." % self.username)
        self.sockfile.close()
        super(ConnectionHandler, self).cleanup()
        del connected[self.username]

    def log_error(self, klass, exc, tb):
        traceback.print_exception(klass, exc, tb)


class ChatServer(servers.TCPServer):
    worker_count = 1
    connection_handler = ConnectionHandler


if __name__ == "__main__":
    greenhouse.add_exception_handler(traceback.print_exception)
    parser = optparse.OptionParser()
    parser.add_option("-H", "--host", default=DEFAULT_HOST)
    parser.add_option("-P", "--port", type="int", default=DEFAULT_PORT)

    options, args = parser.parse_args()
    ChatServer((options.host, options.port)).serve()
