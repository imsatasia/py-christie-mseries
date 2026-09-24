"""Wire protocol for the Christie M Series Serial API (doc 020-100224-11),
used here over its TCP/IP passthrough (port 3002) rather than RS232/RS422.

Only single-projector, single-controller use is implemented: the daisy-chain
projector/controller addressing scheme described in the "Network operation"
section of the API doc is not supported, since a single M 4K25 on a LAN has
no use for it.
"""

from __future__ import annotations

import re
import socket

from .exceptions import ChristieConnectionError, ChristieError

DEFAULT_PORT = 3002

# Error replies look like: (65535 00000 ERR00005 "ITP: Too Few Parameters")
# The leading dest/src address fields are ignored -- see module docstring.
_ERROR_RE = re.compile(r'ERR(\d+)\s+"([^"]*)"')
_MESSAGE_RE = re.compile(r"^([A-Za-z]{3})(?:\+([A-Za-z0-9]{4}))?([!?]?)(.*)$", re.DOTALL)

# Most replies carry a number followed by the projector's own description of
# it, e.g. (PWR!000 "Standby Mode") -- so plain int() on the data fails.
_LEADING_INT_RE = re.compile(r"\s*(-?\d+)")
_QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_SINGLE_QUOTED_RE = re.compile(r'^"((?:[^"\\]|\\.)*)"$')

# A code/subcode's shape is fixed by the protocol itself -- the same shape
# _MESSAGE_RE above expects on the way in. Enforcing it on the way out too
# means a caller building a message from untrusted text (raw_query/raw_set,
# and by extension the "send raw command" service some integrations expose)
# gets a clear ValueError instead of a message that silently smuggles a
# second "(...)" command past the framing.
_OUTGOING_CODE_RE = re.compile(r"^[A-Za-z]{3}$")
_OUTGOING_SUBCODE_RE = re.compile(r"^[A-Za-z0-9]{4}$")
# Parens are the wire framing's own delimiters and control chars have no
# legitimate use in this text protocol -- either would corrupt the message.
_UNSAFE_DATA_RE = re.compile(r"[()\x00-\x1f\x7f]")


def unescape(text: str) -> str:
    """Undo the backslash escaping the projector applies inside quoted text,
    e.g. "3:14 \\(h:m\\)" -> "3:14 (h:m)"."""
    return re.sub(r"\\(.)", r"\1", text)


def parse_quoted(data: str) -> list[str]:
    """Return every quoted field in reply data, unescaped. Status items pair
    them up as value then label, e.g. "3:14 \\(h:m\\)" "Projector Hours"."""
    return [unescape(m.group(1)) for m in _QUOTED_RE.finditer(data)]


def parse_value(data: str) -> tuple[int | None, str | None]:
    """Split reply data into its leading number and first quoted description.

    Replies are not uniform: some are bare numbers ((ZOM!-267)), some pair a
    number with a label ((PWR!000 "Standby Mode")), and some are text only
    ((NET!"192.0.2.50" ...)). Either half is None when absent.
    """
    number = _LEADING_INT_RE.match(data)
    quoted = _QUOTED_RE.search(data)
    return (
        int(number.group(1)) if number else None,
        unescape(quoted.group(1)) if quoted else None,
    )


def build_message(
    code: str,
    subcode: str | None = None,
    data=None,
    query: bool = False,
    prefix: str = "",
) -> bytes:
    """Build one (CODE Data) / (CODE?) / (CODE+SUBCODE Data) wire message.
    `prefix` is an optional single ack character ("$") inserted right after
    the opening bracket, per the API doc's message-integrity options.

    Raises ValueError for a code/subcode/data that doesn't fit the wire
    format, rather than silently building a message a caller's stray
    parenthesis (or worse, a deliberately crafted one) could use to smuggle
    a second command past the framing -- see raw_query()/raw_set()."""
    if not _OUTGOING_CODE_RE.match(code):
        raise ValueError(f"invalid code {code!r}: must be exactly 3 letters")
    if subcode is not None and not _OUTGOING_SUBCODE_RE.match(subcode):
        raise ValueError(f"invalid subcode {subcode!r}: must be exactly 4 letters/digits")
    if isinstance(data, str) and _UNSAFE_DATA_RE.search(data):
        raise ValueError(
            f"invalid data {data!r}: parentheses/control characters would corrupt the message framing"
        )

    body = prefix + code.upper()
    if subcode:
        body += f"+{subcode.upper()}"
    if query:
        body += "?"
    elif data is not None:
        body += f" {data}"
    return f"({body})".encode("ascii")


def parse_message(raw: str) -> tuple[str, str | None, str, str]:
    """Parse a (CODE!DATA) / (CODE+SUBCODE!DATA) reply. Raises ChristieError
    if the projector reported an error instead."""
    if not (raw.startswith("(") and raw.endswith(")")):
        raise ChristieConnectionError(f"Malformed reply from projector: {raw!r}")
    body = raw[1:-1]

    error_match = _ERROR_RE.search(body)
    if error_match:
        raise ChristieError(int(error_match.group(1)), error_match.group(2))

    match = _MESSAGE_RE.match(body)
    if not match:
        raise ChristieConnectionError(f"Unrecognized reply from projector: {raw!r}")
    code, subcode, symbol, data = match.groups()
    data = data.strip()
    # Unwrap only when the whole payload is one quoted string. Replies like
    # NET's ("ip" "mask" "gateway") must keep their quotes, or the fields
    # run together into one unparseable string.
    single_quoted = _SINGLE_QUOTED_RE.match(data)
    if single_quoted:
        data = single_quoted.group(1)
    return code, subcode, symbol, data


