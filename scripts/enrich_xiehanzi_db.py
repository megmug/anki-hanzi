#!/usr/bin/env python

"""
Enrich the compact CC-CEDICT master JSON with xiehanzi deck-source data.

This is a separate pipeline stage:

    CC-CEDICT master JSON + xiehanzi TSV files -> enriched JSON -> deck generator

The enriched output keeps the CC-CEDICT words as the organizing structure and
adds xiehanzi study targets under matching `forms[].xiehanzi.study_targets`.
Those entries intentionally mirror the data the Python deck generator currently
needs, while keeping ingestion independent from APKG generation.

Run from the repository root inside the Nix shell:

    nix-shell --run "python scripts/enrich_xiehanzi_db.py"
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from dragonmapper import transcriptions


DEFAULT_MASTER_DB = Path("master_db_output/cc_cedict_master.json")
DEFAULT_OUTPUT = Path("master_db_output/cc_cedict_xiehanzi_enriched.json")
DEFAULT_REPORT = Path("master_db_output/xiehanzi_enrichment_report.json")
DEFAULT_DECK_INPUTS_DIR = Path("deck_inputs")
DEFAULT_HSK_DATA_DIR = DEFAULT_DECK_INPUTS_DIR / "hsk-3.0-words-list/New HSK (2025)/Anki xiehanzi"
DEFAULT_EXTRA_WORDS = DEFAULT_DECK_INPUTS_DIR / "extra_words.tsv"

LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]
XIEHANZI_FIELDS = [
    "Simplified",
    "Traditional",
    "Pinyin",
    "Zhuyin",
    "Level",
    "PoS",
    "Frequency",
    "Meaning HTML",
]


def normalize_field(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", "", value).strip().lower()


def dedupe_key(entry: dict[str, Any]) -> tuple[str, str]:
    return normalize_field(entry["simplified"]), normalize_field(entry["pinyin"])


def printable_key(key: tuple[str, str]) -> str:
    return "::".join(key)


PINYIN_SEPARATOR_RE = re.compile(r"[\s'’\-·]+")


def normalize_pinyin_lookup_key(value: str) -> str:
    return PINYIN_SEPARATOR_RE.sub(
        "",
        normalize_field(value).replace("u:", "v").replace("ü", "v"),
    )


def pinyin_lookup_keys(value: str) -> list[str]:
    keys: list[str] = []
    for part in re.split(r"/", value or ""):
        if not part.strip():
            continue

        if re.search(r"\d", part):
            numbered = part
        else:
            try:
                numbered = transcriptions.accented_to_numbered(part)
            except ValueError:
                numbered = part

        key = normalize_pinyin_lookup_key(numbered)
        if key and key not in keys:
            keys.append(key)
    return keys


def pinyin_lookup_key(value: str) -> str:
    keys = pinyin_lookup_keys(value)
    return keys[0] if keys else ""


def toneless_pinyin_lookup_key(value: str) -> str:
    return re.sub(r"\d", "", pinyin_lookup_key(value))


def toneless_pinyin_lookup_keys(value: str) -> list[str]:
    keys: list[str] = []
    for key in pinyin_lookup_keys(value):
        toneless_key = re.sub(r"\d", "", key)
        if toneless_key and toneless_key not in keys:
            keys.append(toneless_key)
    return keys


def parse_frequency(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def normalize_hsk_level(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if value in {"7", "8", "9", "7-9"}:
        return "7-9"
    if value in {"1", "2", "3", "4", "5", "6"}:
        return value
    return None


def level_tags(source_level: str, raw_level: str) -> list[str]:
    levels: list[str] = []
    for value in [source_level, *re.findall(r"7-9|[1-9]", raw_level or "")]:
        normalized = normalize_hsk_level(value)
        if normalized and normalized not in levels:
            levels.append(normalized)
    return [f"hsk:{level}" for level in levels]


def entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "simplified": entry["simplified"],
        "traditional": entry["traditional"],
        "pinyin": entry["pinyin"],
        "zhuyin": entry["zhuyin"],
        "deck_level": entry["deck_level"],
        "raw_level": entry["raw_level"],
        "source": entry["source"],
    }


def make_entry(
    row: list[str],
    source: str,
    source_file: Path,
    row_number: int,
    deck_level: str,
) -> dict[str, Any]:
    if len(row) < len(XIEHANZI_FIELDS):
        raise ValueError(f"Expected at least 8 TSV columns in {source_file}:{row_number}, got {len(row)}: {row!r}")

    simplified = row[0]
    traditional = row[1]
    pinyin = row[2]
    zhuyin = row[3]
    raw_level = row[4]
    pos = row[5]
    frequency_text = row[6]
    meaning_html = row[7]

    tags = ["source:xiehanzi", *level_tags(deck_level, raw_level)]
    if source == "Extra":
        tags.append("extra")

    return {
        "simplified": simplified,
        "traditional": traditional,
        "pinyin": pinyin,
        "zhuyin": zhuyin,
        "deck_level": deck_level,
        "raw_level": raw_level,
        "pos": pos,
        "frequency": parse_frequency(frequency_text),
        "meaning_html": meaning_html,
        "audio_filename": f"cmn-{simplified}.mp3",
        "source": source,
        "tags": sorted(set(tags)),
    }


def read_word_file(path: Path, source: str, deck_level: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row_number, row in enumerate(csv.reader(handle, delimiter="\t"), start=1):
            if not row:
                continue
            if row[0].startswith("#"):
                continue
            entries.append(
                make_entry(
                    row,
                    source=source,
                    source_file=path,
                    row_number=row_number,
                    deck_level=deck_level,
                )
            )
    return entries


def load_xiehanzi_entries(hsk_data_dir: Path, extra_words: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for level in LEVELS:
        path = hsk_data_dir / f"HSK_Level_{level}.txt"
        entries.extend(read_word_file(path, source=f"HSK {level}", deck_level=level))

    if extra_words.exists():
        entries.extend(read_word_file(extra_words, source="Extra", deck_level="Extra"))

    return entries


def dedupe_entries(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    kept_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    kept_entries: list[dict[str, Any]] = []
    dropped_duplicates: list[dict[str, Any]] = []
    skipped_extra_duplicates: list[dict[str, Any]] = []
    next_deck_order = {level: 0 for level in [*LEVELS, "Extra"]}

    for entry in entries:
        key = dedupe_key(entry)
        existing = kept_by_key.get(key)
        if existing is None:
            entry["deck_order"] = next_deck_order[entry["deck_level"]]
            next_deck_order[entry["deck_level"]] += 1
            kept_by_key[key] = entry
            kept_entries.append(entry)
            continue

        duplicate_record = {
            "key": printable_key(key),
            "kept": entry_summary(existing),
            "dropped": entry_summary(entry),
            "reason": "already present in HSK data" if entry["source"] == "Extra" else "duplicate xiehanzi entry",
        }
        if entry["source"] == "Extra":
            skipped_extra_duplicates.append(duplicate_record)
        else:
            dropped_duplicates.append(duplicate_record)

    return kept_entries, dropped_duplicates, skipped_extra_duplicates


def build_word_index(words: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for word in words:
        key = normalize_field(str(word.get("simplified") or ""))
        if key:
            index[key] = word
    return index


LI_RE = re.compile(r"<li>(.*?)</li>", re.IGNORECASE | re.DOTALL)


def strip_html_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def definitions_from_meaning_html(value: str) -> list[str]:
    parts = LI_RE.findall(value or "") or [value]
    definitions: list[str] = []
    seen: set[str] = set()

    for part in parts:
        definition = strip_html_text(part)
        if not definition or definition in seen:
            continue
        definitions.append(definition)
        seen.add(definition)

    return definitions


def build_synthetic_words(missing_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_simplified: dict[str, dict[str, Any]] = {}

    for entry in missing_entries:
        simplified = entry["simplified"]
        word = by_simplified.get(simplified)
        if word is None:
            word = {
                "simplified": simplified,
                "traditional_variants": [],
                "forms_by_pinyin": {},
                "tags": ["missing:cc-cedict", "source:xiehanzi"],
            }
            by_simplified[simplified] = word

        traditional = entry["traditional"]
        if traditional and traditional not in word["traditional_variants"]:
            word["traditional_variants"].append(traditional)

        form_key = entry["pinyin"]
        form = word["forms_by_pinyin"].get(form_key)
        if form is None:
            form = {
                "traditional_variants": [],
                "pinyin": entry["pinyin"],
                "definitions": [],
                "tags": [],
            }
            word["forms_by_pinyin"][form_key] = form

        if traditional and traditional not in form["traditional_variants"]:
            form["traditional_variants"].append(traditional)

        append_unique(form["definitions"], definitions_from_meaning_html(entry["meaning_html"]))
        append_unique(form["tags"], entry["tags"])
        form["tags"].sort()

    synthetic_words: list[dict[str, Any]] = []
    for word in by_simplified.values():
        forms = list(word.pop("forms_by_pinyin").values())
        forms.sort(key=lambda form: form["pinyin"])
        word["forms"] = forms
        synthetic_words.append(word)

    return sorted(synthetic_words, key=lambda word: word["simplified"])


def append_unique(values: list[str], new_values: list[str]) -> None:
    seen = set(values)
    for value in new_values:
        if value in seen:
            continue
        values.append(value)
        seen.add(value)


def prefer_first(values: list[str], value: str) -> None:
    if not value:
        return
    if value in values:
        values.remove(value)
    values.insert(0, value)


def study_target_payload(entry: dict[str, Any]) -> dict[str, Any]:
    payload = dict(entry)
    payload.pop("simplified", None)
    payload.pop("traditional", None)
    payload.pop("meaning_html", None)
    payload.pop("audio_filename", None)
    payload.pop("frequency", None)
    payload.pop("source", None)
    payload.pop("tags", None)
    return payload


def find_or_create_xiehanzi_form(
    word: dict[str, Any],
    entry: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    forms = word.setdefault("forms", [])
    entry_keys = pinyin_lookup_keys(entry["pinyin"])

    for form in forms:
        form_keys = pinyin_lookup_keys(str(form.get("pinyin") or ""))
        if set(form_keys).intersection(entry_keys):
            form_stats["matched"] += 1
            if form_keys != entry_keys:
                form_stats["matched_pinyin_variant"] += 1
            return form

    entry_toneless_keys = toneless_pinyin_lookup_keys(entry["pinyin"])
    toneless_matches = [
        form
        for form in forms
        if set(toneless_pinyin_lookup_keys(str(form.get("pinyin") or ""))).intersection(entry_toneless_keys)
    ]
    if len(toneless_matches) == 1:
        form_stats["matched"] += 1
        form_stats["matched_toneless"] += 1
        return toneless_matches[0]

    form = {
        "traditional_variants": [],
        "pinyin": entry["pinyin"],
        "definitions": definitions_from_meaning_html(entry["meaning_html"]),
        "tags": ["missing:cc-cedict-form", "source:xiehanzi"],
    }
    forms.append(form)
    forms.sort(key=lambda form: form["pinyin"])
    form_stats["created"] += 1
    form_stats["created_entries"].append({
        "entry": entry_summary(entry),
        "lookup_key": entry_keys[0] if entry_keys else "",
        "lookup_keys": entry_keys,
        "available_form_pinyins": [
            str(existing_form.get("pinyin") or "")
            for existing_form in forms
            if existing_form is not form
        ],
    })
    return form


def attach_deck_entries_to_words(
    words: list[dict[str, Any]],
    deck_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    word_index = build_word_index(words)
    unmatched: list[dict[str, Any]] = []
    form_stats = {
        "matched": 0,
        "matched_pinyin_variant": 0,
        "matched_toneless": 0,
        "created": 0,
        "created_entries": [],
    }

    for entry in deck_entries:
        word = word_index.get(normalize_field(entry["simplified"]))
        if word is None:
            unmatched.append(entry_summary(entry))
            continue

        word.setdefault("tags", [])
        append_unique(word["tags"], entry["tags"])
        word["tags"].sort()

        xiehanzi = word.setdefault("xiehanzi", {})
        xiehanzi.setdefault("frequency", entry["frequency"])

        form = find_or_create_xiehanzi_form(word, entry, form_stats)
        prefer_first(form.setdefault("traditional_variants", []), entry["traditional"])
        append_unique(form.setdefault("tags", []), entry["tags"])
        form["tags"].sort()

        if entry.get("pinyin"):
            try:
                form["pinyin"] = transcriptions.accented_to_numbered(entry["pinyin"])
            except ValueError:
                pass

    return unmatched, form_stats


def summarize_by_level(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = {level: 0 for level in [*LEVELS, "Extra"]}
    for entry in entries:
        counts[entry["deck_level"]] = counts.get(entry["deck_level"], 0) + 1
    return counts


def enrich_database(
    master_db_path: Path,
    output_path: Path,
    report_path: Path,
    hsk_data_dir: Path,
    extra_words: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    master_db = json.loads(master_db_path.read_text(encoding="utf-8"))
    base_words = list(master_db.get("words") or [])
    base_word_index = build_word_index(base_words)

    raw_entries = load_xiehanzi_entries(hsk_data_dir=hsk_data_dir, extra_words=extra_words)
    deck_entries, dropped_duplicates, skipped_extra_duplicates = dedupe_entries(raw_entries)

    missing_raw_before_stubs = [
        entry_summary(entry)
        for entry in raw_entries
        if normalize_field(entry["simplified"]) not in base_word_index
    ]
    missing_deck_entries_before_stubs = [
        entry
        for entry in deck_entries
        if normalize_field(entry["simplified"]) not in base_word_index
    ]
    synthetic_words = build_synthetic_words(missing_deck_entries_before_stubs)
    words = [*base_words, *synthetic_words]
    words.sort(key=lambda word: word["simplified"])
    missing_deck_after_stubs, form_stats = attach_deck_entries_to_words(words, deck_entries)

    enriched = {
        "schema": "xiehanzi-enriched-lexicon-v1",
        "base": {
            "schema": master_db.get("schema"),
            "source": master_db.get("source"),
            "summary": master_db.get("summary"),
        },
        "enrichment": {
            "name": "xiehanzi New HSK (2025)",
            "fields": XIEHANZI_FIELDS,
            "hsk_data_dir": str(hsk_data_dir),
            "extra_words": str(extra_words) if extra_words.exists() else None,
            "dedupe_key": "Simplified + normalized Pinyin",
        },
        "summary": {
            "base_words": len(base_words),
            "synthetic_xiehanzi_words": len(synthetic_words),
            "total_words": len(words),
            "raw_xiehanzi_entries": len(raw_entries),
            "deck_entries_after_dedupe": len(deck_entries),
            "dropped_duplicate_entries": len(dropped_duplicates),
            "skipped_extra_duplicates": len(skipped_extra_duplicates),
            "raw_entries_missing_base_word": len(missing_raw_before_stubs),
            "deck_entries_missing_base_word": len(missing_deck_entries_before_stubs),
            "deck_entries_missing_enriched_word": len(missing_deck_after_stubs),
            "deck_entries_by_level": summarize_by_level(deck_entries),
            "xiehanzi_form_targets": form_stats["matched"] + form_stats["created"],
            "xiehanzi_form_matches": form_stats["matched"],
            "xiehanzi_form_pinyin_variant_matches": form_stats["matched_pinyin_variant"],
            "xiehanzi_form_toneless_matches": form_stats["matched_toneless"],
            "xiehanzi_form_stubs_created": form_stats["created"],
        },
        "words": words,
        "xiehanzi": {
            "study_targets_location": "words[].forms[].xiehanzi.study_targets",
            "dropped_duplicates": dropped_duplicates,
            "skipped_extra_duplicates": skipped_extra_duplicates,
        },
    }

    report = {
        "schema": "xiehanzi-enrichment-report-v1",
        "input": str(master_db_path),
        "output": str(output_path),
        "report": str(report_path),
        "summary": enriched["summary"],
        "samples": {
            "missing_raw_entries": missing_raw_before_stubs[:25],
            "missing_deck_entries": [
                entry_summary(entry)
                for entry in missing_deck_entries_before_stubs[:25]
            ],
            "synthetic_words": synthetic_words[:25],
            "missing_deck_entries_after_stubs": missing_deck_after_stubs[:25],
            "xiehanzi_form_stubs": form_stats["created_entries"],
            "dropped_duplicates": dropped_duplicates[:25],
            "skipped_extra_duplicates": skipped_extra_duplicates[:25],
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return enriched, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-db", type=Path, default=DEFAULT_MASTER_DB, help="Input compact CC-CEDICT master JSON.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output enriched JSON.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="Output enrichment report JSON.")
    parser.add_argument("--hsk-data-dir", type=Path, default=DEFAULT_HSK_DATA_DIR, help="Prepared xiehanzi HSK TSV directory.")
    parser.add_argument("--extra-words", type=Path, default=DEFAULT_EXTRA_WORDS, help="Optional extra words TSV.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.master_db.exists():
        print(f"missing master DB: {args.master_db}")
        return 2
    if not args.hsk_data_dir.exists():
        print(f"missing xiehanzi HSK data dir: {args.hsk_data_dir}")
        return 2

    enriched, _report = enrich_database(
        master_db_path=args.master_db,
        output_path=args.output,
        report_path=args.report,
        hsk_data_dir=args.hsk_data_dir,
        extra_words=args.extra_words,
    )

    print("xiehanzi enrichment generated")
    print(f"input: {args.master_db}")
    print(f"output: {args.output}")
    print(f"report: {args.report}")
    print(json.dumps(enriched["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
