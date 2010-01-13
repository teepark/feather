#!/usr/bin/env python

import optparse

import feather


DEFAULT_HOST = ""
DEFAULT_PORT = 9000

connected = {}


class ChatClientConnection(object):
    def __init__(self, sock, address, server):
        self.sock = sock
        self.client_address = address
        self.server = server

    def send_msg(self, msg):
        if not self.sock._closed:
            self.sock.sendall(msg)

    def broadcast(self, msg):
        for conn in connected.values():
            if conn is not self:
                conn.send_msg(msg)

    def serve_all_requests(self):
        sock = self.sock

        sock.sendall("enter your name up to 20 characters\r\n")
        name = sock.recv(8192).rstrip("\r\n")

        if len(name) > 20:
            sock.close()
            return

        connected[name] = self
        self.broadcast("*** %s has entered\r\n" % name)

        sockfile = sock.makefile('r')
        while 1:
            line = sockfile.readline().rstrip("\r\n")

            if not line:
                connected.pop(name)
                break

            self.broadcast("%s: %s\r\n" % (name, line))

        self.broadcast("*** %s has left the building\r\n" % name)


class ChatServer(feather.server.Server):
    connection_handler = ChatClientConnection
    worker_count = 1 # no forking - all connections must share RAM


if __name__ == "__main__":
    parser = optparse.OptionParser()
    parser.add_option("-H", "--host", default=DEFAULT_HOST)
    parser.add_option("-P", "--port", type="int", default=DEFAULT_PORT)

    options, args = parser.parse_args()
    ChatServer((options.host, options.port)).serve()