class ChristieClient:
    """Low-level ASCII connection to a Christie M Series projector."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = 5.0):
        """Create a client for the projector at `host`. Does not connect --
        call connect() or use as a context manager. `timeout` applies to
        both the initial connection and each subsequent recv()."""
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = bytearray()

    def connect(self) -> None:
        """Open the TCP connection to (host, port)."""
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._buf.clear()

    def close(self) -> None:
        """Close the TCP connection, if open."""
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        self._buf.clear()

    def __enter__(self) -> ChristieClient:
        """Connect on entering a `with` block."""
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        """Close the connection on leaving a `with` block."""
        self.close()

    def _require_socket(self) -> socket.socket:
        """Return the open socket, or raise if connect() hasn't been called."""
        if self._sock is None:
            raise ChristieConnectionError("Not connected -- call connect() first")
        return self._sock

    @staticmethod
    def _split_message(buf: bytearray) -> tuple[str | None, int]:
        """Find the first complete (...) message in `buf`, respecting the
        \\( \\) escape so quoted text containing literal parens doesn't break
        framing. Returns (message, bytes_consumed), or (None, 0) if `buf`
        doesn't hold a whole message yet."""
        depth = 0
        started = False
        escape = False
        for i, c in enumerate(buf):
            if escape:
                escape = False
                continue
            if c == 0x5C:  # backslash
                escape = True
                continue
            if c == 0x28:  # (
                depth += 1
                started = True
            elif c == 0x29:  # )
                depth -= 1
                if started and depth == 0:
                    # Decoded as UTF-8: status text carries non-ASCII, e.g. the
                    # degree sign in SST+TEMP's "32 °C".
                    return buf[: i + 1].decode("utf-8", "replace"), i + 1
        return None, 0

    def _read_message(self) -> str:
        """Read one complete (...) message, buffering whatever else arrived
        with it so a multi-message reply can be read without re-reading the
        socket a byte at a time."""
        sock = self._require_socket()
        while True:
            message, consumed = self._split_message(self._buf)
            if message is not None:
                del self._buf[:consumed]
                return message
            chunk = sock.recv(4096)
            if not chunk:
                raise ChristieConnectionError("Connection closed by projector")
            self._buf.extend(chunk)

    def query(self, code: str, subcode: str | None = None) -> str:
        """Send a REQUEST (Code?) message and return the reply data."""
        self._require_socket().sendall(build_message(code, subcode, query=True))
        _, _, _, data = parse_message(self._read_message())
        return data

    def query_value(self, code: str, subcode: str | None = None) -> tuple[int | None, str | None]:
        """Send a REQUEST and split the reply into (number, description)."""
        return parse_value(self.query(code, subcode))

    def query_int(self, code: str, subcode: str | None = None) -> int:
        """Send a REQUEST and return just the numeric part of the reply."""
        number, _ = self.query_value(code, subcode)
        if number is None:
            raise ChristieConnectionError(f"{code} did not return a numeric value")
        return number

    def query_multi(self, code: str, subcode: str | None = None, idle: float = 0.4) -> list[str]:
        """Send a REQUEST that answers with many messages (SST status groups
        reply with one message per item) and return every message's data.

        There is no terminator to look for, so the end of the reply is
        detected by the projector going quiet for `idle` seconds.
        """
        sock = self._require_socket()
        sock.sendall(build_message(code, subcode, query=True))
        replies = [parse_message(self._read_message())[3]]
        sock.settimeout(idle)
        try:
            while True:
                replies.append(parse_message(self._read_message())[3])
        except TimeoutError:
            pass
        finally:
            sock.settimeout(self.timeout)
        return replies

    def set(
        self,
        code: str,
        subcode: str | None = None,
        data=None,
        ack: bool = False,
        error_wait: float = 0.25,
    ) -> None:
        """Send a SET (Code Data) message.

        A SET that succeeds is answered with silence, but a rejected one
        gets an error message back (the projector has error reporting on --
        EME is 1), so this always waits `error_wait` seconds for one. Skipping
        that check doesn't just lose the error: it stays in the socket buffer
        and is read as the reply to the *next* query, desynchronizing
        everything after it.

        With ack=True, requests a positive acknowledgment and blocks until the
        projector confirms the command finished executing -- raises
        ChristieError if it responds with a NAK. Useful for commands like
        power on where completion isn't instant; set a longer `timeout` on
        the client for those.
        """
        prefix = "$" if ack else ""
        self._require_socket().sendall(build_message(code, subcode, data=data, prefix=prefix))
        if ack:
            reply = self._read_message()
            if reply[1:-1] == "^":
                raise ChristieError(0, f"{code} was not acknowledged by the projector")
            parse_message(reply)  # raises if the projector reported an error instead
            return
        self._raise_pending_error(error_wait)

    def _raise_pending_error(self, timeout: float) -> None:
        """Consume anything the projector sent back unprompted, raising if it
        was an error. Returns quietly once it has gone silent for `timeout`."""
        sock = self._require_socket()
        sock.settimeout(timeout)
        try:
            while True:
                parse_message(self._read_message())
        except TimeoutError:
            pass
        finally:
            sock.settimeout(self.timeout)
