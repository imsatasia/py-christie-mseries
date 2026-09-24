"""Pure protocol-logic tests -- no network, no real projector required.

The reply strings here are real captures from an M 4K25 RGB (software
1.3.9, re-verified unchanged on 1.3.10), so they also serve as a record of
what this platform actually sends.

Run with: python3 -m unittest discover -s tests
"""

import unittest

from conftest import FakeSocket

from christie_mseries.client import (
    ChristieClient,
    build_message,
    parse_message,
    parse_quoted,
    parse_value,
    unescape,
)
from christie_mseries.exceptions import ChristieError
from christie_mseries.projector import ChristieM4K25


class BuildMessageTests(unittest.TestCase):
    def test_set(self):
        self.assertEqual(build_message("CON", data=500), b"(CON 500)")

    def test_query(self):
        self.assertEqual(build_message("PWR", query=True), b"(PWR?)")

    def test_subcode(self):
        self.assertEqual(build_message("WRP", subcode="SLCT", data=1), b"(WRP+SLCT 1)")

    def test_ack_prefix(self):
        self.assertEqual(build_message("CON", data=64, prefix="$"), b"($CON 64)")

    def test_rejects_code_wrong_length(self):
        with self.assertRaises(ValueError):
            build_message("PW", data=1)

    def test_rejects_code_with_injected_paren(self):
        # A caller building a code from untrusted text (raw_query/raw_set,
        # and by extension a "send raw command" HA service) must not be
        # able to smuggle a second command past the "(...)" framing.
        with self.assertRaises(ValueError):
            build_message("PWR)($SHU", data=1)

    def test_rejects_subcode_wrong_shape(self):
        with self.assertRaises(ValueError):
            build_message("LAS", subcode="P", data=1)

    def test_rejects_data_with_paren(self):
        with self.assertRaises(ValueError):
            build_message("SHU", data="1) ($PWR 0")

    def test_rejects_data_with_control_character(self):
        with self.assertRaises(ValueError):
            build_message("SHU", data="1\n($PWR 0")

    def test_allows_quoted_string_data(self):
        # Legitimate non-numeric data (e.g. a channel/preset name) must
        # still work -- only the framing-breaking characters are rejected.
        self.assertEqual(build_message("SIN", data='"HDMI 1"'), b'(SIN "HDMI 1")')


class ParseMessageTests(unittest.TestCase):
    def test_reply(self):
        code, subcode, symbol, data = parse_message("(CON!064)")
        self.assertEqual((code, subcode, symbol, data), ("CON", None, "!", "064"))

    def test_reply_with_subcode(self):
        code, subcode, symbol, data = parse_message('(BDR+PRTA!005 "57600")')
        self.assertEqual((code, subcode, symbol), ("BDR", "PRTA", "!"))
        self.assertEqual(data, '005 "57600"')

    def test_reply_quoted_text_only(self):
        _, _, _, data = parse_message('(CHA+INFO!"Tilt the Wagon")')
        self.assertEqual(data, "Tilt the Wagon")

    def test_several_quoted_fields_stay_separable(self):
        """Unwrapping a multi-field reply as if it were one quoted string
        silently merges the fields -- NET used to come back as (' ', ' ')."""
        _, _, _, data = parse_message('(NET!"192.0.2.50" "255.255.255.0" "192.0.2.1")')
        self.assertEqual(parse_quoted(data), ["192.0.2.50", "255.255.255.0", "192.0.2.1"])

    def test_error_raises(self):
        with self.assertRaises(ChristieError) as ctx:
            parse_message('(65535 00000 ERR00005 "ITP: Too Few Parameters")')
        self.assertEqual(ctx.exception.code, 5)
        self.assertEqual(ctx.exception.message, "ITP: Too Few Parameters")


class ParseValueTests(unittest.TestCase):
    """The projector answers most queries with a number plus its own
    description of that number, which plain int() cannot handle."""

    def test_number_with_description(self):
        self.assertEqual(parse_value('000 "Standby Mode"'), (0, "Standby Mode"))

    def test_bare_number(self):
        self.assertEqual(parse_value("-267"), (-267, None))

    def test_negative_with_leading_space(self):
        self.assertEqual(parse_value(" -1032"), (-1032, None))

    def test_text_only(self):
        self.assertEqual(parse_value('"Default User" 04'), (None, "Default User"))

    def test_description_is_unescaped(self):
        self.assertEqual(parse_value('000 "3:14 \\(h:m\\)"'), (0, "3:14 (h:m)"))


class ParseQuotedTests(unittest.TestCase):
    def test_status_item_value_then_label(self):
        self.assertEqual(
            parse_quoted('000 000 "3:14 \\(h:m\\)" "Projector Hours"'),
            ["3:14 (h:m)", "Projector Hours"],
        )

    def test_network_reply(self):
        self.assertEqual(
            parse_quoted('"192.0.2.50" "255.255.255.0" "192.0.2.1"'),
            ["192.0.2.50", "255.255.255.0", "192.0.2.1"],
        )

    def test_unescape_leaves_plain_text_alone(self):
        self.assertEqual(unescape("Air Intake"), "Air Intake")


