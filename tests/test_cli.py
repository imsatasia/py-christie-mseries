"""Tests for the CLI's 3D commands -- no network, no real projector."""

import unittest

from conftest import TIMEOUT, FakeSocket

from christie_mseries.cli import run_3d
from christie_mseries.exceptions import ChristieError
from christie_mseries.projector import ChristieM4K25


def _projector(chunks=()):
    projector = ChristieM4K25("projector.invalid")
    projector._client._sock = FakeSocket(chunks)
    return projector


def _sent(projector):
    return bytes(projector._client._sock.sent)


class RunThreeDTests(unittest.TestCase):
    def test_plain_3d_prints_every_setting_and_status(self):
        projector = _projector(
            [
                b'(TDM!003 "Side-by-Side 3D")',
                b'(TDO!000 "To Emitter")',
                b'(SST+SIGN!"Locked" "3D Sync")',
                b'(SST+SIGN!"Achieved" "3D Darktime Status")',
                TIMEOUT,
                b"(TDD!-50)",
                b"(DRK!1500)",
                b"(TDN!000)",
                b"(TDT!001)",
            ]
        )
        text = run_3d(projector, "3d", None)
        self.assertIn("3 (Side-by-Side 3D)", text)
        self.assertIn("timing controls enabled", text)
        self.assertIn("-50", text)
        self.assertIn("Invert eyes:      off", text)
        self.assertIn("Test pattern:     on", text)
        self.assertIn("Locked", text)
        self.assertIn("Achieved", text)

    def test_3d_mode_by_name_sets_then_reads_back(self):
        projector = _projector([TIMEOUT, b'(TDM!005 "Top-and-Bottom 3D")'])
        self.assertEqual(
            run_3d(projector, "3d-mode", "Top-and-Bottom 3D"), "3D mode is now 5 (Top-and-Bottom 3D)"
        )
        self.assertEqual(_sent(projector), b"(TDM 5)(TDM?)")

    def test_3d_mode_by_number(self):
        projector = _projector([TIMEOUT, b'(TDM!006 "Frame Packing 3D")'])
        run_3d(projector, "3d-mode", "6")
        self.assertTrue(_sent(projector).startswith(b"(TDM 6)"))

    def test_3d_mode_without_an_argument_only_reads(self):
        projector = _projector([b'(TDM!000 "Off")'])
        run_3d(projector, "3d-mode", None)
        self.assertEqual(_sent(projector), b"(TDM?)")

    def test_negative_delay_is_parsed_as_a_number(self):
        projector = _projector([TIMEOUT, b"(TDD!-200)"])
        self.assertEqual(run_3d(projector, "3d-delay", "-200"), "3D sync delay is now -200")
        self.assertTrue(_sent(projector).startswith(b"(TDD -200)"))

    def test_out_of_range_dark_interval_raises_value_error(self):
        with self.assertRaises(ValueError):
            run_3d(_projector(), "3d-dark-interval", "99999")

    def test_switches_take_on_and_off(self):
        projector = _projector([TIMEOUT, b"(TDN!001)"])
        self.assertEqual(run_3d(projector, "3d-invert", "on"), "Eye inversion is now on")
        self.assertTrue(_sent(projector).startswith(b"(TDN 1)"))
        projector = _projector([TIMEOUT, b"(TDT!000)"])
        self.assertEqual(run_3d(projector, "3d-test-pattern", "off"), "3D test pattern is now off")
        self.assertTrue(_sent(projector).startswith(b"(TDT 0)"))

    def test_a_switch_rejects_a_value_that_is_not_on_or_off(self):
        with self.assertRaises(ValueError):
            run_3d(_projector(), "3d-invert", "maybe")

    def test_a_disabled_control_surfaces_the_projectors_error(self):
        projector = _projector([b'(65535 00000 ERR00105 "TDN: Disabled Control")'])
        with self.assertRaises(ChristieError):
            run_3d(projector, "3d-invert", "on")
