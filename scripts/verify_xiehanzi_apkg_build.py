#!/usr/bin/env python

"""Compare reference and candidate xiehanzi APKG builds."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_summary(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": str(path),
        "size": len(data),
        "sha256": sha256_bytes(data),
    }


def zip_info_summary(info: zipfile.ZipInfo) -> dict[str, Any]:
    return {
        "name": info.filename,
        "size": info.file_size,
        "compressed_size": info.compress_size,
        "crc32": f"{info.CRC:08x}",
        "date_time": list(info.date_time),
        "compress_type": info.compress_type,
        "external_attr": info.external_attr,
        "create_system": info.create_system,
    }


def compare_zip_infos(
    reference_infos: list[zipfile.ZipInfo],
    candidate_infos: list[zipfile.ZipInfo],
) -> tuple[list[dict[str, Any]], bool]:
    metadata_diffs: list[dict[str, Any]] = []
    metadata_equal = True

    for reference_info, candidate_info in zip(reference_infos, candidate_infos):
        reference_summary = zip_info_summary(reference_info)
        candidate_summary = zip_info_summary(candidate_info)
        field_diffs = {
            key: {
                "reference": reference_summary[key],
                "candidate": candidate_summary[key],
            }
            for key in reference_summary
            if reference_summary[key] != candidate_summary[key]
        }
        if field_diffs:
            metadata_equal = False
            metadata_diffs.append({
                "name": reference_info.filename,
                "fields": field_diffs,
            })

    if len(reference_infos) != len(candidate_infos):
        metadata_equal = False

    return metadata_diffs, metadata_equal


def compare_zip_contents(reference: Path, candidate: Path) -> dict[str, Any]:
    with zipfile.ZipFile(reference) as reference_zip, zipfile.ZipFile(candidate) as candidate_zip:
        reference_infos = reference_zip.infolist()
        candidate_infos = candidate_zip.infolist()
        reference_names = [info.filename for info in reference_infos]
        candidate_names = [info.filename for info in candidate_infos]
        names_equal = reference_names == candidate_names
        metadata_diffs, metadata_equal = compare_zip_infos(reference_infos, candidate_infos)

        content_diffs: list[str] = []
        key_members: dict[str, dict[str, Any]] = {}
        common_names = [name for name in reference_names if name in set(candidate_names)]

        for name in common_names:
            reference_data = reference_zip.read(name)
            candidate_data = candidate_zip.read(name)
            equal = reference_data == candidate_data
            if not equal:
                content_diffs.append(name)
            if name in {"collection.anki2", "media"}:
                key_members[name] = {
                    "equal": equal,
                    "reference_size": len(reference_data),
                    "candidate_size": len(candidate_data),
                    "reference_sha256": sha256_bytes(reference_data),
                    "candidate_sha256": sha256_bytes(candidate_data),
                }

        media_payload_diffs = [
            name for name in content_diffs if name not in {"collection.anki2", "media"}
        ]

    return {
        "entry_count": {
            "reference": len(reference_infos),
            "candidate": len(candidate_infos),
        },
        "names_equal": names_equal,
        "metadata_equal": metadata_equal,
        "metadata_diff_count": len(metadata_diffs),
        "metadata_diffs_first": metadata_diffs[:10],
        "content_equal": not content_diffs and names_equal,
        "content_diff_count": len(content_diffs),
        "content_diffs_first": content_diffs[:20],
        "media_payload_equal": not media_payload_diffs,
        "media_payload_diff_count": len(media_payload_diffs),
        "media_payload_diffs_first": media_payload_diffs[:20],
        "key_members": key_members,
    }


def build_report(reference: Path, candidate: Path) -> dict[str, Any]:
    reference_summary = file_summary(reference)
    candidate_summary = file_summary(candidate)
    zip_summary = compare_zip_contents(reference, candidate)
    byte_equal = reference.read_bytes() == candidate.read_bytes()

    return {
        "schema": "xiehanzi-apkg-build-verification-v1",
        "status": "ok" if byte_equal else "changed",
        "byte_equal": byte_equal,
        "reference": reference_summary,
        "candidate": candidate_summary,
        "zip": zip_summary,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True, help="Reference APKG path.")
    parser.add_argument("--candidate", type=Path, required=True, help="Candidate APKG path.")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON report path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args.reference, args.candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["byte_equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
