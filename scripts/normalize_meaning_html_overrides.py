#!/usr/bin/env python

"""
Remove exactly reproducible legacy Meaning HTML overrides.

The enriched database can temporarily contain old `meaning_html` strings. This
script removes only those overrides where `render_meaning_html(word)` recreates
the old HTML byte-for-byte. The deck generator falls back to the renderer when a
study target no longer carries a legacy override.
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from meaning_html import render_meaning_html


DEFAULT_INPUT = Path("master_db_output/cc_cedict_xiehanzi_enriched.json")
DEFAULT_OUTPUT = DEFAULT_INPUT
DEFAULT_REPORT = Path("master_db_output/meaning_html_normalization_report.json")
DEFAULT_DIFF_REPORT = Path("master_db_output/meaning_html_diff_report.md")
HTML_TAG_RE = re.compile(r"<[^>]+>")
HTML_TOKEN_RE = re.compile(r"<[^>]+>|[^<]+")
LI_RE = re.compile(r"<li>(.*?)</li>", re.DOTALL)
PINYIN_WRAPPER_RE = re.compile(
    r'<span class="pinYinWrapper">(.*?)</span>\s*<ul>',
    re.DOTALL,
)


def collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def strip_html_tags(value: str) -> str:
    return HTML_TAG_RE.sub("", value)


def normalized_text(value: str) -> str:
    return collapse_spaces(html.unescape(strip_html_tags(value)).replace("\xa0", " "))


def extract_li_texts(value: str) -> list[str]:
    return [normalized_text(item) for item in LI_RE.findall(value)]


def extract_pinyin_texts(value: str) -> list[str]:
    return [normalized_text(item) for item in PINYIN_WRAPPER_RE.findall(value)]


def first_difference(left: str, right: str) -> dict[str, Any]:
    for index, (left_char, right_char) in enumerate(zip(left, right)):
        if left_char != right_char:
            return {
                "index": index,
                "legacy_context": left[max(0, index - 80):index + 120],
                "rendered_context": right[max(0, index - 80):index + 120],
            }
    index = min(len(left), len(right))
    return {
        "index": index,
        "legacy_context": left[max(0, index - 80):index + 120],
        "rendered_context": right[max(0, index - 80):index + 120],
    }


def html_tokens(value: str) -> list[str]:
    return [
        token
        for token in (part.strip() for part in HTML_TOKEN_RE.findall(value))
        if token
    ]


def diff_preview(left: str, right: str, max_lines: int = 80) -> list[str]:
    diff = list(difflib.unified_diff(
        html_tokens(left),
        html_tokens(right),
        fromfile="legacy",
        tofile="rendered",
        lineterm="",
        n=0,
    ))
    if len(diff) <= max_lines:
        return diff
    return [*diff[:max_lines], f"... diff truncated; {len(diff) - max_lines} more lines"]


def list_diff(left: list[str], right: list[str], left_label: str, right_label: str) -> list[str]:
    return list(difflib.unified_diff(
        left,
        right,
        fromfile=left_label,
        tofile=right_label,
        lineterm="",
        n=0,
    ))


def classify_difference(legacy_html: str, rendered_html: str) -> dict[str, Any]:
    legacy_definitions = extract_li_texts(legacy_html)
    rendered_definitions = extract_li_texts(rendered_html)
    legacy_pinyin = extract_pinyin_texts(legacy_html)
    rendered_pinyin = extract_pinyin_texts(rendered_html)
    legacy_text = normalized_text(legacy_html)
    rendered_text = normalized_text(rendered_html)

    pinyin_changed = legacy_pinyin != rendered_pinyin
    definitions_changed = legacy_definitions != rendered_definitions
    text_changed = legacy_text != rendered_text

    if not text_changed:
        reason = "markup_only"
    elif pinyin_changed and definitions_changed:
        reason = "pinyin_and_definition_text"
    elif definitions_changed:
        reason = "definition_text"
    elif pinyin_changed:
        reason = "pinyin_text"
    else:
        reason = "other_text_or_markup"

    diffs: list[dict[str, Any]] = []
    if pinyin_changed:
        diffs.append({
            "name": "pinyin",
            "lines": list_diff(
                legacy_pinyin,
                rendered_pinyin,
                "legacy pinyin",
                "rendered pinyin",
            ),
        })
    if definitions_changed:
        diffs.append({
            "name": "definitions",
            "lines": list_diff(
                legacy_definitions,
                rendered_definitions,
                "legacy definitions",
                "rendered definitions",
            ),
        })
    if not diffs:
        diffs.append({
            "name": "html tokens",
            "lines": diff_preview(legacy_html, rendered_html),
        })

    return {
        "reason": reason,
        "pinyin_changed": pinyin_changed,
        "definitions_changed": definitions_changed,
        "text_changed": text_changed,
        "legacy": {
            "pinyin": legacy_pinyin,
            "definition_count": len(legacy_definitions),
        },
        "rendered": {
            "pinyin": rendered_pinyin,
            "definition_count": len(rendered_definitions),
        },
        "first_difference": first_difference(legacy_html, rendered_html),
        "diffs": diffs,
    }


def iter_study_targets(word: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        target
        for form in word.get("forms", [])
        for target in (form.get("xiehanzi") or {}).get("study_targets", [])
    ]


def normalize_database(database: dict[str, Any]) -> dict[str, Any]:
    legacy_total = 0
    removed = 0
    retained = 0
    already_missing = 0
    rendered_words = 0
    reason_counts: Counter[str] = Counter()
    retained_candidates: list[dict[str, Any]] = []

    for word in database.get("words", []):
        targets = iter_study_targets(word)
        if not targets:
            continue

        rendered = render_meaning_html(word)
        rendered_words += 1

        for target in targets:
            legacy_html = target.get("meaning_html")
            if legacy_html is None:
                already_missing += 1
                continue

            legacy_total += 1
            if legacy_html == rendered:
                target.pop("meaning_html", None)
                removed += 1
            else:
                retained += 1
                classification = classify_difference(str(legacy_html), rendered)
                reason_counts.update([classification["reason"]])
                retained_candidates.append({
                    "simplified": word.get("simplified"),
                    "traditional_variants": word.get("traditional_variants", []),
                    "target_pinyin": target.get("pinyin"),
                    "deck_level": target.get("deck_level"),
                    "raw_level": target.get("raw_level"),
                    "deck_order": target.get("deck_order"),
                    **classification,
                })

    database["schema"] = "xiehanzi-enriched-lexicon-v1"
    database.setdefault("xiehanzi", {})["meaning_html_overrides"] = {
        "policy": "legacy meaning_html is kept only when the renderer is not byte-exact",
        "renderer": "scripts/meaning_html.py",
        "location": "words[].forms[].xiehanzi.study_targets[].meaning_html",
        "removed_exact_overrides": removed,
        "retained_legacy_overrides": retained,
        "already_missing_overrides": already_missing,
    }

    return {
        "schema": "xiehanzi-meaning-html-normalization-report-v1",
        "summary": {
            "words_rendered": rendered_words,
            "legacy_overrides_seen": legacy_total,
            "removed_exact_overrides": removed,
            "retained_legacy_overrides": retained,
            "already_missing_overrides": already_missing,
            "retained_reason_counts": dict(sorted(reason_counts.items())),
        },
        "retained_legacy_overrides": retained_candidates,
    }


def markdown_code_block(lines: list[str]) -> list[str]:
    return [
        "```diff",
        *(lines if lines else ["(no diff)"]),
        "```",
    ]


def render_markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    output = [
        "# Meaning HTML Diff Review",
        "",
        f"Rendered words: {summary['words_rendered']} | "
        f"legacy overrides seen: {summary['legacy_overrides_seen']} | "
        f"exact overrides removed: {summary['removed_exact_overrides']} | "
        f"retained overrides: {summary['retained_legacy_overrides']}",
        "",
        "Reason counts:",
        "",
    ]

    for reason, count in summary["retained_reason_counts"].items():
        output.append(f"- `{reason}`: {count}")

    output.extend(["", "## Candidates", ""])
    for index, candidate in enumerate(report["retained_legacy_overrides"], start=1):
        output.extend([
            f"### {index:03d}. {candidate['simplified']} | "
            f"{candidate['target_pinyin']} | level {candidate['deck_level']} | "
            f"`{candidate['reason']}`",
            "",
        ])
        for diff in candidate["diffs"]:
            output.extend([
                f"{diff['name']}:",
                *markdown_code_block(diff["lines"]),
                "",
            ])

    return "\n".join(output).rstrip() + "\n"


def compact_json_report(report: dict[str, Any], diff_report_path: Path) -> dict[str, Any]:
    return {
        "schema": report["schema"],
        "summary": report["summary"],
        "retained_legacy_overrides_report": str(diff_report_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input enriched JSON path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output enriched JSON path.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="Output report path.")
    parser.add_argument(
        "--diff-report",
        type=Path,
        default=DEFAULT_DIFF_REPORT,
        help="Output human-readable retained-override diff report path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database = json.loads(args.input.read_text(encoding="utf-8"))
    report = normalize_database(database)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(database, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.diff_report.parent.mkdir(parents=True, exist_ok=True)
    args.diff_report.write_text(render_markdown_report(report), encoding="utf-8")
    args.report.write_text(
        json.dumps(
            compact_json_report(report, args.diff_report),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    print("meaning HTML normalization complete")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
