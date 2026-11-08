"""Tests for the ChristieM4K25 domain layer -- no network, no real projector
required. client.py's parsing/framing is covered by test_protocol.py; this
file covers projector.py's higher-level methods built on top of it.
"""

import unittest

from conftest import TIMEOUT, FakeSocket

from christie_mseries.exceptions import ChristieError
from christie_mseries.projector import (
    INPUTS,
    INPUTS_BY_NAME,
    THREE_D_DARK_INTERVAL_MAX,
    THREE_D_DARK_INTERVAL_MIN,
    THREE_D_EMITTER_DELAY_MAX,
    THREE_D_EMITTER_DELAY_MIN,
    THREE_D_MODES,
    THREE_D_MODES_BY_NAME,
    THREE_D_SYNC_OUTPUTS,
    THREE_D_SYNC_OUTPUTS_BY_NAME,
    THREE_D_TIMING_MODES,
    ChristieM4K25,
    PowerState,
    Snapshot,
)


def _projector(chunks=()):
    projector = ChristieM4K25("projector.invalid")
    projector._client._sock = FakeSocket(chunks)
    return projector


# What snapshot() reads for 3D, in order: the six controls, then the SIGN
# status group. 3D off, nothing displayed -- the reading when idle.
THREE_D_OFF = [
    b'(TDM!000 "Off")',
    b'(TDO!000 "To Emitter")',
    b"(TDD!000)",
    b"(DRK!1500)",
    b"(TDN!000)",
    b"(TDT!000)",
    b'(SST+SIGN!"96.00Hz" "Output Frequency")',
    b'(SST+SIGN!"N/A" "3D Sync")',
    b'(SST+SIGN!"N/A" "3D Darktime Status")',
    TIMEOUT,
]


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
                *THREE_D_OFF,
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
                *THREE_D_OFF,
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
                *THREE_D_OFF,
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


