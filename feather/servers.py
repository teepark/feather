import errno
import random
import socket

import greenhouse
from feather import connections


__all__ = ["BaseServer", "TCPServer", "UDPServer"]


class BaseServer(object):
    address_family = socket.AF_INET
    socket_protocol = socket.SOL_IP

    def __init__(self, address):
        self.address = address
        self.is_setup = False
        self.shutting_down = False

    def init_socket(self):
        self.socket = greenhouse.Socket(
                self.address_family,
                self.socket_type,
                self.socket_protocol)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def setup(self):
        if not hasattr(self, "socket"):
            self.init_socket()
        self.socket.bind(self.address)
        self.is_setup = True

    def serve(self):
        raise NotImplementedError()

    @property
    def host(self):
        return self.address[0]

    @host.setter
    def host(self, value):
        self.address[0] = value

    @property
    def port(self):
        return self.address[1]

    @port.setter
    def port(self, value):
        self.address[1] = value


class TCPServer(BaseServer):
    socket_type = socket.SOCK_STREAM
    listen_backlog = 128
    connection_handler = connections.TCPConnection

    def __init__(self, *args, **kwargs):
        super(TCPServer, self).__init__(*args, **kwargs)
        self.killable = {}

    def setup(self):
        super(TCPServer, self).setup()
        self.socket.listen(self.listen_backlog)

    def connection(self, client_sock, client_address):
        handler = self.connection_handler(
                client_sock,
                client_address,
                self.address,
                self.killable)
        greenhouse.schedule(handler.serve_all)

    def cleanup_disconnected(self):
        pass

    def serve(self):
        if not self.is_setup:
            self.setup()

        try:
            while not self.shutting_down:
                self.cleanup_disconnected()

                try:
                    self.connection(*(self.socket.accept()))
                except socket.error, error:
                    if err.args[0] == errno.EMFILE:
                        if not self.killable:
                            greenhouse.pause_for(0.01)
                            continue

                        fd = random.choice(self.killable.keys())
                        unlucky = self.killable.pop(fd)
                        unlucky.socket.close()
                        unlucky.closed = True
                    elif err.args[0] == errno.ENFILE:
                        greenhouse.pause_for(0.01)
                    else:
                        raise
        finally:
            self.socket.close()


class UDPServer(BaseServer):
    socket_type = socket.SOCK_DGRAM

    def serve(self):
        if not self.is_setup:
            self.setup()
        ##XXX: finish this
