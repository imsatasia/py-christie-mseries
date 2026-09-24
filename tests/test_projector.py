"""Tests for the ChristieM4K25 domain layer -- no network, no real projector
required. client.py's parsing/framing is covered by test_protocol.py; this
file covers projector.py's higher-level methods built on top of it.
"""

import unittest

from conftest import TIMEOUT, FakeSocket

from christie_mseries.exceptions import ChristieError
from christie_mseries.projector import INPUTS, INPUTS_BY_NAME, ChristieM4K25, PowerState, Snapshot


def _projector(chunks=()):
    projector = ChristieM4K25("projector.invalid")
    projector._client._sock = FakeSocket(chunks)
    return projector


class PowerTests(unittest.TestCase):
    def test_power_on_sends_pwr_1(self):
        projector = _projector()
        projector.power_on()
        self.assertEqual(bytes(projector._client._sock.sent), b"(PWR 1)")

    def test_power_off_sends_pwr_0(self):
        projector = _projector()
        projector.power_off()
        self.assertEqual(bytes(projector._client._sock.sent), b"(PWR 0)")

    def test_get_power_state_returns_enum(self):
        projector = _projector([b'(PWR!000 "Standby Mode")'])
        self.assertEqual(projector.get_power_state(), PowerState.STANDBY)

    def test_get_power_state_text_prefers_device_wording(self):
        projector = _projector([b'(PWR!001 "On")'])
        self.assertEqual(projector.get_power_state_text(), "On")

    def test_power_on_wait_uses_ack(self):
        projector = _projector([b'(PWR!001 "On")'])
        projector.power_on(wait=True)
        self.assertEqual(bytes(projector._client._sock.sent), b"($PWR 1)")


class ShutterTests(unittest.TestCase):
    def test_open_shutter_sends_shu_0(self):
        projector = _projector()
        projector.open_shutter()
        self.assertEqual(bytes(projector._client._sock.sent), b"(SHU 0)")

    def test_is_shutter_open_true_when_zero(self):
        self.assertTrue(_projector([b"(SHU!000)"]).is_shutter_open())
        self.assertFalse(_projector([b"(SHU!001)"]).is_shutter_open())


class InputChannelTests(unittest.TestCase):
    def test_select_input_sends_index(self):
        projector = _projector()
        projector.select_input(3)
        self.assertEqual(bytes(projector._client._sock.sent), b"(SIN 3)")

    def test_select_input_by_label_sends_its_index(self):
        projector = _projector()
        projector.select_input("HDMI 2.1 Port 3")
        self.assertEqual(bytes(projector._client._sock.sent), b"(SIN 3)")

    def test_select_input_unknown_label_raises_without_sending(self):
        projector = _projector()
        with self.assertRaises(ValueError):
            projector.select_input("HDMI 9.9 Port 0")
        self.assertEqual(bytes(projector._client._sock.sent), b"")

    def test_input_labels_are_unique(self):
        # INPUTS_BY_NAME is a reverse lookup, so a duplicate would make an
        # input unselectable by name.
        self.assertEqual(len(INPUTS_BY_NAME), len(INPUTS))

    def test_get_input_returns_index_and_name(self):
        projector = _projector([b'(SIN!001 "One-Port HDMI0")'])
        self.assertEqual(projector.get_input(), (1, "One-Port HDMI0"))

    def test_get_channel_returns_number_and_name(self):
        projector = _projector([b'(CHA!600 "One-Port HDMI0")'])
        self.assertEqual(projector.get_channel(), (600, "One-Port HDMI0"))

    def test_copy_channel_without_destination_omits_it(self):
        projector = _projector()
        projector.copy_channel(600)
        self.assertEqual(bytes(projector._client._sock.sent), b"(CHA+COPY 600)")

    def test_copy_channel_with_destination(self):
        projector = _projector()
        projector.copy_channel(600, 601)
        self.assertEqual(bytes(projector._client._sock.sent), b"(CHA+COPY 600 601)")


class LensTests(unittest.TestCase):
    """FCS/ZOM/LHO/LVO are plain absolute-position codes with no published
    range -- these methods pass values through rather than validating them,
    which matches how the Control4 driver's lens commands treat them too."""

    def test_get_focus(self):
        self.assertEqual(_projector([b"(FCS!-267)"]).get_focus(), -267)

    def test_set_focus_sends_position(self):
        projector = _projector()
        projector.set_focus(-267)
        self.assertEqual(bytes(projector._client._sock.sent), b"(FCS -267)")

    def test_get_zoom(self):
        self.assertEqual(_projector([b"(ZOM!100)"]).get_zoom(), 100)

    def test_set_zoom_sends_position(self):
        projector = _projector()
        projector.set_zoom(100)
        self.assertEqual(bytes(projector._client._sock.sent), b"(ZOM 100)")

    def test_get_lens_horizontal(self):
        self.assertEqual(_projector([b"(LHO!0)"]).get_lens_horizontal(), 0)

    def test_set_lens_horizontal_sends_position(self):
        projector = _projector()
        projector.set_lens_horizontal(-50)
        self.assertEqual(bytes(projector._client._sock.sent), b"(LHO -50)")

    def test_get_lens_vertical(self):
        self.assertEqual(_projector([b"(LVO!25)"]).get_lens_vertical(), 25)

    def test_set_lens_vertical_sends_position(self):
        projector = _projector()
        projector.set_lens_vertical(25)
        self.assertEqual(bytes(projector._client._sock.sent), b"(LVO 25)")

    def test_calibrate_lens_all_sends_bare_lcb(self):
        projector = _projector()
        projector.calibrate_lens()
        self.assertEqual(bytes(projector._client._sock.sent), b"(LCB)")

    def test_home_lens_sends_lcb_home(self):
        projector = _projector()
        projector.home_lens()
        self.assertEqual(bytes(projector._client._sock.sent), b"(LCB+HOME)")


