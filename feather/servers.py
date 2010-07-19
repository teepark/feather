import errno
import os
import socket
import subprocess

import greenhouse
from feather import connections


__all__ = ["BaseServer", "TCPServer", "UDPServer"]


class BaseServer(object):
    """purely abstract server class.

    subclass TCPServer or UDPServer instead (or just use them as they are).
    """
    address_family = socket.AF_INET
    socket_protocol = socket.SOL_IP
    worker_count = 5
    allow_reuse_address = True

    def __init__(self, address):
        self.host, self.port = address
        self.is_setup = False
        self.shutting_down = False

    def init_socket(self):
        self.socket = greenhouse.Socket(
                self.address_family,
                self.socket_type,
                self.socket_protocol)
        if self.allow_reuse_address:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def setup(self):
        self.pre_fork_setup()
        self.fork_children()
        self.post_fork_setup()
        self.is_setup = True

    def pre_fork_setup(self):
        if not hasattr(self, "socket"):
            self.init_socket()
        self.socket.bind((self.host, self.port))

    def post_fork_setup(self):
        pass

    def fork_children(self):
        for i in xrange(self.worker_count - 1):
            if not os.fork():
                # children will need their own epoll object
                greenhouse.poller.set()
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

    * max_conns is the number of connections to handle simultaneously per
      worker process. it defaults to the maximum number of file descriptors one
      process is allowed to have open, after accounting for stdin, stdout,
      stderr and the listening socket. if you are running more than one
      TCPServer together you should reduce max_conns to accomodate them all.

    * descriptor_counter is a greenhouse.BoundedSemaphore that controls socket
      and file object creation (created on setup()). if you open sockets (for
      api calls or database connections) you may want to call
      server.descriptor_counter.acquire() (and .release() when the socket
      closes) to avoid EMFILE exceptions.

    the cleanup() method may also be overridden (but call the super) to add
    extra behavior at the server's exit
    """
    socket_type = socket.SOCK_STREAM
    listen_backlog = socket.SOMAXCONN
    connection_handler = connections.TCPConnection
    max_conns = subprocess.MAXFD - 4 # stdin, stdout, stderr, listening socket
    if isinstance(greenhouse.scheduler.state.poller, greenhouse.poller.Poll):
        max_conns -= 1 # Poll and Epoll objects use up another fd

    def __init__(self, *args, **kwargs):
        super(TCPServer, self).__init__(*args, **kwargs)
        self.killable = {}

    def pre_fork_setup(self):
        super(TCPServer, self).pre_fork_setup()
        self.socket.listen(self.listen_backlog)
        self.descriptor_counter = greenhouse.BoundedSemaphore(self.max_conns)

    def setup(self):
        super(TCPServer, self).setup()
        self.open_conns = 0

    def serve(self):
        """run the server at the provided address forever.

        this method will remove the calling greenlet (generally the main
        greenlet) from the scheduler, so don't expect anything else to run in
        the calling greenlet until the server has been shut down.
        """
        if not self.is_setup:
            self.setup()

        try:
            while not self.shutting_down:
                try:
                    # this will block until fewer than max_conns handlers exist
                    self.descriptor_counter.acquire()

                    client_sock, client_address = self.socket.accept()
                    handler = self.connection_handler(
                            client_sock,
                            client_address,
                            self)
                    greenhouse.schedule(handler.serve_all)
                    self.open_conns += 1
                except socket.error, error:
                    if error.args[0] == errno.EMFILE:
                        # max open connections for the process
                        if self.killable:
                            # close all the connections that are
                            # only open for keep-alive anyway
                            for handler in self.killable.values():
                                handler.socket.close()
                                handler.closing = True
                            self.killable.clear()
                        else:
                            # if all connections are active, just let the
                            # semaphore block -- we already set its value to 0
                            continue

                    elif error.args[0] == errno.ENFILE:
                        # max open connections for the machine
                        greenhouse.pause_for(0.01)
                    elif error.args[0] == errno.EINVAL:
                        # server socket was shut down
                        break
                    elif error.args[0] == errno.EBADF:
                        # believe it or not, this is the graceful shutdown
                        # case. see the comments in shutdown() below
                        break
                    else:
                        raise
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

    def cleanup(self):
        self.socket.close()

        # kill all connections now that aren't actively serving requests
        # and the rest won't pick up new requests because of self.shutting_down
        for handler in self.killable.values():
            handler.socket.close()
            handler.closing = True

        # do a small timed wait until current requests are finished
        while self.open_conns:
            greenhouse.pause_for(0.05)

    def shutdown(self):
        self.shutting_down = True

        # there's no good way to interrupt an accept() call without shutting
        # down the socket, and there may be sibling processes listening on the
        # same socket that we want to leave alone. so this cheats, using the
        # internals of greenhouse.io.Socket to bail out in only this process.

        # wake up the greenlet blocked on the accept() call
        self.socket._sock._readable.set()

        # and also make sure the accept() call blows up with EBADF
        self.socket._sock.close()

class UDPServer(BaseServer):
    socket_type = socket.SOCK_DGRAM
    max_packet_size = 8192

    def serve(self):
        if not self.is_setup:
            self.setup()

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