class ThreeDTests(unittest.TestCase):
    """The six 3D controls. Names, numbers and ranges are the ones read back
    from a physical M 4K25 RGB, not the API doc's tables."""

    @staticmethod
    def _sent(projector):
        return bytes(projector._client._sock.sent)

    def test_tables_match_what_the_projector_reported(self):
        self.assertEqual(
            THREE_D_MODES,
            {
                0: "Off",
                1: "Auto Detect",
                2: "Multi-Flash 3D",
                3: "Side-by-Side 3D",
                5: "Top-and-Bottom 3D",
                6: "Frame Packing 3D",
            },
        )
        self.assertEqual(THREE_D_SYNC_OUTPUTS, {0: "To Emitter", 1: "To Next Input"})
        self.assertEqual(THREE_D_TIMING_MODES, {3, 5, 6})

    def test_names_are_unique_so_the_reverse_lookups_are_complete(self):
        self.assertEqual(len(THREE_D_MODES_BY_NAME), len(THREE_D_MODES))
        self.assertEqual(len(THREE_D_SYNC_OUTPUTS_BY_NAME), len(THREE_D_SYNC_OUTPUTS))

    def test_get_3d_mode_returns_value_and_name(self):
        projector = _projector([b'(TDM!003 "Side-by-Side 3D")'])
        self.assertEqual(projector.get_3d_mode(), (3, "Side-by-Side 3D"))

    def test_set_3d_mode_by_number(self):
        projector = _projector()
        projector.set_3d_mode(6)
        self.assertEqual(self._sent(projector), b"(TDM 6)")

    def test_set_3d_mode_by_name(self):
        projector = _projector()
        projector.set_3d_mode("Top-and-Bottom 3D")
        self.assertEqual(self._sent(projector), b"(TDM 5)")

    def test_set_3d_mode_unknown_name_raises_without_sending(self):
        projector = _projector()
        with self.assertRaises(ValueError):
            projector.set_3d_mode("Native 3D")  # the API doc's name for 1, not this unit's
        self.assertEqual(self._sent(projector), b"")

    def test_set_3d_mode_unknown_number_is_left_for_the_projector_to_reject(self):
        projector = _projector([b'(65535 00000 ERR00104 "TDM: Invalid Value")'])
        with self.assertRaises(ChristieError) as ctx:
            projector.set_3d_mode(4)
        self.assertEqual(ctx.exception.code, 104)

    def test_get_and_set_3d_sync_output(self):
        projector = _projector([b'(TDO!001 "To Next Input")'])
        self.assertEqual(projector.get_3d_sync_output(), (1, "To Next Input"))
        projector = _projector()
        projector.set_3d_sync_output("To Next Input")
        self.assertEqual(self._sent(projector), b"(TDO 1)")

    def test_set_3d_sync_output_unknown_name_raises_without_sending(self):
        projector = _projector()
        with self.assertRaises(ValueError):
            projector.set_3d_sync_output("To Nowhere")
        self.assertEqual(self._sent(projector), b"")

    def test_timing_controls_are_disabled_outside_the_packed_modes(self):
        projector = _projector([b'(65535 00000 ERR00105 "TDO: Disabled Control")'])
        with self.assertRaises(ChristieError) as ctx:
            projector.set_3d_sync_output(0)
        self.assertEqual(ctx.exception.code, 105)

    def test_emitter_delay_round_trips_including_negative(self):
        projector = _projector([b"(TDD!-250)"])
        self.assertEqual(projector.get_3d_emitter_delay(), -250)
        projector = _projector()
        projector.set_3d_emitter_delay(-250)
        self.assertEqual(self._sent(projector), b"(TDD -250)")

    def test_emitter_delay_accepts_both_ends_of_its_range(self):
        for value in (THREE_D_EMITTER_DELAY_MIN, 0, THREE_D_EMITTER_DELAY_MAX):
            projector = _projector()
            projector.set_3d_emitter_delay(value)
            self.assertEqual(self._sent(projector), b"(TDD %d)" % value)

    def test_emitter_delay_outside_its_range_raises_instead_of_being_clamped(self):
        # The projector would answer 1001 with a silent clamp to 1000.
        for value in (THREE_D_EMITTER_DELAY_MIN - 1, THREE_D_EMITTER_DELAY_MAX + 1):
            projector = _projector()
            with self.assertRaises(ValueError):
                projector.set_3d_emitter_delay(value)
            self.assertEqual(self._sent(projector), b"")

    def test_dark_interval_accepts_both_ends_of_its_range(self):
        for value in (THREE_D_DARK_INTERVAL_MIN, 1500, THREE_D_DARK_INTERVAL_MAX):
            projector = _projector()
            projector.set_3d_dark_interval(value)
            self.assertEqual(self._sent(projector), b"(DRK %d)" % value)

    def test_dark_interval_outside_its_range_raises_instead_of_being_clamped(self):
        for value in (THREE_D_DARK_INTERVAL_MIN - 1, THREE_D_DARK_INTERVAL_MAX + 1):
            projector = _projector()
            with self.assertRaises(ValueError):
                projector.set_3d_dark_interval(value)
            self.assertEqual(self._sent(projector), b"")

    def test_get_dark_interval(self):
        self.assertEqual(_projector([b"(DRK!1500)"]).get_3d_dark_interval(), 1500)

    def test_input_inversion(self):
        self.assertTrue(_projector([b"(TDN!001)"]).is_3d_input_inverted())
        self.assertFalse(_projector([b"(TDN!000)"]).is_3d_input_inverted())
        projector = _projector()
        projector.set_3d_input_inverted(True)
        self.assertEqual(self._sent(projector), b"(TDN 1)")

    def test_3d_test_pattern(self):
        self.assertTrue(_projector([b"(TDT!001)"]).is_3d_test_pattern_enabled())
        projector = _projector()
        projector.enable_3d_test_pattern()
        projector.disable_3d_test_pattern()
        self.assertEqual(self._sent(projector), b"(TDT 1)(TDT 0)")

    def test_3d_status_reads_the_sign_group(self):
        projector = _projector(
            [
                b'(SST+SIGN!"96.00Hz" "Output Frequency")',
                b'(SST+SIGN!"Locked" "3D Sync")',
                b'(SST+SIGN!"Achieved" "3D Darktime Status")',
                TIMEOUT,
            ]
        )
        self.assertEqual(projector.get_3d_status(), {"sync": "Locked", "darktime": "Achieved"})

    def test_3d_status_is_empty_strings_when_the_group_lacks_the_items(self):
        projector = _projector([b'(SST+SIGN!"96.00Hz" "Output Frequency")', TIMEOUT])
        self.assertEqual(projector.get_3d_status(), {"sync": "", "darktime": ""})

    def test_setting_the_dark_interval_survives_the_projectors_darktime_warning(self):
        # Captured from a unit: lengthening DRK made it volunteer these two
        # frames. The SET succeeded; neither is an error.
        projector = _projector(
            [
                b'(65535 00000 ERR00000 "System Warning: \\(SST+SIGN?054\\) '
                b'3D Darktime Status = Not Achieved")',
                b'(65535 00000 FYI00000 "\\(SST+SIGN?054\\) 3D Darktime Status = Achieved")',
            ]
        )
        projector.set_3d_dark_interval(3000)  # must not raise
        self.assertEqual(self._sent(projector), b"(DRK 3000)")

    def test_a_notice_ahead_of_a_reply_is_not_mistaken_for_it(self):
        projector = _projector(
            [
                b'(65535 00000 FYI00000 "\\(SST+SIGN?054\\) 3D Darktime Status = Achieved")',
                b"(DRK!2000)",
            ]
        )
        self.assertEqual(projector.get_3d_dark_interval(), 2000)


