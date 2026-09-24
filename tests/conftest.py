"""Shared test doubles -- no network, no real projector required."""

# Insert into `chunks` to simulate the projector going idle mid-sequence --
# e.g. between two SST+<group> multi-message replies queued on one socket --
# without exhausting the whole chunk list. query_multi()'s "read until idle"
# loop treats this exactly like a real read timeout.
TIMEOUT = object()


class FakeSocket:
    """Stands in for a connected projector: replays `chunks` from recv(),
    raises TimeoutError for a TIMEOUT sentinel (an idle gap mid-sequence),
    and raises TimeoutError once `chunks` run out entirely, like a device
    that went quiet for good."""

    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.sent = bytearray()
        self.timeout = None

    def sendall(self, data):
        self.sent.extend(data)

    def recv(self, _size):
        if not self.chunks:
            raise TimeoutError
        chunk = self.chunks.pop(0)
        if chunk is TIMEOUT:
            raise TimeoutError
        return chunk

    def settimeout(self, timeout):
        self.timeout = timeout

    def close(self):
        pass
