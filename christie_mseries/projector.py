"""High-level control of a Christie M 4K25 RGB.

Every command code and subcode used here was verified against a physical
M 4K25 RGB (software 1.3.9, re-verified on 1.3.10) by querying it directly.
That matters because this unit runs Christie's TruLife+ platform, which
implements only about a third of the codes in the M Series serial API doc
(020-100224-11) that this library was first written from -- see README for
the confirmed-absent list.

Codes here come from two sources: the doc, and the projector's own menu tree
as dumped by examples/dump_menu.py into docs/menu-map.json. The menu is the
better source, because a code that takes a subcode answers "Control Not
Found" when queried bare -- LAS, WRP and NET all do -- so sweeping the whole
three-letter space over the serial API cannot discover them. That is how
LAS+POWR (Brightness) was missed until the menu was read.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .client import DEFAULT_PORT, ChristieClient, parse_quoted
from .exceptions import ChristieError

# Returned by a status group that exists but currently holds nothing, which
# is how ALRM reports "no alarms".
_ERR_NO_STATUS_ITEMS = 9

# LAS+POWR accepts 0-1000 (tenths of a percent). The projector publishes a
# soft minimum of 200, i.e. it will not run the lasers below 20%.
#
# The floor enforced here is deliberately higher than that. Christie's own
# release notes (v1.3.9 and v1.3.10, both unresolved) list as a known issue
# that "LiteLOC performance is compromised when running at low brightness
# levels (30% or less) ... laser devices may shut down and colors may drop
# out", and recommend against running there at all. Since LiteLOC is enabled
# on this unit, 20-30% is a range the hardware accepts but the vendor says
# not to use, so it is refused rather than offered.
BRIGHTNESS_MIN_PERCENT = 30.0
BRIGHTNESS_MAX_PERCENT = 100.0

# LAS+STAT is not a plain boolean: it reports 3 for on and 1 for off.
_LITELOC_DISABLED = 1
_LITELOC_ENABLED = 3


class PowerState(IntEnum):
    """Values returned by ChristieM4K25.get_power_state() (PWR?). The
    COOLING/WARMING/AUTO_SHUTDOWN_* values are read-only -- they reflect a
    transition the projector is already in rather than states you can set.

    Only STANDBY is confirmed against hardware; the rest come from the API
    doc and can't be observed without power-cycling the projector.
    """

    STANDBY = 0
    ON = 1
    COOLING = 10
    WARMING = 11
    AUTO_SHUTDOWN_1 = 20
    AUTO_SHUTDOWN_2 = 21
    AUTO_SHUTDOWN_3 = 22
    EMERGENCY_SHUTDOWN = 23


class LensAxis(IntEnum):
    """Selects which LCB+xxxx calibration subcode to use."""

    ALL = 0
    HORIZONTAL = 1
    VERTICAL = 2
    FOCUS = 3
    ZOOM = 4


_LENS_AXIS_SUBCODE = {
    LensAxis.HORIZONTAL: "HORZ",
    LensAxis.VERTICAL: "VERT",
    LensAxis.FOCUS: "FOCS",
    LensAxis.ZOOM: "ZOOM",
}

# Confirmed by probing SST+<group> on the M 4K25. The doc's HLTH and LAMP
# groups do not exist here ("Cannot find status group"); LGHT is not in the
# doc but does exist, and carries the laser/light-source readings. ALRM is a
# real group that is simply empty when nothing is wrong.
STATUS_GROUPS = ("ALRM", "CONF", "COOL", "LGHT", "SIGN", "SYST", "TEMP", "VERS")


# ITP values and names exactly as the projector's own menu lists them (the
# `list` on the ITP node in docs/menu-map.json). The API doc's numbering does
# not match this platform -- it lists 8 as Color Bars and 14 as Boresight,
# where this unit answers Edge Blend and Diagonal Ramp, and puts Boresight
# at 21. The gaps are real: 20 and 22 are rejected as "Invalid Value".
TEST_PATTERNS = {
    0: "Off",
    1: "Grid",
    2: "Gray Scale 16",
    3: "Flat White",
    4: "Flat Gray",
    5: "Flat Black",
    6: "Checker",
    7: "17 Point",
    8: "Edge Blend",
    9: "Color Bars",
    10: "Multi-color",
    11: "RGBW Ramp",
    12: "Horizontal Ramp",
    13: "Vertical Ramp",
    14: "Diagonal Ramp",
    15: "Square Grid",
    16: "Diagonal Grid",
    18: "Prism / Convergence",
    21: "Boresight",
    23: "Integrator Rod",
    28: "Electronic Convergence",
}

# Accepted by ITP but deliberately not offered above, because the projector's
# own menu (docs/menu-map.json) does not list them: 17 "Maximum Activity",
# 19 "FLIR" and 24 "Flare". Pass the number to set_test_pattern() to use one.

TEST_PATTERNS_BY_NAME = {name: value for value, name in TEST_PATTERNS.items()}


# SIN index -> the physical port it selects, for a unit fitted with the
# Variable Option Module (VOM). The projector itself only reports its own
# names ("One-Port VOM-HDMI", see get_input()), which don't say which
# connector they mean; these labels do. They come from the port names in the
# projector's Input Settings menu (the `EDC+HDCV`/`HDVO`/`DPCV`/`DPVO` nodes
# in docs/menu-map.json: "HDMI 2.0 Port 1 and 2", "HDMI 2.1 Port 3",
# "DisplayPort 1.2 Port 1 and 2", "DisplayPort 1.4 Port 3 and 4"). The HDMI
# 2.1 = index 3 mapping is confirmed on hardware; which DisplayPort index is
# which port of its pair (4-7) is inferred from the order the projector
# reports them, not checked against a cable. Names must stay unique, since
# INPUTS_BY_NAME is a reverse lookup.
INPUTS = {
    1: "HDMI 2.0 Port 1",
    2: "HDMI 2.0 Port 2",
    3: "HDMI 2.1 Port 3",
    4: "DisplayPort 1.4 Port 3",
    5: "DisplayPort 1.4 Port 4",
    6: "DisplayPort 1.2 Port 1",
    7: "DisplayPort 1.2 Port 2",
    8: "SDI 1",
    9: "SDI 2",
    10: "SDI 3",
    11: "SDI 4",
}

INPUTS_BY_NAME = {name: value for value, name in INPUTS.items()}


class GeometryWarp(IntEnum):
    """WRP+SLCT -- which warp map is active. Values 2-17 select a
    user-loaded Twist warp by slot number; pass a plain int (not this enum)
    for those to set_geometry_warp()."""

    OFF = 0
    KEYSTONE_2D = 1


@dataclass
class Snapshot:
    """Everything worth polling in one shot, gathered with one connection.

    Bundles the handful of reads a poller wants every cycle -- the CLI's
    `json` command, and Home Assistant's coordinator -- so callers don't have
    to remember which status group backs which field. Returned by
    ChristieM4K25.snapshot(); see that method for how "unreachable" should be
    reported by callers that poll on an interval.
    """

    power: str
    power_code: int
    is_on: bool
    in_transition: bool
    shutter_open: bool
    input: int
    input_name: str
    input_label: str
    inputs: list[str]
    input_map: dict[str, int]
    hours: str
    model: str
    serial: str
    alarms: int
    brightness: float
    liteloc: bool
    test_pattern: str
    test_patterns: list[str]
    test_pattern_map: dict[str, int]
    focus: int
    zoom: int
    lens_horizontal: int
    lens_vertical: int
    intake_temp: float | None = None


class ChristieM4K25:
    """Control a Christie M 4K25 RGB over its Ethernet serial API (TCP 3002).

    >>> with ChristieM4K25("192.0.2.50") as projector:
    ...     projector.get_power_state()
    <PowerState.STANDBY: 0>
    ...     projector.get_input()
    (1, 'One-Port HDMI0')
    """

    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = 5.0):
        """Create a client for the projector at `host`. Does not connect --
        call connect() or use as a context manager."""
        self._client = ChristieClient(host, port=port, timeout=timeout)

    def connect(self) -> None:
        """Open the TCP connection to the projector's serial API port."""
        self._client.connect()

    def close(self) -> None:
        """Close the TCP connection."""
        self._client.close()

    def __enter__(self) -> ChristieM4K25:
        """Connect on entering a `with` block."""
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        """Close the connection on leaving a `with` block."""
        self.close()

    # -- Power -----------------------------------------------------------

    def power_on(self, wait: bool = False) -> None:
        """Turn on the light source and all electrical power (PWR 1).

        With wait=True, blocks until the projector acknowledges the command
        as fully executed rather than just accepted -- set a longer client
        `timeout` since warm-up isn't instant."""
        self._client.set("PWR", data=1, ack=wait)

    def power_off(self, wait: bool = False) -> None:
        """Set the projector to Standby mode (PWR 0). See power_on() for
        what wait=True does."""
        self._client.set("PWR", data=0, ack=wait)

    def get_power_state(self) -> PowerState:
        """Current power state (PWR?), including transient states like
        COOLING/WARMING and the various auto/emergency shutdown stages."""
        return PowerState(self._client.query_int("PWR"))

    def get_power_state_text(self) -> str:
        """The projector's own wording for its power state, e.g. "Standby
        Mode". Preferred for display over PowerState.name, since it comes
        from the device rather than from the API doc."""
        _, text = self._client.query_value("PWR")
        return text or ""

    # -- Light source --------------------------------------------------------

    def get_brightness(self) -> float:
        """Light-source brightness as a percentage, e.g. 70.0 (LAS+POWR).

        This is the laser power control, the one the on-screen menu shows
        under Configuration > Light & Output Settings > Brightness. The
        projector stores it in tenths of a percent, so it answers 700 for 70%.
        """
        return self._client.query_int("LAS", "POWR") / 10.0

    def set_brightness(self, percent: float) -> None:
        """Set light-source brightness, as a percentage from 30.0 to 100.0.

        The control's hard range is 0-100% and the projector's own soft
        minimum is 20%, below which it will not run the lasers at all. The
        floor here is Christie's recommended one of 30% instead: below that
        they warn LiteLOC is compromised, lasers may shut down and colour may
        drop out. Anything lower is rejected rather than silently ignored.
        """
        if not BRIGHTNESS_MIN_PERCENT <= percent <= BRIGHTNESS_MAX_PERCENT:
            raise ValueError(
                f"Brightness must be between {BRIGHTNESS_MIN_PERCENT} and "
                f"{BRIGHTNESS_MAX_PERCENT} percent, got {percent}"
            )
        self._client.set("LAS", subcode="POWR", data=round(percent * 10))

    def get_liteloc(self) -> bool:
        """True when LiteLOC is enabled (LAS+STAT), which holds brightness and
        colour constant over time by trading off spare laser headroom."""
        return self._client.query_int("LAS", "STAT") == _LITELOC_ENABLED

    def set_liteloc(self, enabled: bool) -> None:
        """Enable or disable LiteLOC (LAS+STAT)."""
        self._client.set(
            "LAS",
            subcode="STAT",
            data=_LITELOC_ENABLED if enabled else _LITELOC_DISABLED,
        )

    # -- Shutter -----------------------------------------------------------

    def open_shutter(self) -> None:
        """Open the mechanical shutter, letting light reach the screen (SHU 0)."""
        self._client.set("SHU", data=0)

    def close_shutter(self) -> None:
        """Close the mechanical shutter, blocking all light to the screen (SHU 1)."""
        self._client.set("SHU", data=1)

    def is_shutter_open(self) -> bool:
        """True if the shutter is currently open (SHU?)."""
        return self._client.query_int("SHU") == 0

    # -- Input / channel selection -----------------------------------------

    def select_input(self, source: int | str) -> None:
        """Switch the main video input (SIN), by index 1 to 11 or by the
        label in INPUTS (e.g. "HDMI 2.1 Port 3").

        Note this is a plain SIN with a single index -- the SIN+MAIN
        slot/input subcode in the API doc does not exist on this platform.

        Rejected with "Disabled Control" while the projector is in standby;
        the input can be read then, but only changed once it is on.
        """
        if isinstance(source, str):
            if source not in INPUTS_BY_NAME:
                raise ValueError(f"Unknown input {source!r}; expected one of {list(INPUTS_BY_NAME)}")
            source = INPUTS_BY_NAME[source]
        self._client.set("SIN", data=int(source))

    def get_input(self) -> tuple[int, str]:
        """Current input as (index, name), e.g. (1, "One-Port HDMI0") (SIN?)."""
        index, name = self._client.query_value("SIN")
        return int(index or 0), name or ""

    def select_channel(self, channel: int) -> None:
        """Switch the active channel (CHA). A channel is the nearest thing
        this projector has to a "preset": it stores its own source routing
        and image settings."""
        self._client.set("CHA", data=channel)

    def get_channel(self) -> tuple[int, str]:
        """Active channel as (number, name), e.g. (600, "One-Port HDMI0") (CHA?)."""
        number, name = self._client.query_value("CHA")
        return int(number or 0), name or ""

    def copy_channel(self, source: int, destination: int | None = None) -> None:
        """Duplicate a channel's saved setup (CHA+COPY). If destination is
        omitted, the projector assigns the next free channel number; if
        given, the copy fails when that channel number is already in use."""
        data = source if destination is None else f"{source} {destination}"
        self._client.set("CHA", subcode="COPY", data=data)

    def delete_channel(self, channel: int) -> None:
        """Delete a channel's saved setup (CHA+DLET). Pass 0 to delete all
        unlocked channels."""
        self._client.set("CHA", subcode="DLET", data=channel)

    # -- Lens ----------------------------------------------------------------

    def calibrate_lens(self, axis: LensAxis = LensAxis.ALL) -> None:
        """Run lens calibration to (re)establish home position, travel
        range, and backlash for one axis, or all four with LensAxis.ALL."""
        self._client.set("LCB", subcode=_LENS_AXIS_SUBCODE.get(axis))

    def home_lens(self) -> None:
        """Return the lens to its horizontal/vertical home position (focus
        and zoom are unaffected)."""
        self._client.set("LCB", subcode="HOME")

    def get_focus(self) -> int:
        """Current lens focus motor position (FCS?), -1200 to 1200 (range
        may narrow after calibrate_lens())."""
        return self._client.query_int("FCS")

    def set_focus(self, position: int) -> None:
        """Move the lens focus motor to an absolute position (FCS)."""
        self._client.set("FCS", data=position)

    def get_zoom(self) -> int:
        """Current lens zoom motor position (ZOM?), -1200 to 1200."""
        return self._client.query_int("ZOM")

    def set_zoom(self, position: int) -> None:
        """Move the lens zoom motor to an absolute position (ZOM)."""
        self._client.set("ZOM", data=position)

    def get_lens_horizontal(self) -> int:
        """Current lens horizontal-shift motor position (LHO?)."""
        return self._client.query_int("LHO")

    def set_lens_horizontal(self, position: int) -> None:
        """Move the lens horizontally to an absolute position (LHO)."""
        self._client.set("LHO", data=position)

    def get_lens_vertical(self) -> int:
        """Current lens vertical-shift motor position (LVO?)."""
        return self._client.query_int("LVO")

    def set_lens_vertical(self, position: int) -> None:
        """Move the lens vertically to an absolute position (LVO)."""
        self._client.set("LVO", data=position)

    # -- Image ----------------------------------------------------------------

    def is_frozen(self) -> bool:
        """True if the image is frozen on the current frame (FRZ?)."""
        return self._client.query_int("FRZ") == 1

    def set_frozen(self, frozen: bool) -> None:
        """Freeze or unfreeze the image on the current frame (FRZ)."""
        self._client.set("FRZ", data=int(frozen))

    def get_test_pattern(self) -> tuple[int, str]:
        """Current internal test pattern as (value, name) (ITP?), e.g.
        (0, "Off"). See TEST_PATTERNS for the full list."""
        value, name = self._client.query_value("ITP")
        return int(value or 0), name or ""

    def set_test_pattern(self, pattern: int | str) -> None:
        """Display an internal test pattern, by value or by name -- pass 0 or
        "Off" to go back to the normal input signal (ITP).

        Rejected with "Disabled Control" while the projector is in standby;
        image controls only accept writes once it is on.
        """
        if isinstance(pattern, str):
            if pattern not in TEST_PATTERNS_BY_NAME:
                raise ValueError(
                    f"Unknown test pattern {pattern!r}; expected one of {sorted(TEST_PATTERNS_BY_NAME)}"
                )
            pattern = TEST_PATTERNS_BY_NAME[pattern]
        self._client.set("ITP", data=int(pattern))

    def get_geometry_warp(self) -> tuple[int, str]:
        """Active warp map as (value, name) (WRP+SLCT?): 0 = off, 1 = 2D
        keystone, 2-17 = a user-loaded Twist warp by slot number."""
        value, name = self._client.query_value("WRP", subcode="SLCT")
        return int(value or 0), name or ""

    def set_geometry_warp(self, warp: GeometryWarp | int) -> None:
        """Select the active warp map (WRP+SLCT). Pass a GeometryWarp value,
        or a plain int from 2 to 17 to select a user-loaded Twist warp by
        slot number."""
        self._client.set("WRP", subcode="SLCT", data=int(warp))

    def reset_keystone(self) -> None:
        """Reset the 2D keystone settings to zero (WRP+KRST)."""
        self._client.set("WRP", subcode="KRST")

    def auto_setup(self) -> None:
        """Automatically readjust video controls for the active source to
        produce an optimal image (ASU) -- the remote's auto-image button."""
        self._client.set("ASU")

    # -- 3D -------------------------------------------------------------------
    # These take no +MAIN subcode on this platform, unlike the API doc.

    def get_3d_mode(self) -> tuple[int, str]:
        """3D processing mode as (value, name) (TDM?), e.g. (1, "Auto
        Detect"). The doc's value table doesn't match this platform, so the
        projector's own name for the mode is the reliable half."""
        value, name = self._client.query_value("TDM")
        return int(value or 0), name or ""

    def set_3d_mode(self, mode: int) -> None:
        """Set the 3D processing mode (TDM). Read get_3d_mode() on a unit
        already in the mode you want to learn the right number."""
        self._client.set("TDM", data=mode)

    def get_3d_emitter_delay(self) -> int:
        """3D emitter delay in hundredths of a millisecond (TDD?) -- e.g.
        2000 = 20.00ms. Corrects cross-talk/color ghosting between active
        glasses and the projected frames."""
        return self._client.query_int("TDD")

    def set_3d_emitter_delay(self, delay: int) -> None:
        """Set the 3D emitter delay (TDD). See get_3d_emitter_delay() for units."""
        self._client.set("TDD", data=delay)

    def is_3d_input_inverted(self) -> bool:
        """True if 3D input inversion is on (TDN?) -- fixes left/right eyes
        being swapped."""
        return self._client.query_int("TDN") == 1

    def set_3d_input_inverted(self, inverted: bool) -> None:
        """Invert (or un-invert) the 3D input (TDN)."""
        self._client.set("TDN", data=int(inverted))

    def get_3d_sync_output(self) -> tuple[int, str]:
        """3D sync output mode on the GPIO port as (value, name) (TDO?),
        e.g. (0, "To Emitter")."""
        value, name = self._client.query_value("TDO")
        return int(value or 0), name or ""

    def set_3d_sync_output(self, value: int) -> None:
        """Set the 3D sync output mode (TDO)."""
        self._client.set("TDO", data=value)

    def get_3d_dark_interval(self) -> int:
        """3D dark interval in hundredths of a millisecond (DRK?) -- e.g.
        500 = 5.00ms. Increasing it reduces peak brightness."""
        return self._client.query_int("DRK")

    def set_3d_dark_interval(self, interval: int) -> None:
        """Set the 3D dark interval (DRK). See get_3d_dark_interval() for units."""
        self._client.set("DRK", data=interval)

    def is_3d_test_pattern_enabled(self) -> bool:
        """True if the 3D sync test pattern is currently on (TDT?)."""
        return self._client.query_int("TDT") == 1

    def enable_3d_test_pattern(self) -> None:
        """Enable the scrolling diagonal-line 3D sync test pattern, used to
        check left/right eye synchronization (TDT 1)."""
        self._client.set("TDT", data=1)

    def disable_3d_test_pattern(self) -> None:
        """Disable the 3D sync test pattern (TDT 0)."""
        self._client.set("TDT", data=0)

    # -- Network / identity ----------------------------------------------------

    def get_network(self) -> tuple[str, str, str]:
        """Current (ip_address, subnet_mask, gateway) (NET?)."""
        fields = parse_quoted(self._client.query("NET"))
        fields += [""] * (3 - len(fields))
        return fields[0], fields[1], fields[2]

    def get_address(self) -> int:
        """This projector's device address (ADR?), used to identify it in a
        daisy-chained network of projectors."""
        return self._client.query_int("ADR")

    def set_address(self, address: int) -> None:
        """Set this projector's device address (ADR), 0 to 999."""
        self._client.set("ADR", data=address)

    def ping(self) -> list[int]:
        """Identify the device (PNG?) -- returns the projector type and
        software version numbers the projector reports about itself."""
        data = self._client.query("PNG")
        return [int(part) for part in data.split() if part.lstrip("-").isdigit()]

    # -- Status / diagnostics ------------------------------------------------

    def get_status(self, group: str) -> dict[str, str]:
        """All status items in one of STATUS_GROUPS, as {label: value},
        e.g. get_status("SYST")["Projector Hours"] -> "3:14 (h:m)".

        A status group answers with one message per item, so this reads
        until the projector stops sending. Items sharing a label collapse
        to the last one seen. An empty group returns {} -- ALRM reports "No
        status items" when nothing is wrong, which is a healthy result
        rather than an error.
        """
        group = group.upper()
        if group not in STATUS_GROUPS:
            raise ValueError(f"Unknown status group {group!r}, expected one of {STATUS_GROUPS}")
        items: dict[str, str] = {}
        try:
            replies = self._client.query_multi("SST", subcode=group)
        except ChristieError as exc:
            if exc.code == _ERR_NO_STATUS_ITEMS:
                return items
            raise
        for data in replies:
            fields = parse_quoted(data)
            if len(fields) >= 2:
                items[fields[1]] = fields[0]
        return items

    def get_hours(self) -> str:
        """Total elapsed operating hours, as the projector formats it, e.g.
        "3:14 (h:m)". Read from the SYST status group -- the API doc's
        dedicated PJH code does not exist on this platform."""
        return self.get_status("SYST").get("Projector Hours", "")

    def get_model(self) -> str:
        """Projector model name, e.g. "Christie M 4K25 RGB" (SST+CONF)."""
        return self.get_status("CONF").get("Projector Model", "")

    def get_serial_number(self) -> str:
        """Projector serial number (SST+CONF)."""
        return self.get_status("CONF").get("Projector S/N", "")

    def get_temperatures(self) -> dict[str, str]:
        """All temperature sensor readings as {label: value}, e.g.
        {"Air Intake Temperature (Temp 2)": "32 °C", ...} (SST+TEMP)."""
        return self.get_status("TEMP")

    # -- Polling ---------------------------------------------------------------

    def snapshot(self) -> Snapshot:
        """Gather everything worth polling in one shot: power, shutter,
        input, brightness, test pattern, lens positions, hours, identity,
        alarm count, and intake temperature.

        Raises like any other method here if a read fails or the connection
        drops mid-poll. Callers that want "unreachable" reported as data
        rather than an exception -- a fixed-interval poller like Home
        Assistant's coordinator, or the CLI's `json` command -- should catch
        around this call, the same way examples/cli.py's `as_json()` does,
        rather than this method swallowing errors itself.
        """
        code, text = self._client.query_value("PWR")
        config = self.get_status("CONF")
        system = self.get_status("SYST")
        temperatures = self.get_status("TEMP")
        index, name = self.get_input()
        pattern_value, pattern_name = self.get_test_pattern()
        focus = self.get_focus()
        zoom = self.get_zoom()
        lens_horizontal = self.get_lens_horizontal()
        lens_vertical = self.get_lens_vertical()

        intake_temp: float | None = None
        intake = temperatures.get("Air Intake Temperature (Temp 2)", "")
        digits = "".join(c for c in intake if c.isdigit() or c == ".")
        if digits:
            intake_temp = float(digits)

        return Snapshot(
            power=text or "",
            power_code=code if code is not None else -1,
            is_on=code == PowerState.ON,
            in_transition=code in (PowerState.COOLING, PowerState.WARMING),
            shutter_open=self.is_shutter_open(),
            input=index,
            input_name=name,
            # An index outside INPUTS (a different option module, or newer
            # firmware) falls back to the projector's own name for it.
            input_label=INPUTS.get(index) or name,
            inputs=list(INPUTS.values()),
            input_map={label: n for n, label in INPUTS.items()},
            hours=system.get("Projector Hours", ""),
            model=config.get("Projector Model", ""),
            serial=config.get("Projector S/N", ""),
            alarms=len(self.get_status("ALRM")),
            brightness=self.get_brightness(),
            liteloc=self.get_liteloc(),
            test_pattern=pattern_name or TEST_PATTERNS.get(pattern_value, "Off"),
            test_patterns=list(TEST_PATTERNS.values()),
            test_pattern_map={name: n for n, name in TEST_PATTERNS.items()},
            focus=focus,
            zoom=zoom,
            lens_horizontal=lens_horizontal,
            lens_vertical=lens_vertical,
            intake_temp=intake_temp,
        )

    # -- Escape hatch ---------------------------------------------------------

    def raw_query(self, code: str, subcode: str | None = None) -> str:
        """Send a REQUEST for any three-letter API code not wrapped by a
        named method above, and return the reply data as text. Use this to
        reach codes that exist on your unit but aren't wrapped here."""
        return self._client.query(code, subcode=subcode)

    def raw_set(self, code: str, subcode: str | None = None, data=None, ack: bool = False) -> None:
        """Send a SET for any three-letter API code not wrapped by a named
        method above. See ChristieClient.set() for what ack=True does."""
        self._client.set(code, subcode=subcode, data=data, ack=ack)
