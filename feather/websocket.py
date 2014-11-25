# vim: fileencoding=utf8:et:sw=4:ts=8:sts=4

"""
API design
==========


class Handler(http.HTTPRequestHandler):

    websockets = True

    def do_GET(self, request):
        # regular GET request...

    def do_websocket(self, request, gen):
        # this method gets called in the event that a GET request meets
        # requirements for a websocket request.

        # the first argument is the http request that triggered the
        # upgrade to the websocket protocol (this may be useful for the
        # 'Origin' header for example)

        # the 'gen' argument is a generator that produces messages from
        # the client. it will produce instances of websocket.Frame.

        # do_websocket must also itself be a generator, which will be
        # used to send frames back. yield unicode objects for text
        # frames, or bytestrings for binary frames.

"""

import struct


class Frame(object):
    __slots__ = ['fin', 'opcode', 'payload', 'resv1', 'resv2', 'resv3']


def get_frame(content):
    meta = _read_bytes(content, 2)

    # first byte
    byte = ord(meta[0])
    fin = bool(byte & 0x80)
    resv1 = bool(byte & 0x40)
    resv2 = bool(byte & 0x20)
    resv3 = bool(byte & 0x10)
    opcode = byte & 0x0f

    if (3 <= opcode <= 7) || opcode >= 0x0b:
        raise InvalidFrame("unknown opcode")

    byte = ord(meta[1])
    masked = byte & 0x80
    length = byte & 0x7f

    if not masked:
        raise InvalidFrame("mask required for client->server frames")

    if length == 126:  # real length is in the next 2 bytes
        length = struct.unpack(">H", _read_bytes(content, 2))[0]

    elif length == 127:  # real length is in the next 4 bytes
        length = struct.unpack(">Q", _read_bytes(content, 4))[0]

    mask = struct.unpack(">I", _read_bytes(content, 4))[0]

    # TODO: provide a reader file-like object that unmasks as it reads so
    #       we don't necessarily have to hold the whole payload in memory
    payload = _unmask(mask, _read_bytes(content, length), 0, length)

    frame = Frame()
    frame.fin = fin
    frame.resv1 = resv1
    frame.resv2 = resv2
    frame.resv3 = resv3
    frame.opcode = opcode
    frame.payload = payload
    return frame


def _read_bytes(content, length):
    result = content.read(length)
    if len(result) < length:
        raise InvalidFrame("disconnected")


def _group_by(msg, start, end, size):
    for i in xrange(start, end, size):
        yield msg[start:start+size]
        start += size


def _unmask(mask, msg, start, length):
    unpack = struct.unpack
    pack = struct.pack
    chunks = []

    pagefmt = ">" + ("I" * 1024)
    for page in _group_by(msg, start, length, 4096):
        if len(page) < 4096:
            # last, partial page
            size = len(page) // 4
            fmt = ">" + ("I" * size)
            ints = unpack(fmt, page[:size*4])
            masked = [mask ^ i for i in ints]
            chunks.append(pack(fmt, *masked))
            break

        # whole page
        ints = unpack(pagefmt, page)
        masked = [mask ^ i for i in ints]
        chunks.append(pack(pagefmt, *masked))

    # now catch the last 3 bytes
    leftover = (length - start) % 4
    while 1:
        if not leftover:
            break

        chunks.append(chr((mask & 0xff) ^ ord(msg[length-leftover])))
        leftover -= 1
        mask >>= 1

    return ''.join(chunks)


def format_single_frame_msg(output):
    if isinstance(output, unicode):
        opcode = 0x01  # text frame
        output = output.encode('utf8')
    elif isinstance(output, str):
        opcode = 0x02  # binary frame
    else:
        return None

    msg = [chr(0x80 | opcode)]
    if len(output) < 126:
        msg.append(chr(len(output)))
    elif len(output) < (1 << 16):
        msg += [chr(126), struct.pack(">H", len(output))]
    else:
        msg += [chr(127), struct.pack(">Q", len(output))]

    msg.append(output)
    return ''.join(msg)


class InvalidFrame(Exception):
    pass


def _input_gen(content):
    while 1:
        yield get_frame(content)


def _handle_with_http(handler, request):
    conn = handler.connection
    if conn.keepalive_timeout:
        conn.socket.settimeout(None)
    request.content._ignore_length = True

    input_gen = _input_gen(request.content)
    for output in handler._do_websocket(request, input_gen):
        frame = format_single_frame_msg(output)
        if frame is None:
            break
        else:
            conn.push(frame)
