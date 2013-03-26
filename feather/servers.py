import errno
import os
import socket
import subprocess

import greenhouse
from feather import connections, util


__all__ = ["BaseServer", "TCPServer", "UDPServer"]


class BaseServer(object):
    """purely abstract server class.

    subclass TCPServer or UDPServer instead (or just use them as they are).
    """
    address_family = socket.AF_INET
    socket_protocol = socket.SOL_IP
    worker_count = 1
    allow_reuse_address = True
    environ_fd_name = "FEATHER_LISTEN_FD"

    def __init__(self, address, hostname=None, daemonize=False):
        self.host, self.port = address
        self.name = hostname or self.host
        self.is_setup = False
        self.shutting_down = False
        self.ready = greenhouse.Event()
        self.daemonize = daemonize

    def init_socket(self):
        self.socket = greenhouse.Socket(
                self.address_family,
                self.socket_type,
                self.socket_protocol)
        if self.allow_reuse_address:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def pickup_environ_socket(self):
        fd = int(os.environ[self.environ_fd_name])
        self.socket = greenhouse.Socket(
                fromsock=socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM))

    def setup(self):
        self.pre_fork_setup()
        self.fork_children()
        self.post_fork_setup()
        self.is_setup = True

    def pre_fork_setup(self):
        if self.environ_fd_name in os.environ:
            self.pickup_environ_socket()
        else:
            if not hasattr(self, "socket"):
                self.init_socket()
            self.socket.bind((self.host, self.port))

    def post_fork_setup(self):
        pass

    def fork_children(self):
        for i in xrange(self.worker_count - 1):
            if not os.fork():
                # children will need their own epoll object
                greenhouse.reset_poller()
                break # no grandchildren

    def serve(self):
        raise NotImplementedError()


class TCPServer(BaseServer):
    """the master TCP server

    to use, create an instance with a (host, port) address pair, customize it
    by setting certain attributes, and then just call its serve() method.

    * connection_handler is an attribute that should be a subclass of
      TCPConnection that will handle individual client connections. each
      instance of the connection_handler (for each connection) will be run in
      its own coroutine.

    * worker_count is the number of processes to have run the server. it will
      fork worker_count - 1 children, as the original process itself acts as
      a worker. it defaults to 5, so if your application is utilizing
      module-global memory be sure to set it to 1.

    * listen_backlog is the number of connections to allow to queue up when the
      server can't accept them fast enough. its default is the maximum allowed
      by the system (socket.SOMAXCONN).

    the cleanup() method may also be overridden to add extra behavior at the
    server's exit
    """
    socket_type = socket.SOCK_STREAM
    listen_backlog = socket.SOMAXCONN
    connection_handler = connections.TCPConnection

    def __init__(self, *args, **kwargs):
        super(TCPServer, self).__init__(*args, **kwargs)
        self.done = greenhouse.Event()
        self.connections = greenhouse.Counter()

    def pre_fork_setup(self):
        super(TCPServer, self).pre_fork_setup()
        self.socket.listen(self.listen_backlog)

    def serve(self):
        """run the server at the provided address forever.

        this method will remove the calling greenlet (generally the main
        greenlet) from the scheduler, so don't expect anything else to run in
        the calling greenlet until the server has been shut down.
        """
        if self.daemonize and os.environ.get('DAEMON', None) != 'yes':
            os.environ['DAEMON'] = 'yes'
            util.background()

        if not self.is_setup:
            self.setup()

        self.ready.set()
        try:
            while not self.shutting_down:
                try:
                    client_sock, client_address = self.socket.accept()
                    handler = self.connection_handler(
                            client_sock,
                            client_address,
                            self)
                except socket.error, error:
                    if error.args[0] in (errno.ENFILE, errno.EMFILE):
                        # max open connections
                        greenhouse.pause_for(0.01)
                    elif error.args[0] == errno.EINVAL:
                        # server socket was shut down
                        break
                    elif error.args[0] == errno.EBADF:
                        # believe it or not, this is the graceful shutdown
                        # case. see the comments in shutdown() below
                        break
                    raise
                else:
                    # might be a long time before the next accept call returns
                    greenhouse.schedule(handler.serve_all)
                    del handler, client_sock
        except KeyboardInterrupt:
            pass
        finally:
            self._cleanup()

    def _cleanup(self):
        self.socket.close()

        self.cleanup()

        self.connections.wait()
        self.done.set()

    def cleanup(self):
        pass

    def shutdown(self):
        self.shutting_down = True

        # there's no good way to interrupt an accept() call without shutting
        # down the socket, and there may be sibling processes listening on the
        # same socket that we want to leave alone. so this cheats, using the
        # internals of greenhouse.io.Socket to bail out in only this process.

        # wake up the greenlet blocked on the accept() call
        self.socket._readable.set()

        # and also make sure the accept() call blows up with EBADF
        self.socket.close()


class UDPServer(BaseServer):
    socket_type = socket.SOCK_DGRAM
    max_packet_size = 8192

    def serve(self):
        if self.daemonize and os.environ.get('DAEMON', None) != 'yes':
            os.environ['DAEMON'] = 'yes'
            util.background()

        if not self.is_setup:
            self.setup()

        self.ready.set()
        try:
            while not self.shutting_down:
                self.handle_packet(*self.socket.recvfrom(self.max_packet_size))
                if not self.shutting_down:
                    greenhouse.pause()
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

    def cleanup(self):
        self.socket.close()

    def handle_packet(self, data, address):
        raise NotImplementedError()

    def sendto(self, data, address):
        return self.socket.sendto(data, address)
