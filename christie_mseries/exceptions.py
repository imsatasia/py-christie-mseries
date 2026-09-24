class ChristieError(Exception):
    """A projector-reported error, per the ERR##### reply format."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Christie error {code}: {message}")


class ChristieConnectionError(ConnectionError):
    """The TCP connection to the projector is missing, closed, or sent garbage."""