class TestPatternTests(unittest.TestCase):
    def test_get_test_pattern_returns_value_and_name(self):
        projector = _projector([b'(ITP!000 "Off")'])
        self.assertEqual(projector.get_test_pattern(), (0, "Off"))

    def test_set_test_pattern_by_number(self):
        projector = _projector()
        projector.set_test_pattern(9)
        self.assertEqual(bytes(projector._client._sock.sent), b"(ITP 9)")

    def test_set_test_pattern_by_name(self):
        projector = _projector()
        projector.set_test_pattern("Color Bars")
        self.assertEqual(bytes(projector._client._sock.sent), b"(ITP 9)")

    def test_set_test_pattern_unknown_name_raises_without_sending(self):
        projector = _projector()
        with self.assertRaises(ValueError):
            projector.set_test_pattern("Not A Real Pattern")
        self.assertEqual(bytes(projector._client._sock.sent), b"")

    def test_set_test_pattern_rejected_in_standby_raises_christie_error(self):
        projector = _projector([b'(65535 00000 ERR00105 "ITP: Disabled Control")'])
        with self.assertRaises(ChristieError):
            projector.set_test_pattern(0)


class StatusTests(unittest.TestCase):
    def test_get_status_pairs_value_and_label(self):
        projector = _projector([b'(SST+SYST!"3:14 (h:m)" "Projector Hours")'])
        self.assertEqual(projector.get_status("SYST"), {"Projector Hours": "3:14 (h:m)"})

    def test_get_status_unknown_group_raises(self):
        projector = _projector()
        with self.assertRaises(ValueError):
            projector.get_status("NOPE")

    def test_get_status_no_status_items_returns_empty_dict(self):
        # ALRM answers error 9 ("No status items") when nothing is wrong --
        # a healthy empty result, not a failure.
        projector = _projector([b'(65535 00000 ERR00009 "No status items")'])
        self.assertEqual(projector.get_status("ALRM"), {})

    def test_get_status_other_error_propagates(self):
        projector = _projector([b'(65535 00000 ERR00101 "Control Not Found")'])
        with self.assertRaises(ChristieError):
            projector.get_status("SYST")

    def test_get_hours_reads_from_syst_group(self):
        projector = _projector([b'(SST+SYST!"3:14 (h:m)" "Projector Hours")'])
        self.assertEqual(projector.get_hours(), "3:14 (h:m)")

    def test_get_model_and_serial_read_from_conf_group(self):
        projector = _projector(
            [
                b'(SST+CONF!"Christie M 4K25 RGB" "Projector Model")',
                b'(SST+CONF!"12345" "Projector S/N")',
            ]
        )
        self.assertEqual(projector.get_model(), "Christie M 4K25 RGB")


class EscapeHatchTests(unittest.TestCase):
    def test_raw_query_sends_bare_code(self):
        projector = _projector([b"(GAM!002)"])
        self.assertEqual(projector.raw_query("GAM"), "002")
        self.assertEqual(bytes(projector._client._sock.sent), b"(GAM?)")

    def test_raw_query_with_subcode(self):
        projector = _projector([b"(LAS+WHTX!100)"])
        projector.raw_query("LAS", "WHTX")
        self.assertEqual(bytes(projector._client._sock.sent), b"(LAS+WHTX?)")

    def test_raw_set_sends_data(self):
        projector = _projector()
        projector.raw_set("CON", data=64)
        self.assertEqual(bytes(projector._client._sock.sent), b"(CON 64)")


