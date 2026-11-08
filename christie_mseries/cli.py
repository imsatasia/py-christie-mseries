#!/usr/bin/env python3
"""Command-line tool for a Christie M 4K25 on the LAN. Installed as the
`christie-mseries` console script.

Usage:
    christie-mseries 192.0.2.50 status
    christie-mseries 192.0.2.50 json     # machine-readable, for Home Assistant
    christie-mseries 192.0.2.50 power-on
    christie-mseries 192.0.2.50 power-off
    christie-mseries 192.0.2.50 input 3                     # by SIN index
    christie-mseries 192.0.2.50 input "HDMI 2.1 Port 3"     # or by label
    christie-mseries 192.0.2.50 shutter open
    christie-mseries 192.0.2.50 brightness        # read laser power %
    christie-mseries 192.0.2.50 brightness 70     # set it (30-100)
    christie-mseries 192.0.2.50 3d                           # all 3D settings and status
    christie-mseries 192.0.2.50 3d-mode "Side-by-Side 3D"    # or by number; omit to read
    christie-mseries 192.0.2.50 3d-sync-output "To Emitter"  # needs a packed 3D mode
    christie-mseries 192.0.2.50 3d-delay -200                # needs a packed 3D mode
    christie-mseries 192.0.2.50 3d-dark-interval 1500        # needs a packed 3D mode
    christie-mseries 192.0.2.50 3d-invert on                 # not in a packed 3D mode
    christie-mseries 192.0.2.50 3d-test-pattern on
    christie-mseries 192.0.2.50 group TEMP
    christie-mseries 192.0.2.50 probe
    christie-mseries 192.0.2.50 raw 'GAM?'
"""

import argparse
import json

from christie_mseries import (
    BRIGHTNESS_MAX_PERCENT,
    BRIGHTNESS_MIN_PERCENT,
    INPUTS,
    STATUS_GROUPS,
    TEST_PATTERNS,
    THREE_D_TIMING_MODES,
    ChristieM4K25,
)
from christie_mseries.exceptions import ChristieError

# Every three-letter code in Christie's M Series API doc, used by `probe` to
# report which ones this particular unit implements.
DOC_CODES = [
    "ACE",
    "ACO",
    "ACT",
    "ADR",
    "AGC",
    "AIC",
    "AIL",
    "ALT",
    "APJ",
    "APW",
    "ARO",
    "ASH",
    "ASR",
    "ASU",
    "BBL",
    "BDR",
    "BGC",
    "BGF",
    "BGS",
    "BKY",
    "BLB",
    "BLD",
    "BOG",
    "BOO",
    "BRT",
    "BRU",
    "CCD",
    "CCI",
    "CCS",
    "CHA",
    "CLE",
    "CLP",
    "CLR",
    "CON",
    "CRM",
    "CSP",
    "DED",
    "DEQ",
    "DIM",
    "DIS",
    "DLG",
    "DMX",
    "DRK",
    "DTL",
    "DTO",
    "DTT",
    "EBB",
    "EBL",
    "EME",
    "ESC",
    "FAD",
    "FAS",
    "FCS",
    "FIL",
    "FLE",
    "FLW",
    "FMD",
    "FRD",
    "FRF",
    "FRZ",
    "FTB",
    "GAM",
    "GIA",
    "GID",
    "GIO",
    "GMS",
    "GNB",
    "GND",
    "GOG",
    "GOO",
    "HDC",
    "HIS",
    "HLP",
    "HLT",
    "HOR",
    "ILS",
    "ILV",
    "INM",
    "IRS",
    "ITG",
    "ITP",
    "KEN",
    "KEY",
    "LBL",
    "LCB",
    "LCD",
    "LDT",
    "LDV",
    "LHO",
    "LLC",
    "LMV",
    "LOC",
    "LOP",
    "LOS",
    "LPI",
    "LPL",
    "LPM",
    "LPP",
    "LRG",
    "LSF",
    "LVO",
    "MBE",
    "MCS",
    "MDE",
    "MFT",
    "MIP",
    "MLK",
    "MNR",
    "MNU",
    "MSH",
    "MSP",
    "MSV",
    "NAM",
    "NET",
    "NRB",
    "NRD",
    "NTR",
    "OPP",
    "OSD",
    "OST",
    "PBC",
    "PBW",
    "PDT",
    "PHP",
    "PHS",
    "PIP",
    "PJH",
    "PLK",
    "PMT",
    "PNG",
    "PPA",
    "PPP",
    "PPS",
    "PRT",
    "PTL",
    "PVP",
    "PWR",
    "PXP",
    "RAL",
    "RBL",
    "RDB",
    "RDD",
    "ROG",
    "ROO",
    "RQR",
    "RTE",
    "SHU",
    "SIN",
    "SIZ",
    "SMP",
    "SOR",
    "SPS",
    "SPT",
    "STD",
    "SZP",
    "TBL",
    "TDD",
    "TDI",
    "TDM",
    "TDN",
    "TDO",
    "TDT",
    "TED",
    "TIL",
    "TMD",
    "TNT",
    "TTM",
    "TXE",
    "UID",
    "VBL",
    "VRT",
    "VST",
    "WRP",
    "YNF",
    "ZOM",
]


