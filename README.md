# christie-mseries

Python client for Christie **M Series** projectors' Ethernet serial API on
**TCP port 3002**. Standard library only, no third-party dependencies.

Named for the protocol, not one model: `client.py`'s wire framing/parsing
comes straight from Christie's own M Series Serial API Commands document and
should hold across the line. Only `ChristieM4K25` in `projector.py` is
actually verified, against the TruLife+ platform in the M 4K25 RGB
specifically — its control set (which codes exist, test pattern numbering,
brightness floor) is *not* assumed to carry over to other M Series models
without checking `docs/menu-map.json`/`raw_query()` against the real unit
first. See "The control model, and how to find a control" below for why.

## Contents

- [Firmware this was built for](#firmware-this-was-built-for)
- [Install](#install)
- [Usage](#usage)
- [CLI](#cli)
- [The control model, and how to find a control](#the-control-model-and-how-to-find-a-control)
- [Command coverage](#command-coverage)
- [Inputs: `SIN`](#inputs-sin)
- [Laser power: `LAS+POWR`](#laser-power-laspowr)
- [How replies work, and why it bites](#how-replies-work-and-why-it-bites)
- [Status groups](#status-groups)
- [Polling: `snapshot()`](#polling-snapshot)
- [Testing](#testing)
- [Consumers](#consumers)
- [Layout](#layout)
- [Credits](#credits)
- [License](#license)

## Firmware this was built for

**Christie M 4K25 RGB, main control board software 1.3.x** — developed and
verified against a physical unit running **1.3.9**, re-verified against the
same unit updated to **1.3.10** (no behavior changes to anything below; see
"1.3.10" note further down), with these component versions:

| Component | Version |
| --- | --- |
| Main Control Board SW | `ChristieM 1.3.10` |
| Main Control Board HW | `CAVE.7.1` |
| Formatter R/G/B HW | `CFB098HU.3.4` |
| Photon SW | `1.6.1-1(Boot)/1.8.1-7(Main)` |
| Power Supply HW | `PSB.2.0` |
| Housekeeping Board HW | `HKBG.3.2` |
| Keypad Display HW | `IKB.6.0` |
| Variable Option Module HW | `VOMHBI.3.0` |
| BIOS SW | `00.33` |
| SSPWBD SW / HW | `1.6.741270` / `WBD.2.3` |

This matters more than it usually would. Which codes exist at all is a
property of the firmware, not of the model — this unit's TruLife+ platform
implements roughly a third of the codes in the M Series serial API document
this client was first written from, and `docs/menu-map.json` is a snapshot of
*this* firmware's menu tree. After a software upgrade, regenerate that map and
re-run the tests before trusting any code that is not exercised by them:

```bash
python3 examples/dump_menu.py <host> <user> <password> --json > docs/menu-map.json
git diff docs/menu-map.json      # controls added, removed or re-ranged
```

**1.3.10**: re-ran the full functional check (power/shutter/brightness/
LiteLOC/test pattern/lens positions/input/hours, plus a fresh menu dump) —
everything already wrapped here behaves identically. Five new codes appeared
under `EDC+DPCV`/`EDC+DPVO`/`EDC+HDCV`/`EDC+HDVO`/`MMC+EDID` (custom EDID
management for the HDMI/DisplayPort inputs, under Configuration > Input
Settings), all reported `enabled: false` with no options beyond "Default
EDID" — nothing configurable yet, so nothing new to wrap.

Read the running versions at any time with:

```bash
python3 -c "from christie_mseries import ChristieM4K25
with ChristieM4K25('<host>') as p:
    for k, v in p.get_status('VERS').items(): print(f'{k}: {v}')"
```

## Install

```bash
pip install christie-mseries
```

For local development:

```bash
git clone https://github.com/imsatasia/py-christie-mseries.git
cd py-christie-mseries
uv sync --group dev    # or: task install
```

## Usage

```python
from christie_mseries import ChristieM4K25

with ChristieM4K25("192.0.2.50") as projector:
    projector.get_power_state()  # <PowerState.ON: 1>
    projector.get_power_state_text()  # 'On'
    projector.get_input()  # (1, 'One-Port HDMI0')
    projector.get_brightness()  # 70.0  (percent of laser power)
    projector.get_hours()  # '4:05 (h:m)'
    projector.get_temperatures()  # {'Air Intake Temperature (Temp 2)': '34 °C', ...}
    projector.power_on(wait=True)  # blocks until the ack comes back
    projector.snapshot()  # Snapshot(power='On', power_code=1, ...) -- one poll, every field a caller like Home Assistant wants
```

Anything without a named method is reachable with `raw_query()` /
`raw_set()`, which take a code and an optional subcode:

```python
projector.raw_query("GAM")  # (GAM?)
projector.raw_query("LAS", "WHTX")  # (LAS+WHTX?)
```

## CLI

Installed as the `christie-mseries` console script:

```bash
christie-mseries 192.0.2.50 status          # power, input, hours, alarms
christie-mseries 192.0.2.50 json            # machine-readable, one poll (snapshot())
christie-mseries 192.0.2.50 brightness      # read laser power %
christie-mseries 192.0.2.50 brightness 70   # set it (30-100)
christie-mseries 192.0.2.50 input 3                    # by SIN index...
christie-mseries 192.0.2.50 input "HDMI 2.1 Port 3"    # ...or by label
christie-mseries 192.0.2.50 shutter open
christie-mseries 192.0.2.50 test-pattern "Color Bars"
christie-mseries 192.0.2.50 group TEMP      # one status group in full
christie-mseries 192.0.2.50 probe           # which documented codes exist here
```

## The control model, and how to find a control

This unit runs Christie's **TruLife+** platform, and the M Series serial API
doc (`020-100224-11`) that this library was first written from describes a
different, older one. Of the doc's 175 codes, 36 answer here; assuming the
rest exist produces methods that fail at runtime with `ERR00101 "Control Not
Found"`.

More importantly, the doc's model — a flat space of three-letter codes — is
simply not how this platform is shaped. Its real control surface is
overwhelmingly **subcoded**: of 221 controls (as of firmware 1.3.10), 19 are
bare codes and 202 are `CODE+SUB` across 33 families.

That has a sharp consequence for discovery. **The serial API cannot list
anything.** It only confirms a code you already guessed, and a code that
requires a subcode answers `Control Not Found` when queried bare — `LAS`,
`WRP` and `NET` all do. So sweeping the three-letter space cannot find
subcoded controls even in principle: a sweep of all 17,576 combinations
returned 56 codes here and still missed laser power entirely.

The projector's built-in web UI has the interface that *does* enumerate: a
JSON-RPC endpoint at `http://<host>/cgi-bin/c4jweb/`, where `menu:get`
returns each menu node with every child's code, label, type, range, soft
range and option list. `examples/dump_menu.py` walks the whole tree:

```bash
python3 examples/dump_menu.py <host> <user> <password> --json > docs/menu-map.json
```

**`docs/menu-map.json` is the checked-in result and the reference to read
first** for any "can it do X?" question: 236 entries covering those 221
controls, each with its menu path. Regenerate it after a firmware update.
Note that `session:connect` returns a session URL that every later call must
be posted to, or the reply is `invalid Session ID`.

The vendor's own M Series serial API document (020-100224-11) is
deliberately **not** included in this repo — it's Christie's copyrighted
material, and reproducing it wholesale isn't appropriate to publish here.
Everything this README says about it (which codes it gets right or wrong,
what it doesn't cover) comes from our own testing against the real unit,
cross-checked with `docs/menu-map.json`.

## Command coverage

Codes with a named method:

| Code | Meaning | Method |
|------|---------|--------|
| `PWR` | Power | `power_on()`, `power_off()`, `get_power_state()`, `get_power_state_text()` |
| `SHU` | Shutter | `open_shutter()`, `close_shutter()`, `is_shutter_open()` |
| `LAS+POWR` | Brightness (laser power) | `get_brightness()`, `set_brightness()` |
| `LAS+STAT` | LiteLOC | `get_liteloc()`, `set_liteloc()` |
| `SIN` | Select Input | `select_input()` (index or label), `get_input()` |
| `CHA` | Channel | `select_channel()`, `get_channel()`, `copy_channel()`, `delete_channel()` |
| `SST` | Projector Status | `get_status()`, `get_hours()`, `get_model()`, `get_serial_number()`, `get_temperatures()` |
| `FCS` | Focus | `get_focus()`, `set_focus()` |
| `ZOM` | Zoom | `get_zoom()`, `set_zoom()` |
| `LHO` | Lens Horizontal | `get_lens_horizontal()`, `set_lens_horizontal()` |
| `LVO` | Lens Vertical | `get_lens_vertical()`, `set_lens_vertical()` |
| `LCB` | Lens Calibration | `calibrate_lens()`, `home_lens()` (write-only) |
| `FRZ` | Image Freeze | `is_frozen()`, `set_frozen()` |
| `ITP` | Test Pattern | `get_test_pattern()`, `set_test_pattern()` |
| `WRP+SLCT` | Geometry Correction | `get_geometry_warp()`, `set_geometry_warp()`, `reset_keystone()` |
| `ASU` | Auto Setup | `auto_setup()` (write-only) |
| `TDM` `TDD` `TDN` `TDO` `TDT` `DRK` | 3D | `get_3d_mode()`, `get_3d_emitter_delay()`, `is_3d_input_inverted()`, `get_3d_sync_output()`, `is_3d_test_pattern_enabled()`, `get_3d_dark_interval()` (+ setters) |
| `NET` | Network Setup | `get_network()` |
| `ADR` | Address | `get_address()`, `set_address()` |
| `PNG` | Ping | `ping()` |
| — | Everything worth polling in one shot | `snapshot()` |

Present but not wrapped — use `raw_query()` / `raw_set()`: `APW` (auto power
on), `BGC` (gamma curve), `CLE` (color enable), `CSP` (color space), `DTL`
(detail), `EME` (error messages), `FMD` (film mode detect), `FRD` (frame
delay), `GAM` (gamma), `MSP` (menu location), `NTR` (network routing), `OSD`
(on-screen display), `RAL` (remote access level), `SOR` (screen
orientation), `SZP` (size preset), `UID` (user ID), plus the ~202 subcoded
controls in `docs/menu-map.json`.

### What this platform does not have

- **None of the doc's laser/illumination codes.** `LPI`, `LPM`, `LPP` are
  all absent, as are `LSR`, `LSP`, `LPW`, `LIP`, `ILP`, `LSI` and `ILI`.
  Laser power is controllable, just under a different name — see below.
- **No ILS / lens memory.** `ILS` and `ILV` are absent, so lens positions
  are not stored per channel. Channels (`CHA`) still store source routing
  and image settings, but recalling one will not move the lens. (The
  `christie-m4k25-homeassistant` and `christie-m4k25-control4` integrations
  each synthesize their own lens presets on top of `get_focus()`/`set_focus()`
  etc., since the projector has none of its own.)
- **No iris control** (`IRS`, `DIM`, `DIS`, `MIP`).
- **No `PJH`** for runtime hours — use `get_hours()`, which pulls "Projector
  Hours" out of the `SYST` status group.
- **No `KEY` remote-button emulator** and no `MNU`, so the on-screen menu
  can't be driven over this API.
- **No `+MAIN` subcodes.** The doc's `SIN+MAIN`, `CHA+MAIN`, `TDM+MAIN`,
  `TDD+MAIN` and `DRK+MAIN` do not exist; use the plain codes.

These absences are structural, not a side effect of the projector being
idle: probing in standby and again with the light source running returns an
identical list, 35 codes either way.

## Inputs: `SIN`

The projector reports its inputs by its own names (`get_input()` returns
`(3, "One-Port VOM-HDMI")`), which don't say which connector on the back they
are. `INPUTS` maps each `SIN` index to the physical port, and `select_input()`
takes either the index or the label, the same way `set_test_pattern()` takes
a number or a name:

| Index | Projector's name | Label |
|---|---|---|
| 1 | One-Port HDMI0 | HDMI 2.0 Port 1 |
| 2 | One-Port HDMI1 | HDMI 2.0 Port 2 |
| 3 | One-Port VOM-HDMI | HDMI 2.1 Port 3 |
| 4 | One-Port VOM-DP0 | DisplayPort 1.4 Port 3 |
| 5 | One-Port VOM-DP1 | DisplayPort 1.4 Port 4 |
| 6 | One-Port DP0 | DisplayPort 1.2 Port 1 |
| 7 | One-Port DP1 | DisplayPort 1.2 Port 2 |
| 8-11 | One-Port SDI0-SDI3 | SDI 1-SDI 4 |

```python
projector.select_input("HDMI 2.1 Port 3")  # same as select_input(3)
projector.select_input(3)
```

An unknown label raises `ValueError` before anything is sent. Every index
1-11 was switched to and read back on hardware; the labels come from
the port names in the projector's Input Settings menu (`EDC+HDCV`, `HDVO`,
`DPCV`, `DPVO` in `docs/menu-map.json`). **Index 3 = HDMI 2.1 Port 3 is
confirmed; the pairing of indexes 4-7 to individual DisplayPort ports is
inferred from the order the projector lists them, not checked against a
cable** - correct `INPUTS` if a port turns out to be the other of its pair.
The `VOM-*` inputs belong to the Variable Option Module, so a unit without
one won't have them.

`SIN` is refused with `Disabled Control` while the projector is in standby:
the input can be read then, but only changed once it is on. `snapshot()`
carries the table for pollers (see below), and its `input_label` falls back to
the projector's own name for an index that isn't in `INPUTS`.

## Laser power: `LAS+POWR`

Labelled **Brightness** in the projector's menu, under Configuration > Light
& Output Settings. Stored in tenths of a percent, so it reads `700` at 70%:

```python
projector.get_brightness()  # 70.0
projector.set_brightness(85)  # percent, not tenths
```

Its hard range is 0–1000, and the projector publishes a **soft minimum of
200**, below which it will not run the lasers at all.

`set_brightness()` enforces a stricter floor of **30%**, because Christie's
own release notes for both 1.3.9 and 1.3.10 carry this as an open known
issue: *"LiteLOC performance is compromised when running at low brightness
levels (30% or less) ... laser devices may shut down and colors may drop
out."* LiteLOC is enabled on this unit, so 20–30% is a band the hardware
accepts but the vendor advises against, and it is rejected rather than
offered. The menu node
also carries a `softvalue`: the brightness actually being applied, which
drops below the set value when the projector thermally limits itself. That
is what the web UI's "Brightness Reduced / System Adjusted" labels report.

If this floor is ever revisited, change `BRIGHTNESS_MIN_PERCENT` here and
update it everywhere else it's duplicated — the Home Assistant integration's
`number` entity and the Control4 driver's `SetBrightness` command each carry
their own copy, and all three are expected to agree.

`LAS+STAT` is LiteLOC, reporting `3` for enabled and `1` for disabled. Note
the projector currently marks it `enabled: false` — greyed out in its own
UI. Per-laser setpoints `LAS+REDP`/`GRNP`/`BLUP` exist under Admin >
Diagnostics; those are service-level colour calibration, not a brightness
control, and are best left alone.

Laser *telemetry* is separate and read-only: `get_status("LGHT")` returns
105 items including per-bank temperatures, driver amps/volts, and "Laser On
Hours".

## How replies work, and why it bites

Three things about this protocol are easy to get wrong, and all three
produced real bugs here:

- **Most replies pair a number with a description** — `(PWR!000 "Standby
  Mode")`, not `(PWR!000)` — so `int()` on the reply data fails. Use
  `get_power_state()` for the number and `get_power_state_text()` for the
  projector's own wording, which is more trustworthy than the doc's value
  tables (the doc says `TDM` 1 is "Native 3D"; this unit says "Auto Detect").
- **A successful SET is answered with silence, a rejected one isn't.** An
  unread error reply doesn't vanish — it's returned as the answer to the
  next query, shifting every later reading by one. `set()` therefore waits
  briefly for an error and raises it.
- **Three different failures look similar.** `ERR00101 "Control Not Found"`
  means the code doesn't exist on this platform (or needs a subcode);
  `ERR00105 "Disabled Control"` means it exists but isn't available right
  now — image controls like `ITP` and `FRZ` are rejected in standby and
  accepted once the projector is on; and `"This control can not be read"`
  marks write-only codes (`ASU`, `LCB`).

Also worth knowing for polling: for a few seconds right after `PWR 1` the
projector accepts a TCP connection but answers nothing, so a read can time
out mid-transition. Treat a timeout as "unknown", not as "off" — the
sequence observed here was silence, then `11 "Warming Up"`, then `1 "On"`
about 16 seconds after the command.

## Status groups

`get_status(group)` returns `{label: value}` for one group, reading the
projector's multi-message reply until it goes quiet:

| Group | Items | Contents |
|-------|-------|----------|
| `CONF` | 4 | model, serial number, output resolution, build date |
| `COOL` | 12 | fans and blowers |
| `LGHT` | 105 | laser/light-source state, temperatures, firmware versions |
| `SIGN` | 22 | input signal properties |
| `SYST` | 30 | hours, pitch/roll, lens calibration, board health, voltages |
| `TEMP` | 13 | temperature sensors |
| `VERS` | 13 | software versions |
| `ALRM` | 0 | active alarms; empty is the healthy case, returned as `{}` |

The doc's `HLTH` and `LAMP` groups don't exist here, and `LGHT` exists but
isn't in the doc.

## Polling: `snapshot()`

```python
snap = projector.snapshot()
snap.power_code, snap.power  # 1, "On"
snap.is_on, snap.in_transition
snap.input, snap.input_name
snap.input_label, snap.inputs, snap.input_map  # "HDMI 2.1 Port 3", [labels...], {label: index}
snap.brightness, snap.liteloc
snap.test_pattern, snap.test_patterns, snap.test_pattern_map
snap.focus, snap.zoom, snap.lens_horizontal, snap.lens_vertical
snap.hours, snap.model, snap.serial, snap.alarms
snap.intake_temp  # None if unreadable
```

One connection's worth of reads, bundled into a single `Snapshot` dataclass.
This is the single source of truth both the CLI's `json` command and (via
`christie-m4k25-homeassistant`) Home Assistant's coordinator poll from — add
a new pollable field here, not in either caller.

`snapshot()` raises like any other method here if a read fails or the
connection drops mid-poll. A caller that wants "unreachable" reported as
data instead of an exception should catch around it, the same way `cli.py`'s
`as_json()` does:

```python
try:
    with ChristieM4K25(host, timeout=8) as projector:
        snap = projector.snapshot()
except Exception as exc:
    ...  # report as unreachable rather than propagating
```

## Testing

```bash
task test          # or: uv run pytest -v
```

29 protocol tests (`tests/test_protocol.py`) plus a domain-layer suite
(`tests/test_projector.py`) covering `ChristieM4K25`'s methods including
`snapshot()`. There is no simulator, so both run against fake sockets;
behaviour on real hardware is checked with `christie-mseries probe` and
`christie-mseries status`. The reply strings in the tests are real captures,
including the cases that previously broke: replies pairing a number with a
description (`000 "Standby Mode"`), multi-field replies (`NET`), escaped
parens (`"3:14 \(h:m\)"`), and non-ASCII status text (`"32 °C"`).

## Consumers

This package is a standalone client; it contains no Home Assistant or
Control4 integration code of its own.

- [`christie-m4k25-homeassistant`](https://github.com/imsatasia/christie-m4k25-homeassistant) —
  a native Home Assistant custom integration built on this package.
- [`christie-m4k25-control4`](https://github.com/imsatasia/christie-m4k25-control4) —
  a Control4 DriverWorks driver; a separate Lua reimplementation of the same
  wire protocol (Control4 drivers can't call out to a Python process), not a
  consumer of this package at runtime, but developed against the same
  hardware and kept in sync with the protocol notes above.

## Layout

| Path | Purpose |
|------|---------|
| `christie_mseries/client.py` | Message framing, parsing, and the raw request/set API |
| `christie_mseries/projector.py` | High-level `ChristieM4K25` methods and `Snapshot` |
| `christie_mseries/cli.py` | The `christie-mseries` console script, including the `json` poll Home Assistant runs |
| `examples/dump_menu.py` | Regenerates `docs/menu-map.json` from the web RPC |
| `docs/menu-map.json` | **221 labelled controls** — the reference to read first |

## Credits

This library was originally written against Christie's own **M Series
Serial API Commands** technical reference:

> Technical Reference 020-100224-11 — *M Series Serial API Commands*,
> © 2016 Christie Digital Systems USA Inc. All rights reserved.
> [PDF, hosted by Christie Digital](https://www.christiedigital.com/globalassets/resources/public/020-100224-11-christie-lit-tech-ref-m-series-serial-commands.pdf)

That document isn't reproduced in this repository — it's Christie's
copyrighted material, and redistributing a vendor's proprietary manual
wholesale isn't appropriate for a public repo. It's linked here instead,
from Christie's own site, for anyone who wants the original. As documented
throughout this README, it also turned out to only partially describe this
platform (TruLife+, not the M Series document's original target) — the
document this library actually relies on for day-to-day accuracy is
`docs/menu-map.json`, generated directly from the projector's own web UI.

## License

MIT — see [LICENSE](LICENSE). Applies to the code in this repository only,
not to Christie's serial API document credited above.
