import logging
import sys


VERSION = (0, 1, 0, '')
__version__ = ".".join(filter(None, map(str, VERSION)))


def configure_logging(sublogger=None, filename=None, filemode=None, fmt=None,
        level=logging.INFO, stream=None, handler=None):
    if handler is None:
        if filename is None:
            handler = logging.StreamHandler(stream or sys.stderr)
        else:
            handler = logging.FileHandler(filename, filemode or 'a')

    if fmt is None:
        fmt = "%(process)d [%(asctime)s] %(name)s/%(levelname)s | %(message)s"
    handler.setFormatter(logging.Formatter(fmt))

    name = "feather"
    if sublogger is not None:
        name += "." + sublogger
    log = logging.getLogger(name)
    log.setLevel(level)
    log.addHandler(handler)