def show_status(projector: ChristieM4K25) -> None:
    """Print the handful of readings worth seeing at a glance."""
    print("Model:       ", projector.get_model())
    print("Serial:      ", projector.get_serial_number())
    print("Power:       ", projector.get_power_state_text())
    print("Shutter:     ", "open" if projector.is_shutter_open() else "closed")
    print("Input:       ", "%d (%s)" % projector.get_input())
    print("Channel:     ", "%d (%s)" % projector.get_channel())
    print("Hours:       ", projector.get_hours())
    print("Test pattern:", "%d (%s)" % projector.get_test_pattern())
    alarms = projector.get_status("ALRM")
    print("Alarms:      ", ", ".join(f"{k}={v}" for k, v in alarms.items()) if alarms else "none")


def as_json(host: str) -> str:
    """One JSON object of everything worth polling, for Home Assistant.

    Never raises: an unreachable or mid-power-cycle projector reports
    {"available": false} rather than failing, so the caller can tell
    "cannot read it" apart from "it is off". Right after a power command the
    projector accepts a connection but answers nothing, which would
    otherwise look like a power state of off.
    """
    state: dict = {"available": False}
    try:
        with ChristieM4K25(host, timeout=8) as projector:
            snap = projector.snapshot()
            state = {
                "available": True,
                # Shipped with the poll so the Home Assistant select has one
                # source of truth for its options -- this library -- rather
                # than a second copy of the list in YAML.
                "test_pattern": snap.test_pattern,
                "test_patterns": snap.test_patterns,
                "test_pattern_map": snap.test_pattern_map,
                "power": snap.power,
                "power_code": snap.power_code,
                "is_on": snap.is_on,
                "in_transition": snap.in_transition,
                "shutter_open": snap.shutter_open,
                "input": snap.input,
                "input_name": snap.input_name,
                "input_label": snap.input_label,
                "inputs": snap.inputs,
                "input_map": snap.input_map,
                "hours": snap.hours,
                "model": snap.model,
                "serial": snap.serial,
                "alarms": snap.alarms,
                "brightness": snap.brightness,
                "brightness_min": BRIGHTNESS_MIN_PERCENT,
                "brightness_max": BRIGHTNESS_MAX_PERCENT,
                "liteloc": snap.liteloc,
                "focus": snap.focus,
                "zoom": snap.zoom,
                "lens_horizontal": snap.lens_horizontal,
                "lens_vertical": snap.lens_vertical,
                "three_d_mode": snap.three_d_mode,
                "three_d_modes": snap.three_d_modes,
                "three_d_mode_map": snap.three_d_mode_map,
                "three_d_timing": snap.three_d_timing,
                "three_d_sync_output": snap.three_d_sync_output,
                "three_d_sync_outputs": snap.three_d_sync_outputs,
                "three_d_sync_output_map": snap.three_d_sync_output_map,
                "three_d_emitter_delay": snap.three_d_emitter_delay,
                "three_d_dark_interval": snap.three_d_dark_interval,
                "three_d_input_inverted": snap.three_d_input_inverted,
                "three_d_test_pattern": snap.three_d_test_pattern,
                "three_d_sync": snap.three_d_sync,
                "three_d_darktime": snap.three_d_darktime,
            }
            if snap.intake_temp is not None:
                state["intake_temp"] = snap.intake_temp
    except Exception as exc:  # unreachable, mid-transition, or protocol error
        state["error"] = f"{type(exc).__name__}: {exc}"
    return json.dumps(state)


