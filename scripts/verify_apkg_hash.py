#!/usr/bin/env python

"""Verify or record the generated APKG hash."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_summary(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def load_pin(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_pin(path: Path, apkg: Path, actual: dict[str, Any]) -> None:
    pin = {
        "schema": "xiehanzi-apkg-build-invariant-v1",
        "apkg_filename": apkg.name,
        "sha256": actual["sha256"],
        "size": actual["size"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(pin, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_report(apkg: Path, pin_path: Path, mode: str) -> dict[str, Any]:
    pin = load_pin(pin_path)
    actual = file_summary(apkg)
    expected = None
    matches = None

    if pin is not None:
        expected = {
            "path": str(pin_path),
            "apkg_filename": pin.get("apkg_filename"),
            "size": pin.get("size"),
            "sha256": pin.get("sha256"),
        }
        matches = (
            actual["sha256"] == expected["sha256"]
            and actual["size"] == expected["size"]
        )

    status = "recorded"
    if mode == "enforce":
        status = "ok" if matches else "changed"

    return {
        "schema": "xiehanzi-apkg-hash-verification-v1",
        "mode": mode,
        "status": status,
        "matches_expected": matches,
        "expected": expected,
        "actual": actual,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apkg", type=Path, required=True, help="Generated APKG path.")
    parser.add_argument("--pin", type=Path, required=True, help="Pinned hash JSON path.")
    parser.add_argument("--output", type=Path, required=True, help="Output verification report JSON path.")
    parser.add_argument(
        "--mode",
        choices=["enforce", "record"],
        default="enforce",
        help="enforce fails on hash drift; record only writes a report.",
    )
    parser.add_argument(
        "--write-pin",
        action="store_true",
        help="Rewrite the pin file with the generated APKG hash. Use intentionally outside nix-build.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.apkg.exists():
        print(f"missing APKG: {args.apkg}")
        return 2

    report = build_report(args.apkg, args.pin, args.mode)
    if args.write_pin:
        write_pin(args.pin, args.apkg, report["actual"])
        report = build_report(args.apkg, args.pin, "enforce")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    if args.mode == "enforce" and not report["matches_expected"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
