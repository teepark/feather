#!/usr/bin/env python

import optparse

from feather import servers


DEFAULT_HOST = ""
DEFAULT_PORT = 9000


class EchoServer(servers.UDPServer):
    def handle_packet(self, data, address):
        self.sendto(data, address)


if __name__ == '__main__':
    parser = optparse.OptionParser()
    parser.add_option("-H", "--host", default=DEFAULT_HOST)
    parser.add_option("-P", "--port", type="int", default=DEFAULT_PORT)

    options, args = parser.parse_args()
    server = EchoServer((options.host, options.port))
    server.serve()