class ThreeDSnapshotTests(unittest.TestCase):
    """snapshot() carries the 3D state, so callers never re-gather it."""

    @staticmethod
    def _snapshot(three_d):
        return _projector(
            [
                b'(PWR!001 "On")',
                b'(SST+CONF!"Christie M 4K25 RGB" "Projector Model")',
                b'(SST+CONF!"12345" "Projector S/N")',
                TIMEOUT,
                b'(65535 00000 ERR00009 "No status items")',
                b'(65535 00000 ERR00009 "No status items")',
                b'(SIN!003 "One-Port VOM-HDMI")',
                b'(ITP!000 "Off")',
                b"(FCS!0)",
                b"(ZOM!0)",
                b"(LHO!0)",
                b"(LVO!0)",
                *three_d,
                b"(SHU!000)",
                b'(65535 00000 ERR00009 "No status items")',
                b"(LAS+POWR!700)",
                b'(LAS+STAT!003 "Enabled")',
            ]
        ).snapshot()

    def test_idle_projector(self):
        snap = self._snapshot(THREE_D_OFF)
        self.assertEqual(snap.three_d_mode, "Off")
        self.assertFalse(snap.three_d_timing)
        self.assertEqual(snap.three_d_sync_output, "To Emitter")
        self.assertEqual(snap.three_d_emitter_delay, 0)
        self.assertEqual(snap.three_d_dark_interval, 1500)
        self.assertFalse(snap.three_d_input_inverted)
        self.assertFalse(snap.three_d_test_pattern)
        self.assertEqual(snap.three_d_sync, "N/A")
        self.assertEqual(snap.three_d_darktime, "N/A")
        self.assertIn("Frame Packing 3D", snap.three_d_modes)
        self.assertEqual(snap.three_d_mode_map["Side-by-Side 3D"], 3)
        self.assertEqual(snap.three_d_sync_output_map["To Next Input"], 1)

    def test_packed_mode_with_everything_set(self):
        snap = self._snapshot(
            [
                b'(TDM!003 "Side-by-Side 3D")',
                b'(TDO!001 "To Next Input")',
                b"(TDD!-120)",
                b"(DRK!2500)",
                b"(TDN!001)",
                b"(TDT!001)",
                b'(SST+SIGN!"Locked" "3D Sync")',
                b'(SST+SIGN!"Not Achieved" "3D Darktime Status")',
                TIMEOUT,
            ]
        )
        self.assertEqual(snap.three_d_mode, "Side-by-Side 3D")
        self.assertTrue(snap.three_d_timing)
        self.assertEqual(snap.three_d_sync_output, "To Next Input")
        self.assertEqual(snap.three_d_emitter_delay, -120)
        self.assertEqual(snap.three_d_dark_interval, 2500)
        self.assertTrue(snap.three_d_input_inverted)
        self.assertTrue(snap.three_d_test_pattern)
        self.assertEqual(snap.three_d_sync, "Locked")
        self.assertEqual(snap.three_d_darktime, "Not Achieved")

    def test_timing_flag_follows_the_mode_number_for_every_mode(self):
        for value, name in THREE_D_MODES.items():
            three_d = [b'(TDM!%03d "%s")' % (value, name.encode())] + THREE_D_OFF[1:]
            self.assertEqual(self._snapshot(three_d).three_d_timing, value in {3, 5, 6}, name)

    def test_a_refused_sign_group_does_not_fail_the_whole_snapshot(self):
        three_d = THREE_D_OFF[:6] + [b'(65535 00000 ERR00105 "SST: Disabled Control")']
        snap = self._snapshot(three_d)
        self.assertEqual(snap.three_d_sync, "")
        self.assertEqual(snap.three_d_darktime, "")
        self.assertEqual(snap.brightness, 70.0)  # later reads still lined up

    def test_a_snapshot_built_without_3d_fields_still_has_usable_defaults(self):
        # Callers and fixtures written before 3D support construct Snapshot
        # directly; they must not have to know about the new fields.
        self.assertIn("Off", Snapshot.__dataclass_fields__["three_d_modes"].default_factory())
