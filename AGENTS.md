# AGENTS.md

## Purpose

`py-christie-mseries` is a standalone Python client for Christie's M Series
projector Ethernet serial API (TCP port 3002). Named for the protocol, not
one model — see Design Expectations below for what that does and doesn't
mean in practice. It is consumed by `christie-m4k25-homeassistant` and used
directly from the CLI; it contains no Home Assistant or Control4 code
itself.

## Workflow

- Use `uv`/`task` for local commands (`task install`, `task test`, `task check`).
- Run repo-local lint, format, typecheck and tests before pushing.
- Keep this package dependency-free (stdlib only) unless there's a strong reason otherwise.

## Design Expectations

- The package name/repo describe the *protocol* (Christie's M Series serial
  API), not a claim that every model is supported. `client.py`'s wire
  framing/parsing comes from Christie's own protocol doc and should hold
  across the line; `ChristieM4K25` in `projector.py` is the one actually
  verified model. If a second model gets verified, give it its own class
  (`ChristieM4K35`, whatever) rather than generalizing `ChristieM4K25` to
  cover both — its control set (test pattern numbering, brightness floor,
  which codes exist) is specific to the M 4K25 RGB's TruLife+ platform and
  must not be assumed to transfer silently.
- Two layers, deliberately not more: `client.py` is the wire protocol
  (framing, parsing, the raw request/set API) with no domain knowledge;
  `projector.py` is the domain model (`ChristieM4K25`, `Snapshot`) built on
  top of it. Protocol quirks (reply shapes, the SET-error-desync guard,
  multi-message status groups) belong in `client.py`; device semantics
  (brightness floor, test pattern names, lens axes) belong in `projector.py`.
- `ChristieM4K25.snapshot()` is the single source of truth for "everything
  worth polling in one shot" — both `cli.py`'s `json` command and Home
  Assistant's coordinator should call it rather than re-gathering the same
  fields independently. Add new pollable fields there, not in a caller.
- Never assume a code from Christie's M Series serial API doc (020-100224-11)
  exists on this platform without confirming against `docs/menu-map.json` or
  a live `raw_query()` — see README's "The control model, and how to find a
  control" for why. The doc's own text is deliberately not kept in this
  repo (it's Christie's copyrighted material, © 2016 Christie Digital
  Systems USA Inc.) — cite the document number, don't paste its contents.
- Never write this projector's serial number, or the real LAN IP, into this
  repo. Firmware/software versions are fine; read the serial live from
  `get_serial_number()` when it's actually needed. Use an RFC 5737
  documentation address (`192.0.2.0/24`) in docs/examples instead of a
  real IP.
- Firmware target is 1.3.x. After a firmware update, regenerate
  `docs/menu-map.json` (`examples/dump_menu.py --json`) and diff it before
  trusting any code the tests don't already cover — the available control
  set is a property of the firmware, not the model. See README for which
  versions have actually been verified.

## Commits

Use conventional commits for releasable changes: `fix: ...` or `feat: ...`.

## Releases

1. Merge normal conventional commits to `main`.
2. Let `release-please` open or update the release PR.
3. Do not manually edit version files or changelogs outside the Release Please PR.
4. Do not manually create tags or GitHub releases.
5. Merge the Release Please PR to publish to PyPI.