class SnapshotTests(unittest.TestCase):
    """snapshot() is the single source of truth both the CLI's `json`
    command and (later) Home Assistant's coordinator poll from -- it must
    stay a thin gather-and-return with no reachability handling of its own,
    since callers decide how to report "unreachable"."""

    def test_snapshot_gathers_every_field(self):
        projector = _projector(
            [
                b'(PWR!001 "On")',
                # get_status("CONF") -- a real multi-message SST reply, so
                # each group needs a TIMEOUT sentinel to end its read; a
                # shared socket otherwise has no way to tell where one
                # group's reply stops and the next begins.
                b'(SST+CONF!"Christie M 4K25 RGB" "Projector Model")',
                b'(SST+CONF!"12345" "Projector S/N")',
                TIMEOUT,
                # get_status("SYST")
                b'(SST+SYST!"3:14 (h:m)" "Projector Hours")',
                TIMEOUT,
                # get_status("TEMP")
                b'(SST+TEMP!"32 \xc2\xb0C" "Air Intake Temperature (Temp 2)")',
                TIMEOUT,
                # get_input()
                b'(SIN!001 "One-Port HDMI0")',
                # get_test_pattern()
                b'(ITP!000 "Off")',
                # get_focus() / get_zoom() / get_lens_horizontal() / get_lens_vertical()
                b"(FCS!1100)",
                b"(ZOM!-267)",
                b"(LHO!-1032)",
                b"(LVO!-1417)",
                # is_shutter_open()
                b"(SHU!000)",
                # get_status("ALRM") -- healthy/empty; the error is the
                # *first* message, so it raises before the idle-read loop
                # even starts -- no TIMEOUT sentinel needed here.
                b'(65535 00000 ERR00009 "No status items")',
                # get_brightness()
                b"(LAS+POWR!700)",
                # get_liteloc()
                b'(LAS+STAT!003 "Enabled")',
            ]
        )

        snap = projector.snapshot()

        self.assertIsInstance(snap, Snapshot)
        self.assertEqual(snap.power, "On")
        self.assertEqual(snap.power_code, 1)
        self.assertTrue(snap.is_on)
        self.assertFalse(snap.in_transition)
        self.assertTrue(snap.shutter_open)
        self.assertEqual(snap.input, 1)
        self.assertEqual(snap.input_name, "One-Port HDMI0")
        self.assertEqual(snap.input_label, "HDMI 2.0 Port 1")
        self.assertIn("HDMI 2.1 Port 3", snap.inputs)
        self.assertEqual(snap.input_map["HDMI 2.1 Port 3"], 3)
        self.assertEqual(snap.hours, "3:14 (h:m)")
        self.assertEqual(snap.model, "Christie M 4K25 RGB")
        self.assertEqual(snap.serial, "12345")
        self.assertEqual(snap.alarms, 0)
        self.assertEqual(snap.brightness, 70.0)
        self.assertTrue(snap.liteloc)
        self.assertEqual(snap.test_pattern, "Off")
        self.assertIn("Color Bars", snap.test_patterns)
        self.assertEqual(snap.test_pattern_map["Color Bars"], 9)
        self.assertEqual(snap.focus, 1100)
        self.assertEqual(snap.zoom, -267)
        self.assertEqual(snap.lens_horizontal, -1032)
        self.assertEqual(snap.lens_vertical, -1417)
        self.assertEqual(snap.intake_temp, 32.0)

    def test_snapshot_in_transition_for_warming(self):
        projector = _projector(
            [
                b'(PWR!011 "Warming Up")',
                b'(SST+CONF!"Christie M 4K25 RGB" "Projector Model")',
                b'(SST+CONF!"12345" "Projector S/N")',
                TIMEOUT,
                b'(65535 00000 ERR00009 "No status items")',
                b'(65535 00000 ERR00009 "No status items")',
                b'(SIN!001 "One-Port HDMI0")',
                b'(ITP!000 "Off")',
                b"(FCS!0)",
                b"(ZOM!0)",
                b"(LHO!0)",
                b"(LVO!0)",
                b"(SHU!000)",
                b'(65535 00000 ERR00009 "No status items")',
                b"(LAS+POWR!700)",
                b'(LAS+STAT!003 "Enabled")',
            ]
        )
        snap = projector.snapshot()
        self.assertTrue(snap.in_transition)
        self.assertFalse(snap.is_on)
        self.assertIsNone(snap.intake_temp)

    def test_snapshot_unlisted_input_falls_back_to_projector_name(self):
        # An index outside INPUTS (different option module, newer firmware)
        # should still be labelled, with the projector's own name for it.
        projector = _projector(
            [
                b'(PWR!001 "On")',
                b'(SST+CONF!"Christie M 4K25 RGB" "Projector Model")',
                b'(SST+CONF!"12345" "Projector S/N")',
                TIMEOUT,
                b'(65535 00000 ERR00009 "No status items")',
                b'(65535 00000 ERR00009 "No status items")',
                b'(SIN!012 "One-Port NEW")',
                b'(ITP!000 "Off")',
                b"(FCS!0)",
                b"(ZOM!0)",
                b"(LHO!0)",
                b"(LVO!0)",
                b"(SHU!000)",
                b'(65535 00000 ERR00009 "No status items")',
                b"(LAS+POWR!700)",
                b'(LAS+STAT!003 "Enabled")',
            ]
        )
        snap = projector.snapshot()
        self.assertEqual(snap.input, 12)
        self.assertEqual(snap.input_label, "One-Port NEW")
        self.assertNotIn("One-Port NEW", snap.inputs)


if __name__ == "__main__":
    unittest.main()