_THREE_D_COMMANDS = (
    "3d",
    "3d-mode",
    "3d-sync-output",
    "3d-delay",
    "3d-dark-interval",
    "3d-invert",
    "3d-test-pattern",
)

_ON_OFF = {"on": True, "1": True, "true": True, "off": False, "0": False, "false": False}


def _number_or_name(argument: str) -> int | str:
    """A bare number is a value; anything else is a name, which avoids
    quoting in a shell for callers that already have the number."""
    return int(argument) if argument.lstrip("-").isdigit() else argument


def run_3d(projector: ChristieM4K25, command: str, argument: str | None) -> str:
    """Read or set one 3D setting (or print them all for plain `3d`) and
    return the text to show. Raises ValueError on a bad argument and
    ChristieError if the projector refuses (e.g. a control that the current 3D
    mode disables)."""
    if command == "3d":
        mode_value, mode = projector.get_3d_mode()
        _, output = projector.get_3d_sync_output()
        status = projector.get_3d_status()
        timing = "enabled" if mode_value in THREE_D_TIMING_MODES else "disabled"
        return "\n".join(
            [
                f"3D mode:          {mode_value} ({mode})",
                f"Sync output:      {output}  (timing controls {timing} in this mode)",
                f"Sync delay:       {projector.get_3d_emitter_delay()}",
                f"Dark interval:    {projector.get_3d_dark_interval()}",
                f"Invert eyes:      {'on' if projector.is_3d_input_inverted() else 'off'}",
                f"Test pattern:     {'on' if projector.is_3d_test_pattern_enabled() else 'off'}",
                f"3D sync status:   {status['sync'] or 'unknown'}",
                f"Darktime status:  {status['darktime'] or 'unknown'}",
            ]
        )

    if command == "3d-mode":
        if argument is not None:
            projector.set_3d_mode(_number_or_name(argument))
        return "3D mode is now %d (%s)" % projector.get_3d_mode()
    if command == "3d-sync-output":
        if argument is not None:
            projector.set_3d_sync_output(_number_or_name(argument))
        return "3D sync output is now %d (%s)" % projector.get_3d_sync_output()
    if command == "3d-delay":
        if argument is not None:
            projector.set_3d_emitter_delay(int(argument))
        return f"3D sync delay is now {projector.get_3d_emitter_delay()}"
    if command == "3d-dark-interval":
        if argument is not None:
            projector.set_3d_dark_interval(int(argument))
        return f"3D dark interval is now {projector.get_3d_dark_interval()}"

    # The two switches: 3d-invert and 3d-test-pattern.
    if argument is not None:
        if argument.lower() not in _ON_OFF:
            raise ValueError(f"expected on or off, not {argument!r}")
        wanted = _ON_OFF[argument.lower()]
        if command == "3d-invert":
            projector.set_3d_input_inverted(wanted)
        elif wanted:
            projector.enable_3d_test_pattern()
        else:
            projector.disable_3d_test_pattern()
    if command == "3d-invert":
        return f"Eye inversion is now {'on' if projector.is_3d_input_inverted() else 'off'}"
    return f"3D test pattern is now {'on' if projector.is_3d_test_pattern_enabled() else 'off'}"


