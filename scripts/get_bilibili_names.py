#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


API_URL = "https://api.bilibili.com/x/web-interface/card"
SPACE_HOST_SUFFIX = "bilibili.com"


def parse_uid(text: str) -> str | None:
    value = (text or "").strip()
    if not value:
        return None
    if value.isdigit():
        return value

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        host = parsed.netloc.lower()
        if host.endswith(SPACE_HOST_SUFFIX):
            path_parts = [part for part in parsed.path.split("/") if part]
            if path_parts and path_parts[0] == "space" and len(path_parts) >= 2 and path_parts[1].isdigit():
                return path_parts[1]
            if path_parts and path_parts[0].isdigit():
                return path_parts[0]

    m = re.search(r"(?:^|[^0-9])([1-9][0-9]{5,})(?:[^0-9]|$)", value)
    if m:
        return m.group(1)
    return None


def unique_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def fetch_name(uid: str, timeout: float) -> tuple[bool, str]:
    headers = {
        "user-agent": "Mozilla/5.0",
        "referer": f"https://space.bilibili.com/{uid}",
    }
    resp = requests.get(API_URL, params={"mid": uid}, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    code = data.get("code")
    if code != 0:
        return False, f"code={code}, message={data.get('message', '')}"
    card = (data.get("data") or {}).get("card") or {}
    name = (card.get("name") or "").strip()
    if not name:
        return False, "empty name"
    return True, name


def load_inputs(args: argparse.Namespace) -> list[str]:
    raw_values: list[str] = []
    raw_values.extend(args.inputs or [])
    if args.file:
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                raw_values.append(line)
    if args.stdin:
        for line in sys.stdin:
            line = line.strip()
            if line and not line.startswith("#"):
                raw_values.append(line)
    return raw_values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Bilibili user names by UID or space URLs.",
    )
    parser.add_argument("inputs", nargs="*", help="UID or bilibili space URL")
    parser.add_argument("-f", "--file", help="Read inputs from a text file")
    parser.add_argument("--stdin", action="store_true", help="Read inputs from stdin")
    parser.add_argument(
        "--format",
        choices=["tsv", "feeds"],
        default="tsv",
        help="Output format: tsv -> uid<TAB>name, feeds -> /bilibili/user/video/<uid> # <name>",
    )
    parser.add_argument("--sleep", type=float, default=0.25, help="Sleep between requests in seconds")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds")
    args = parser.parse_args()

    raw_values = load_inputs(args)
    if not raw_values:
        parser.error("no input provided")

    uids: list[str] = []
    bad_values: list[str] = []
    for raw in raw_values:
        uid = parse_uid(raw)
        if uid:
            uids.append(uid)
        else:
            bad_values.append(raw)
    uids = unique_keep_order(uids)

    for value in bad_values:
        print(f"INVALID\t{value}", file=sys.stderr)

    had_error = bool(bad_values)
    for idx, uid in enumerate(uids):
        try:
            ok, name_or_err = fetch_name(uid, timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001
            ok = False
            name_or_err = str(exc)

        if ok:
            if args.format == "feeds":
                print(f"/bilibili/user/video/{uid} # {name_or_err}")
            else:
                print(f"{uid}\t{name_or_err}")
        else:
            had_error = True
            print(f"FAIL\t{uid}\t{name_or_err}", file=sys.stderr)

        if idx < len(uids) - 1 and args.sleep > 0:
            time.sleep(args.sleep)

    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
