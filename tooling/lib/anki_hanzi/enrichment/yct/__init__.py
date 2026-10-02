"""YCT tag enrichment stage for the hanzi LexiconState."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import re
from typing import Any

from anki_hanzi.enrichment.model import EnrichmentStageResult
from anki_hanzi.lexicon import LexiconState
from anki_hanzi.lexicon.state import LexiconForm
from anki_hanzi.pinyin import strict_numbered_preserve_case


YCT_LEVELS = ("1", "2", "3", "4")
PINYIN_TOKEN_SEPARATOR_RE = re.compile(r"(^|[\s'’·-])(?P<token>r5|er)(?=$|[\s'’·-])")
MANUAL_YCT_FORM_MATCHES: dict[tuple[str, str], tuple[str, ...]] = {
    ("一下儿", "yí xià er"): ("yi1 xia4 r5",),
    ("玫瑰花", "méi gui huā"): ("mei2 gui1 hua1",),
    ("起来", "qǐ lái"): ("qi3 lai5",),
    ("还是", "hái shì"): ("hai2 shi5",),
}


def load_yct_entries(yct_data_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for level in YCT_LEVELS:
        path = yct_data_dir / f"yct_level_{level}.tsv"
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                parts = line.rstrip("\n").split("\t")
                if not parts or not parts[0].strip():
                    continue
                entries.append(
                    {
                        "level": level,
                        "word": parts[0].strip(),
                        "pinyin": parts[1].strip() if len(parts) > 1 else "",
                        "meaning": parts[2].strip() if len(parts) > 2 else "",
                        "path": str(path),
                        "line_number": line_number,
                    }
                )
    return entries


def yct_erhua_key(value: str) -> str:
    def replace_token(match: re.Match[str]) -> str:
        return f"{match.group(1)}er5"

    return PINYIN_TOKEN_SEPARATOR_RE.sub(replace_token, value)


def yct_pinyin_key(value: str) -> str:
    return yct_erhua_key(strict_numbered_preserve_case(value))


def form_pinyin_keys(form: LexiconForm) -> set[str]:
    readings = form.pinyin_readings or [form.pinyin]
    return {key for reading in readings if (key := yct_pinyin_key(reading))}


def manual_yct_forms(
    simplified: str,
    entry: dict[str, Any],
    word_forms: list[LexiconForm],
) -> tuple[list[LexiconForm], str | None]:
    target_pinyin_values = MANUAL_YCT_FORM_MATCHES.get((simplified, entry["pinyin"].strip()))
    if target_pinyin_values is None:
        return [], None

    target_keys = {key for value in target_pinyin_values if (key := yct_pinyin_key(value))}
    matches = [form for form in word_forms if target_keys.intersection(form_pinyin_keys(form))]
    return matches, "manual_yct_match" if matches else "manual_target_missing"


def matching_yct_forms(word_forms: list[LexiconForm], source_key: str) -> tuple[list[LexiconForm], str]:
    exact_matches = [form for form in word_forms if source_key in form_pinyin_keys(form)]
    if exact_matches:
        return exact_matches, "exact_pinyin"

    source_lower_key = source_key.casefold()
    casefold_matches = [
        form for form in word_forms if source_lower_key in {key.casefold() for key in form_pinyin_keys(form)}
    ]
    if len(casefold_matches) == 1:
        return casefold_matches, "unique_casefold_pinyin"
    if len(casefold_matches) > 1:
        return [], "ambiguous_casefold_pinyin"
    return [], "pinyin_mismatch"


def apply_yct_enrichment_to_state(state: LexiconState, yct_data_dir: Path) -> EnrichmentStageResult:
    entries = load_yct_entries(yct_data_dir)
    entries_by_word: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for entry in entries:
        word = entry["word"]
        entries_by_word[word].append(entry)

    tagged_words_by_level = {level: 0 for level in YCT_LEVELS}
    tagged_forms_by_level = {level: 0 for level in YCT_LEVELS}
    match_methods = Counter()
    matched_terms: list[str] = []
    unmatched_terms: list[dict[str, Any]] = []
    partial_matches: list[dict[str, Any]] = []
    manual_matches: list[dict[str, Any]] = []

    for simplified, source_entries in sorted(entries_by_word.items()):
        word = state.words.get(simplified)
        if word is None:
            unmatched_terms.append(
                {
                    "word": simplified,
                    "reason": "missing_dictionary_word",
                    "entries": source_entries,
                }
            )
            continue

        matched_levels: set[str] = set()
        unmatched_source_entries: list[dict[str, Any]] = []
        forms = list(word.forms.values())

        for entry in source_entries:
            source_key = yct_pinyin_key(entry["pinyin"])
            if not source_key:
                unmatched_source_entries.append({**entry, "reason": "missing_pinyin"})
                continue

            tag = f"yct:{entry['level']}"
            matching_forms, match_method = manual_yct_forms(simplified, entry, forms)
            if match_method is None:
                matching_forms, match_method = matching_yct_forms(forms, source_key)

            for form in matching_forms:
                form.add_tags([tag])

            if matching_forms:
                matched_levels.add(entry["level"])
                match_methods[match_method] += 1
                if match_method == "manual_yct_match":
                    manual_matches.append(
                        {
                            "word": simplified,
                            "level": entry["level"],
                            "source_pinyin": entry["pinyin"],
                            "target_pinyin": [form.pinyin_reading_string for form in matching_forms],
                        }
                    )
            else:
                unmatched_source_entries.append({**entry, "reason": match_method})

        if matched_levels:
            matched_terms.append(simplified)
            for level in sorted(matched_levels, key=int):
                tagged_words_by_level[level] += 1
                tagged_forms_by_level[level] += sum(f"yct:{level}" in form.tags for form in forms)
            if unmatched_source_entries:
                partial_matches.append(
                    {
                        "word": simplified,
                        "entries": unmatched_source_entries,
                        "dictionary_pinyin": [form.pinyin_reading_string for form in word.forms_in_order()],
                    }
                )
        else:
            unmatched_terms.append(
                {
                    "word": simplified,
                    "reason": "pinyin_mismatch",
                    "entries": unmatched_source_entries,
                    "dictionary_pinyin": [form.pinyin_reading_string for form in word.forms_in_order()],
                }
            )

    duplicate_source_terms = {
        word: records
        for word, records in entries_by_word.items()
        if len({record["level"] for record in records}) != len(records)
    }

    report = {
        "stage": "yct_enrichment",
        "source": str(yct_data_dir),
        "levels": list(YCT_LEVELS),
        "source_entries": len(entries),
        "source_terms": len(entries_by_word),
        "duplicate_source_terms": len(duplicate_source_terms),
        "matched_terms": len(matched_terms),
        "partially_matched_terms": len(partial_matches),
        "unmatched_terms": len(unmatched_terms),
        "match_methods": dict(sorted(match_methods.items())),
        "manual_matches": manual_matches,
        "tagged_words_by_level": tagged_words_by_level,
        "tagged_forms_by_level": tagged_forms_by_level,
        "unmatched_term_samples": unmatched_terms[:25],
        "partial_match_details": partial_matches,
    }
    return EnrichmentStageResult(
        name="yct_enrichment",
        summary={
            "yct_source_terms": len(entries_by_word),
            "yct_matched_terms": len(matched_terms),
            "yct_partially_matched_terms": len(partial_matches),
            "yct_unmatched_terms": len(unmatched_terms),
            "yct_tags_by_word": tagged_words_by_level,
            "yct_tags_by_form": tagged_forms_by_level,
        },
        report=report,
    )