class SplitMessageTests(unittest.TestCase):
    """Framing has to survive replies arriving split across recv() chunks,
    and status groups that answer with many messages back to back."""

    def test_incomplete_message_is_not_returned(self):
        message, consumed = ChristieClient._split_message(bytearray(b'(PWR!000 "Stand'))
        self.assertIsNone(message)
        self.assertEqual(consumed, 0)

    def test_leaves_remainder_for_next_read(self):
        buf = bytearray(b"(PWR!000)(SHU!001)")
        message, consumed = ChristieClient._split_message(buf)
        self.assertEqual(message, "(PWR!000)")
        self.assertEqual(buf[consumed:], b"(SHU!001)")

    def test_escaped_parens_do_not_end_the_message(self):
        raw = b'(SST+SYST!000 000 "3:14 \\(h:m\\)" "Projector Hours")'
        message, consumed = ChristieClient._split_message(bytearray(raw))
        self.assertEqual(message, raw.decode())
        self.assertEqual(consumed, len(raw))

    def test_non_ascii_status_text_decodes(self):
        raw = '(SST+TEMP!002 000 "32 °C" "Air Intake Temperature")'.encode()
        message, _ = ChristieClient._split_message(bytearray(raw))
        self.assertIn("32 °C", message)


class SetTests(unittest.TestCase):
    """A rejected SET is answered with an error message. Leaving it unread
    doesn't just lose the error -- it gets returned as the reply to the next
    query, which silently shifts every later reading by one."""

    @staticmethod
    def _client(chunks=()):
        client = ChristieClient("projector.invalid", timeout=5.0)
        client._sock = FakeSocket(chunks)
        return client

    def test_successful_set_sends_and_stays_quiet(self):
        client = self._client()
        client.set("SHU", data=0)
        self.assertEqual(bytes(client._sock.sent), b"(SHU 0)")

    def test_rejected_set_raises(self):
        client = self._client([b'(65535 00000 ERR00105 "ITP: Disabled Control")'])
        with self.assertRaises(ChristieError) as ctx:
            client.set("ITP", data=0)
        self.assertEqual(ctx.exception.code, 105)

    def test_set_restores_the_normal_timeout_after_erroring(self):
        client = self._client([b'(65535 00000 ERR00105 "ITP: Disabled Control")'])
        with self.assertRaises(ChristieError):
            client.set("ITP", data=0)
        self.assertEqual(client._sock.timeout, 5.0)

    def test_ack_nak_raises(self):
        client = self._client([b"(^)"])
        with self.assertRaises(ChristieError):
            client.set("PWR", data=1, ack=True)


class BrightnessTests(unittest.TestCase):
    """LAS+POWR is in tenths of a percent. The projector's own soft minimum is
    20%, but the enforced floor is Christie's recommended 30% -- below that
    their release notes warn LiteLOC is compromised and lasers may shut
    down."""

    @staticmethod
    def _projector(chunks=()):
        projector = ChristieM4K25("projector.invalid")
        projector._client._sock = FakeSocket(chunks)
        return projector

    def test_get_brightness_converts_from_tenths(self):
        projector = self._projector([b"(LAS+POWR!700)"])
        self.assertEqual(projector.get_brightness(), 70.0)

    def test_set_brightness_converts_to_tenths(self):
        projector = self._projector()
        projector.set_brightness(85)
        self.assertEqual(bytes(projector._client._sock.sent), b"(LAS+POWR 850)")

    def test_set_brightness_below_soft_minimum_is_rejected(self):
        projector = self._projector()
        with self.assertRaises(ValueError):
            projector.set_brightness(10)
        self.assertEqual(bytes(projector._client._sock.sent), b"")

    def test_set_brightness_in_the_discouraged_band_is_rejected(self):
        # 25% is inside the projector's own soft range but below Christie's
        # recommended minimum, so nothing should reach the wire.
        projector = self._projector()
        with self.assertRaises(ValueError):
            projector.set_brightness(25)
        self.assertEqual(bytes(projector._client._sock.sent), b"")

    def test_set_brightness_at_the_recommended_floor_is_allowed(self):
        projector = self._projector()
        projector.set_brightness(30)
        self.assertEqual(bytes(projector._client._sock.sent), b"(LAS+POWR 300)")

    def test_liteloc_is_three_for_enabled(self):
        self.assertTrue(self._projector([b'(LAS+STAT!003 "Enabled")']).get_liteloc())
        self.assertFalse(self._projector([b'(LAS+STAT!001 "Disabled")']).get_liteloc())


if __name__ == "__main__":
    unittest.main()
