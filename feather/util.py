import errno
import os
import resource
import stat
import sys

from greenhouse import scheduler


__all__ = ["background"]


try:
    closerange = os.closerange
except AttributeError:
    def closerange(*args):
        for fd in xrange(*args):
            try:
                os.close(fd)
            except EnvironmentError:
                pass


def background():
    if os.fork():
        sys.exit(0)

    os.setsid()
    sys.argv[0] = os.path.abspath(sys.argv[0])
    os.chdir('/')
    os.umask(0)
    closerange(0, resource.getrlimit(resource.RLIMIT_NOFILE)[0])

    if os.fork():
        sys.exit(0)

    scheduler.reset_poller()
