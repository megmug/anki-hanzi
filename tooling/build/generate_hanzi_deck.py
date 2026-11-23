#!/usr/bin/env python

"""Build the customized hanzi APKG."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from anki_hanzi.deck import common
from anki_hanzi.deck.build import (
    DEFAULT_GENERATED_ZIP_DATETIME,
    DEFAULT_GENANKI_TIMESTAMP,
    DEFAULT_MIGRATOR_ADDON_OUTPUT,
    DEFAULT_REPORT_PATH,
    build_package,
)
from anki_hanzi.json_io import json_text
from anki_hanzi.paths import (
    DEFAULT_BCT_DATA_DIR,
    DEFAULT_DECK_CONFIG,
    DEFAULT_FREQUENCY_LIST,
    DEFAULT_HSK_DATA_DIR,
    DEFAULT_SNAPSHOT_MANIFEST,
    DEFAULT_YCT_DATA_DIR,
)


def parse_zip_datetime(value: str) -> tuple[int, int, int, int, int, int]:
    try:
        date_part, time_part = value.replace("T", " ").split()
        year, month, day = (int(part) for part in date_part.split("-"))
        hour, minute, second = (int(part) for part in time_part.split(":"))
    except Exception as exc:
        raise argparse.ArgumentTypeError("Expected datetime in YYYY-MM-DDTHH:MM:SS format") from exc
    return year, month, day, hour, minute, second


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-manifest",
        type=Path,
        default=DEFAULT_SNAPSHOT_MANIFEST,
        help="Snapshot manifest with the pinned CC-CEDICT source filename, SHA256, and source URL.",
    )
    parser.add_argument("--source-file", type=Path, default=None, help="Optional pinned CC-CEDICT text file override.")
    parser.add_argument("--master-db-output", type=Path, default=None, help="Optional diagnostic master JSON output.")
    parser.add_argument(
        "--enriched-db-output",
        type=Path,
        default=None,
        help="Optional diagnostic enriched JSON output.",
    )
    parser.add_argument(
        "--hsk-data-dir", type=Path, default=DEFAULT_HSK_DATA_DIR, help="Prepared hanzi HSK TSV directory."
    )
    parser.add_argument(
        "--frequency-list",
        type=Path,
        default=DEFAULT_FREQUENCY_LIST,
        help="Simplified word frequency list sorted by usage.",
    )
    parser.add_argument("--yct-data-dir", type=Path, default=DEFAULT_YCT_DATA_DIR, help="Prepared YCT TSV directory.")
    parser.add_argument("--bct-data-dir", type=Path, default=DEFAULT_BCT_DATA_DIR, help="Prepared BCT data directory.")
    parser.add_argument("--config", type=Path, default=DEFAULT_DECK_CONFIG, help="Deck selection JSON config.")
    parser.add_argument("--output", type=Path, default=None, help="Output APKG path.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH, help="Output build report JSON path.")
    parser.add_argument(
        "--migrator-addon-output",
        type=Path,
        default=DEFAULT_MIGRATOR_ADDON_OUTPUT,
        help="Output Anki Hanzi Migrator add-on package path.",
    )
    parser.add_argument(
        "--timestamp",
        type=float,
        default=DEFAULT_GENANKI_TIMESTAMP,
        help="Fixed genanki timestamp for hermetic builds.",
    )
    parser.add_argument(
        "--deterministic-zip",
        action="store_true",
        help="Rewrite the APKG zip with fixed member timestamps for byte-reproducible output.",
    )
    parser.add_argument(
        "--zip-generated-datetime",
        type=parse_zip_datetime,
        default=DEFAULT_GENERATED_ZIP_DATETIME,
        help="Set the ZIP timestamp for collection.anki2 and the media manifest, including in deterministic mode. "
        "Format: YYYY-MM-DDTHH:MM:SS.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.snapshot_manifest.exists():
        print(f"missing snapshot manifest: {args.snapshot_manifest}")
        return 2
    if not args.hsk_data_dir.exists():
        print(f"missing hanzi HSK data dir: {args.hsk_data_dir}")
        return 2
    if not args.frequency_list.exists():
        print(f"missing frequency list: {args.frequency_list}")
        return 2
    if not args.yct_data_dir.exists():
        print(f"missing YCT data dir: {args.yct_data_dir}")
        return 2
    if not args.bct_data_dir.exists():
        print(f"missing BCT data dir: {args.bct_data_dir}")
        return 2

    output_apkg = args.output
    if output_apkg is None:
        output_apkg = common.OUTPUT_APKG

    report = build_package(
        snapshot_manifest=args.snapshot_manifest,
        source_file=args.source_file,
        master_db_output=args.master_db_output,
        enriched_db_output=args.enriched_db_output,
        hsk_data_dir=args.hsk_data_dir,
        frequency_list=args.frequency_list,
        yct_data_dir=args.yct_data_dir,
        bct_data_dir=args.bct_data_dir,
        deck_config_path=args.config,
        output_apkg=output_apkg,
        report_path=args.report,
        migrator_addon_output=args.migrator_addon_output,
        timestamp=args.timestamp,
        deterministic_zip=args.deterministic_zip,
        zip_generated_datetime=args.zip_generated_datetime,
    )
    console_report = {
        "schema": report["schema"],
        "summary": report["summary"],
        "artifacts": report["artifacts"],
    }
    print(json_text(console_report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
