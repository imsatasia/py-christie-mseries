"""Dump the projector's entire menu tree: every control code with its label,
range and option list, as the projector itself reports them.

This does not use the serial API on port 3002 at all. It talks to the same
JSON-RPC endpoint the built-in web UI uses, which is the only interface that
will *enumerate* controls -- the serial API can only confirm a code you already
guessed. It is how `docs/menu-map.json` was produced, and how LAS+POWR
("Brightness") was found after a full sweep of the serial API missed it.

Read-only: it issues menu:get and getAttributes, never a set.

    python3 examples/dump_menu.py 192.0.2.50 user user --json > docs/menu-map.json
"""

import argparse
import json
import sys
import urllib.request


class MenuRPC:
    """Minimal client for the projector's web JSON-RPC endpoint."""

    def __init__(self, host: str):
        """Prepare a client for `host`; call connect() before any query."""
        self._base = f"http://{host}/cgi-bin/c4jweb/"
        self._url = self._base
        self._id = 0

    def connect(self, user: str, password: str) -> None:
        """Log in and switch to the returned per-session URL. Every other
        method fails with "invalid Session ID" until this has run."""
        # The endpoint returns a path, not an absolute URL.
        path = self._call("session:connect", {"user": user, "pass": password})
        self._url = f"http://{self._base.split('/')[2]}{path}"

    def _call(self, method: str, params):
        """Send one JSON-RPC call and return its result, raising on error."""
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}).encode()
        request = urllib.request.Request(self._url, data=body, headers={"Content-Type": "application/json"})
        reply = json.loads(urllib.request.urlopen(request, timeout=10).read())
        if "error" in reply:
            raise RuntimeError(f"{method}: {reply['error']}")
        return reply["result"]

    def menu(self, code: str) -> dict:
        """Fetch one menu node, including its immediate children."""
        return self._call("menu:get", {"code": code})


# Fields containing Christie's own written UI copy (confirmation-dialog
# prose, per-option help text) rather than short functional labels or
# numeric data -- dropped so this file stays unambiguously "extracted
# parameter data", not a reproduction of vendor-authored text. `label`,
# `text` and `continue` are kept: they're short functional names (e.g.
# "Brightness", "Calibrate"), not prose.
_VENDOR_TEXT_FIELDS = ("hint", "confirm")


def _strip_vendor_text(item: dict) -> dict:
    """Drop vendor-authored prose fields from one menu item, including its
    nested option list."""
    clean = {k: v for k, v in item.items() if k not in _VENDOR_TEXT_FIELDS}
    if clean.get("list"):
        clean["list"] = [
            {k: v for k, v in option.items() if k not in _VENDOR_TEXT_FIELDS} for option in clean["list"]
        ]
    return clean


# Codes whose default/value is a unique-per-unit identifier -- a MAC address,
# or a device name the projector derives from one -- rather than functional
# configuration data. Recording these for a real unit would violate this
# project's own policy against committing anything that identifies a
# specific physical device (see the repo's top-level CLAUDE.md), so they're
# replaced with an obviously-fake placeholder before ever reaching disk.
_IDENTIFYING_CODES = {
    "NET+MAC0": "00:00:00:00:00:00",
    "NET+HOST": "Christie-M-4K25-RGB-000000000",
}


def _redact_identifiers(item: dict) -> dict:
    """Replace an identifying control's default/value with a placeholder."""
    placeholder = _IDENTIFYING_CODES.get(item.get("code"))
    if placeholder is None:
        return item
    return {**item, **{k: placeholder for k in ("default", "value") if k in item}}


def walk(rpc: MenuRPC, code: str = "MMM+MAIN", path: str = "") -> list:
    """Depth-first walk of the menu tree from `code`, returning a flat list.

    Submenus are type 600 and are the only nodes recursed into; everything
    else is a leaf control.
    """
    try:
        node = rpc.menu(code)
    except Exception as exc:
        print(f"# {code}: {exc}", file=sys.stderr)
        return []

    here = f"{path} > {node.get('label')}" if path else node.get("label")
    entries = []
    for item in node.get("items", []):
        entries.append({**_redact_identifiers(_strip_vendor_text(item)), "path": here})
        if item.get("type") == 600 and item.get("code"):
            entries.extend(walk(rpc, item["code"], here))
    return entries


def format_entry(entry: dict) -> str:
    """One aligned line per control, with range and options where present.

    `decimals` scales the raw value: LAS+POWR reads 700 with decimals=1,
    meaning 70.0%. Where a control also carries soft bounds, those are the
    range the UI actually lets you pick from -- LAS+POWR's hard minimum is 0
    but its soft minimum is 200, and the projector will not go below it.
    """
    parts = [f"{entry['code']:12s} {str(entry.get('label'))[:42]:42s}"]
    if entry.get("min") is not None:
        parts.append(f"range={entry['min']}..{entry['max']}")
    if entry.get("softmin") is not None:
        parts.append(f"soft={entry['softmin']}..{entry['softmax']}")
    if entry.get("decimals"):
        parts.append(f"decimals={entry['decimals']}")
    if entry.get("list"):
        parts.append("options=" + "|".join(i["text"] for i in entry["list"]))
    return "  ".join(parts).rstrip() + f"   [{entry['path']}]"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("user")
    parser.add_argument("password")
    parser.add_argument("--json", action="store_true", help="emit raw JSON instead of aligned text")
    args = parser.parse_args()

    rpc = MenuRPC(args.host)
    rpc.connect(args.user, args.password)
    entries = [e for e in walk(rpc) if e.get("code")]

    if args.json:
        print(json.dumps(entries, indent=1, ensure_ascii=False))
    else:
        print("\n".join(format_entry(e) for e in entries))
    print(f"# {len(entries)} controls", file=sys.stderr)


if __name__ == "__main__":
    main()
