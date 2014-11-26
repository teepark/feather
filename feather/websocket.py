# vim: fileencoding=utf8:et:sw=4:ts=8:sts=4

import hashlib
import struct


class WebSocketHandler(object):
    def __init__(self, connection):
        self.connection = connection

    def allow(self, request):
        """
        WebSocket appropriateness validation

        Override this method to add validation for the HTTP request requesting
        protocol upgrade to websockets.

        The argument is an HTTPRequest (like those provided to
        http.HTTPRequestHandlers).

        This method should return a 2-tuple of:
        (response_code, additional_headers)

        The "response_code" is the HTTP response code to use. Only 101 will
        permit the upgrade to take place.

        "additional_headers" should be a list of two-tuples (key, value) which
        will be sent as headers in the HTTP response. There is no need to
        provide "Connection", "Upgrade", "Sec-WebSocket-Accept", or
        "Sec-WebSocket-Protocol", or "Sec-WebSocket-Extensions" here, they will
        all be generated elsewhere.
        """
        return 101, []

    def select_subprotocol(self, choices):
        """
        Select from the sub-protocols for which the client advertised support

        Override this to act on particular sub-protocols, the default
        implementation always returns None.

        Return either one of the options presented in "choices", the list
        argument, or None.
        """
        return None

    def select_extensions(self, choices):
        """
        Select from the extensions for which the client advertised support

        Override this to accept support for one or more extensions, the default
        implementation always returns the empty list.

        Return a list, all the contents of which must have been present in the
        "choices" argument.
        """
        return []

    def handle(self, messages):
        """
        """
        pass

    def _handle(self, sockfile, connection):
        try:
            recv_producer = MessageProducer(sockfile, connection)
            for frame in self.handle(recv_producer):
                if isinstance(frame, (str, unicode)):
                    frame = format_single_data_frame_msg(frame)
                    print "pushing a single data frame msg: %r" % (frame,)
                    connection.push(frame)
                else:
                    raise ServerProtocolError(
                        "can only handle str and unicode outgoing frames")
        finally:
            connection.server.connections.decrement()

        connection._cleanup()

    def _allow(self, request):
        if request.headers.get('sec-websocket-version') != '13':
            print "failure on version"
            return 400, [('Sec-WebSocket-Version', '13')]

        if 'sec-websocket-key' not in request.headers:
            print "failure on key"
            return 400, []

        return self.allow(request)

    def _process_key(self, key):
        hsh = hashlib.sha1(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")

        print "converted key %r to %r" % (
            key, hsh.digest().encode('base64').rstrip())

        return hsh.digest().encode('base64').rstrip()

    def _negotiate(self, request):
        # pick a subprotocol (or None) from those offered by the client
        choices = request.headers.get('sec-websocket-protocol', '').split(',')
        choices = [p.strip() for p in choices]
        if choices:
            subprot = self.select_subprotocol(choices)
            if subprot not in [None] + choices:
                raise ServerProtocolError(
                    "subprotocol was not offered by the client")
        else:
            subprot = None

        # pick extensions from those offered by the client
        choices = request.headers.get('sec-websocket-extensions', '')
        choices = [x.strip() for x in choices.split(',')]
        if choices:
            exts = self.select_extensions(choices)
            for ext in exts:
                if ext not in choices:
                    raise ServerProtocolError(
                        "extension was not offered by the client")
        else:
            exts = []

        accept = self._process_key(request.headers['sec-websocket-key'])

        return accept, subprot, exts


class Frame(object):
    __slots__ = ['fin', 'opcode', 'payload', 'resv1', 'resv2', 'resv3']


def get_frame(content):
    print "waiting to read a new frame"
    meta = _read_bytes(content, 2)
    print "got first bytes of a new frame"

    byte = ord(meta[0])
    fin = bool(byte & 0x80)
    print "  fin: %r" % fin
    resv1 = bool(byte & 0x40)
    resv2 = bool(byte & 0x20)
    resv3 = bool(byte & 0x10)
    print "  resv1: %r, resv2: %r, resv3: %r" % (resv1, resv2, resv3)
    opcode = byte & 0x0f
    print "  opcode: %r" % opcode

    if (3 <= opcode <= 7) or opcode >= 0x0b:
        raise InvalidFrame("unknown opcode")

    byte = ord(meta[1])
    masked = byte & 0x80
    print "  masked: %r" % bool(masked)
    length = byte & 0x7f
    print "  length (initial): %r" % (length,)

    if not masked:
        raise InvalidFrame("mask required for client->server frames")

    if opcode & 0x80 and length > 125:
        raise InvalidFrame("too long for a control frame")

    if length == 126:  # real length is in the next 2 bytes
        length = struct.unpack(">H", _read_bytes(content, 2))[0]

    elif length == 127:  # real length is in the next 4 bytes
        length = struct.unpack(">Q", _read_bytes(content, 4))[0]

    print "  length: (final): %r" % (length,)

    mask = struct.unpack(">I", _read_bytes(content, 4))[0]
    print "  mask: %r" % (mask,)

    # TODO: provide a reader file-like object that unmasks as it reads so
    #       we don't necessarily have to hold the whole payload in memory
    payload = _unmask(mask, _read_bytes(content, length), 0, length)
    print "  payload: %r" % (payload,)

    frame = Frame()
    frame.fin = fin
    frame.resv1 = resv1
    frame.resv2 = resv2
    frame.resv3 = resv3
    frame.opcode = opcode
    frame.payload = payload
    print "parse complete, delivering frame"
    return frame


def _read_bytes(content, length):
    result = content.read(length)
    if len(result) < length:
        raise InvalidFrame("disconnected")
    return result


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


class MessageProducer(object):
    def __init__(self, sockfile, conn):
        self._sockfile = sockfile
        self._conn = conn

    def __iter__(self):
        current = []

        while 1:
            frame = get_frame(self._sockfile)
            if frame.opcode & 0x8:
                _deal_with_control_frame(frame, self._conn)

            if frame.opcode == 0:  # continuation frame
                if not current:
                    raise InvalidFrame("continuation frame without context")

                current.append(frame)

                if frame.fin:
                    yield _payload_of_data_message(current)
                    current = []

                continue

            if frame.opcode in (1, 2):  # text frame
                if current:
                    raise InvalidFrame(
                        "non-continuation data frame out of context")

                if frame.fin:
                    yield _unwrap(frame)
                    current = []
                else:
                    current.append(frame)

                continue

            raise InvalidFrame("unrecognized opcode")


def _deal_with_control_frame(frame, conn):
    if not frame.fin:
        raise InvalidFrame("control frame without fin")

    if frame.opcode == 0x8:  # CLOSE
        raise ClosedStream()

    if frame.opcode == 0x9:  # PING
        # immediately respond with a corresponding PONG
        print "pushing a control PONG frame"
        conn.push(format_control_frame(0xA, frame.payload))
        return

    if frame.opcode == 0xA:  # PONG
        return  # no need to do anything with this

    raise InvalidFrame("unrecognized opcode")


def _payload_of_data_message(frames):
    payload = ''.join(f.payload for f in frames)

    if frames[0].opcode == 1:
        return payload.decode('utf8')

    if frames[0].opcode == 2:
        return payload

    raise InvalidFrame("unknown opcode for a first fragment")


def _unwrap(frame):
    # function assumes 'frame' is already known to be a data frame
    if frame.opcode == 1:
        return frame.payload.decode('utf8')
    if frame.opcode == 2:
        return frame.payload


def format_single_data_frame_msg(output):
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


def format_control_frame(opcode, payload):
    if len(payload) > 125:
        raise InvalidFrame("too long for a control frame")

    return ''.join((chr(0x8 | opcode), chr(len(payload)), payload))


class InvalidFrame(Exception):
    pass


class ServerProtocolError(Exception):
    pass


class ClosedStream(Exception):
    pass