def probe(projector: ChristieM4K25) -> None:
    """Report which documented codes this unit actually implements.

    Worth re-running with the projector powered on: some controls may only
    register once the light source is running.
    """
    supported, absent, rejected = [], [], []
    for code in DOC_CODES:
        if code == "SST":
            continue  # answers with ~100 messages; use the `group` command instead
        try:
            supported.append((code, projector.raw_query(code)))
        except ChristieError as exc:
            if exc.code == 101:  # "Control Not Found"
                absent.append(code)
            else:
                rejected.append((code, exc.message))

    print(f"=== implemented ({len(supported)}) ===")
    for code, reply in supported:
        print(f"  {code:4s} {reply}")
    print(f"\n=== absent ({len(absent)}) ===")
    print("  " + " ".join(absent))
    if rejected:
        print(f"\n=== present but not readable ({len(rejected)}) ===")
        for code, message in rejected:
            print(f"  {code:4s} {message}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("host")
    parser.add_argument(
        "command",
        choices=[
            "status",
            "json",
            "power-on",
            "power-off",
            "input",
            "shutter",
            "brightness",
            "test-pattern",
            *_THREE_D_COMMANDS,
            "group",
            "probe",
            "raw",
        ],
    )
    parser.add_argument("argument", nargs="?")
    args = parser.parse_args()

    # Handled before connecting, since it reports unreachability as data.
    if args.command == "json":
        print(as_json(args.host))
        return

    with ChristieM4K25(args.host, timeout=10) as projector:
        if args.command == "status":
            show_status(projector)
        elif args.command == "power-on":
            # Not ack=True: the projector goes silent for a few seconds after
            # a power command, so waiting for an acknowledgment just times out.
            projector.power_on()
            print("Power on sent (warms up over ~15s)")
        elif args.command == "power-off":
            projector.power_off()
            print("Power off sent (cools down before reaching standby)")
        elif args.command == "input":
            if not args.argument:
                parser.error(f"input takes an index (1-11) or one of: {', '.join(INPUTS.values())}")
            # Number or label, as for test-pattern above.
            source = int(args.argument) if args.argument.isdigit() else args.argument
            try:
                projector.select_input(source)
            except ValueError as exc:
                parser.error(str(exc))
            index, name = projector.get_input()
            print("Input is now %d (%s, %s)" % (index, INPUTS.get(index, "unlisted"), name))
        elif args.command == "shutter":
            if args.argument == "open":
                projector.open_shutter()
            elif args.argument == "close":
                projector.close_shutter()
            else:
                parser.error("shutter takes 'open' or 'close'")
            print("Shutter is now", "open" if projector.is_shutter_open() else "closed")
        elif args.command == "brightness":
            if args.argument:
                try:
                    projector.set_brightness(float(args.argument))
                except ValueError as exc:
                    parser.error(str(exc))
            print(
                f"Brightness {projector.get_brightness():.1f}% "
                f"(LiteLOC {'on' if projector.get_liteloc() else 'off'})"
            )
        elif args.command == "test-pattern":
            if not args.argument:
                parser.error(f"test-pattern takes one of: {', '.join(TEST_PATTERNS.values())}")
            # Accept the number as well as the name: callers driving this from
            # a shell command (Home Assistant) send the number, which avoids
            # quoting names that contain spaces.
            pattern = int(args.argument) if args.argument.isdigit() else args.argument
            try:
                projector.set_test_pattern(pattern)
            except ValueError as exc:
                parser.error(str(exc))
            print("Test pattern is now %d (%s)" % projector.get_test_pattern())
        elif args.command in _THREE_D_COMMANDS:
            try:
                print(run_3d(projector, args.command, args.argument))
            except ValueError as exc:
                parser.error(str(exc))
        elif args.command == "group":
            group = (args.argument or "").upper()
            if group not in STATUS_GROUPS:
                parser.error(f"group must be one of {', '.join(STATUS_GROUPS)}")
            for label, value in projector.get_status(group).items():
                print(f"  {label:48s} {value}")
        elif args.command == "probe":
            probe(projector)
        elif args.command == "raw":
            if not args.argument:
                parser.error("raw takes a code, e.g. 'GAM?' or 'LAS+POWR?'")
            # Most of this platform's controls are CODE+SUB, so accept both.
            code, _, subcode = args.argument.rstrip("?").partition("+")
            if args.argument.endswith("?"):
                print(projector.raw_query(code, subcode or None))
            else:
                projector.raw_set(code, subcode or None)
                print("OK")


if __name__ == "__main__":
    main()
