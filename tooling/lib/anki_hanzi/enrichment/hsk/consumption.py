"""Consumption rules for xiehanzi matching and LexiconState enrichment.

The first rule layer mutates only pipeline working sets. The second layer
applies the selected buckets to the LexiconState.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from anki_hanzi.lexicon import LexiconForm, LexiconState, LexiconWord
from anki_hanzi.pinyin import (
    apply_reference_pinyin_case,
    numbered_pinyin,
    pinyin_formatting_key,
    pinyin_reading_in_reference_spacing,
    source_pinyin_in_dictionary_format,
)
from anki_hanzi.enrichment.hsk.rule_helpers import (
    definition_sets_exact,
    definitions_from_meaning_html,
    pinyin_rule_kind,
)
from anki_hanzi.enrichment.hsk.model import (
    HskMatchingPair,
    HskSourceForm,
    PairConsumption,
    SourcePreludeConsumption,
    bucket_matching_pair_count,
    bucket_source_form_ids,
    item_source_form_id,
)
from anki_hanzi.enrichment.hsk.source import entry_summary


SourcePreludeConsumptionHandler = Callable[[list[HskSourceForm], set[int]], SourcePreludeConsumption]
PairConsumptionHandler = Callable[[list[HskMatchingPair], list[HskMatchingPair]], PairConsumption]
ConsumptionRuleHandler = SourcePreludeConsumptionHandler | PairConsumptionHandler
MissingDictionaryWordStateHandler = Callable[[LexiconState, list[dict[str, Any]], dict[str, Any]], dict[str, Any]]
BucketStateHandler = Callable[[LexiconState, list[dict[str, Any]], dict[str, Any], dict[str, Any]], dict[str, Any]]
StateConsumptionRuleHandler = MissingDictionaryWordStateHandler | BucketStateHandler


@dataclass(frozen=True)
class ConsumptionRuleDefinition:
    name: str
    report_only_effect: str
    enrichment_effect: str
    handler: ConsumptionRuleHandler

    def consume_source_prelude(
        self,
        selected_items: list[HskSourceForm],
        remaining_source_form_ids: set[int],
    ) -> SourcePreludeConsumption:
        handler = cast(SourcePreludeConsumptionHandler, self.handler)
        return handler(selected_items, remaining_source_form_ids)

    def consume_pairs(
        self,
        selected_items: list[HskMatchingPair],
        remaining_items: list[HskMatchingPair],
    ) -> PairConsumption:
        handler = cast(PairConsumptionHandler, self.handler)
        return handler(selected_items, remaining_items)


@dataclass(frozen=True)
class StateConsumptionRuleDefinition:
    name: str
    bucket: str
    state_effect: str
    handler: StateConsumptionRuleHandler

    def apply_to_state(
        self,
        state: LexiconState,
        deck_entries: list[dict[str, Any]],
        pipeline: dict[str, Any],
        form_stats: dict[str, Any],
    ) -> dict[str, Any]:
        if self.bucket == "missing_dictionary_word":
            handler = cast(MissingDictionaryWordStateHandler, self.handler)
            return handler(state, deck_entries, pipeline)

        handler = cast(BucketStateHandler, self.handler)
        return handler(state, deck_entries, pipeline, form_stats)


def build_synthetic_words(missing_entries: list[dict[str, Any]]) -> list[LexiconWord]:
    by_simplified: dict[str, LexiconWord] = {}

    for entry in missing_entries:
        simplified = entry["simplified"]
        word = by_simplified.get(simplified)
        if word is None:
            word = LexiconWord(simplified=simplified)
            by_simplified[simplified] = word

        word.add_tags(entry["tags"])
        word.set_hanzi_frequency_once(entry["frequency"])

        form_key = numbered_pinyin(entry["pinyin"])
        form = word.forms.get(form_key)
        if form is None:
            form = LexiconForm(pinyin=form_key, tags=[])
            word.forms[form_key] = form

        form.append_definitions(definitions_from_meaning_html(entry["meaning_html"]))
        form.add_tags(entry["tags"])

    for word in by_simplified.values():
        word.sort_forms_by_pinyin()

    return sorted(by_simplified.values(), key=lambda word: word.simplified)


def record_form_match(form_stats: dict[str, Any], match_type: str) -> None:
    form_stats["match_types"][match_type] += 1


def non_exact_match_record(
    entry: dict[str, Any],
    match_type: str,
    cc_cedict_pinyin: str | None,
    cc_cedict_definitions: list[str],
    xiehanzi_pinyin: str,
) -> dict[str, Any]:
    return {
        "simplified": entry["simplified"],
        "match_type": match_type,
        "cc_cedict_pinyin": cc_cedict_pinyin,
        "xiehanzi_pinyin": xiehanzi_pinyin,
        "xiehanzi_raw_pinyin": entry.get("raw_pinyin", entry["pinyin"]),
        "cc_cedict_definitions": cc_cedict_definitions,
        "xiehanzi_definitions": definitions_from_meaning_html(entry["meaning_html"]),
    }


def normalized_definition_set(definitions: list[str]) -> set[str]:
    return {re.sub(r"\s+", " ", definition).strip() for definition in definitions if definition.strip()}


def definitions_differ(left: list[str], right: list[str]) -> bool:
    return normalized_definition_set(left) != normalized_definition_set(right)


def new_form_stats() -> dict[str, Any]:
    return {
        "matched": 0,
        "match_types": {
            "exact": 0,
            "format_variant": 0,
            "case_variant": 0,
            "spoken_tone_variant": 0,
            "exact_definition": 0,
            "exact_definition_also_pr": 0,
            "semicolon_split_exact_definition_also_pr": 0,
            "html_subform_definition_cover": 0,
            "source_see_colloquial_pr": 0,
        },
        "non_exact_matches": [],
        "non_exact_definition_mismatches": [],
        "pinyin_case_preserved": [],
        "pinyin_whitespace_only": [],
        "pinyin_substantive": [],
    }


def drop_missing_dictionary_word_source_forms(
    selected_items: list[HskSourceForm],
    remaining_source_form_ids: set[int],
) -> SourcePreludeConsumption:
    consumed_source_form_ids = bucket_source_form_ids(selected_items) & remaining_source_form_ids
    remaining_source_form_ids.difference_update(consumed_source_form_ids)
    return {
        "consumed_source_form_ids": consumed_source_form_ids,
        "consumed_source_form_count": len(consumed_source_form_ids),
        "consumed_matching_pair_count": 0,
        "remaining_source_form_count": len(remaining_source_form_ids),
    }


def drop_source_form_pairs(
    selected_items: list[HskMatchingPair],
    remaining_items: list[HskMatchingPair],
) -> PairConsumption:
    consumed_source_form_ids = bucket_source_form_ids(selected_items)
    remaining_after_consumption: list[HskMatchingPair] = []
    removed_from_remaining_items: list[HskMatchingPair] = []

    for item in remaining_items:
        if item.source_form_id in consumed_source_form_ids:
            removed_from_remaining_items.append(item)
        else:
            remaining_after_consumption.append(item)

    return {
        "consumed_source_form_ids": consumed_source_form_ids,
        "consumed_source_form_count": len(consumed_source_form_ids),
        "consumed_matching_pair_count": bucket_matching_pair_count(selected_items)
        + bucket_matching_pair_count(removed_from_remaining_items),
        "removed_from_remaining_matching_pair_count": bucket_matching_pair_count(removed_from_remaining_items),
        "remaining_items": remaining_after_consumption,
    }


def assert_default_unresolved_empty_pairs(
    selected_items: list[HskMatchingPair],
    remaining_items: list[HskMatchingPair],
) -> PairConsumption:
    if selected_items:
        sample = [
            {
                "source_form_id": item.source_form_id,
                "source": item.source_form.source_report(),
                "target": item.target_report(),
            }
            for item in selected_items[:10]
        ]
        raise ValueError(
            "xiehanzi enrichment left unresolved matching pairs in default_unresolved; "
            f"add a matching/consumption rule before building. count={len(selected_items)} sample={sample!r}"
        )

    return {
        "consumed_source_form_ids": set(),
        "consumed_source_form_count": 0,
        "consumed_matching_pair_count": 0,
        "removed_from_remaining_matching_pair_count": 0,
        "remaining_items": remaining_items,
    }


DROP_MISSING_DICTIONARY_WORD_SOURCE_FORMS_RULE = ConsumptionRuleDefinition(
    name="drop_missing_dictionary_word_source_forms",
    report_only_effect="remove the source form from the pair pipeline before any pairs are materialized",
    enrichment_effect="create synthetic words/forms from xiehanzi source entries",
    handler=drop_missing_dictionary_word_source_forms,
)
DROP_PERFECT_MATCH_SOURCE_FORM_PAIRS_RULE = ConsumptionRuleDefinition(
    name="drop_perfect_match_source_form_pairs",
    report_only_effect="remove all remaining matching pairs for the consumed source form",
    enrichment_effect="apply exact-pair tags and metadata directly to the selected dictionary form",
    handler=drop_source_form_pairs,
)
DROP_MANUAL_PINYIN_OVERRIDE_SOURCE_FORM_PAIRS_RULE = ConsumptionRuleDefinition(
    name="drop_manual_pinyin_override_source_form_pairs",
    report_only_effect="remove all remaining matching pairs for the manually corrected source form",
    enrichment_effect="apply the configured Pinyin override directly to the selected dictionary form",
    handler=drop_source_form_pairs,
)
DROP_FORMAT_VARIANT_SOURCE_FORM_PAIRS_RULE = ConsumptionRuleDefinition(
    name="drop_format_variant_source_form_pairs",
    report_only_effect="remove all remaining matching pairs for the format-variant source form",
    enrichment_effect="apply tags and metadata directly to the selected dictionary form without changing Pinyin",
    handler=drop_source_form_pairs,
)
CONSUME_SPOKEN_TONE_VARIANT_SOURCE_FORM_PAIRS_RULE = ConsumptionRuleDefinition(
    name="consume_spoken_tone_variant_source_form_pairs",
    report_only_effect="remove all remaining matching pairs for the spoken-tone-variant source form",
    enrichment_effect="add the source Pinyin as an accepted reading on the selected dictionary form",
    handler=drop_source_form_pairs,
)
DROP_CASE_VARIANT_EXACT_DEFINITION_SOURCE_FORM_PAIRS_RULE = ConsumptionRuleDefinition(
    name="drop_case_variant_exact_definition_source_form_pairs",
    report_only_effect="remove all remaining matching pairs for the exact-definition case-variant source form",
    enrichment_effect="apply tags and metadata directly to the selected dictionary form without changing Pinyin",
    handler=drop_source_form_pairs,
)
DROP_EXACT_DEFINITION_ALSO_PR_SOURCE_FORM_PAIRS_RULE = ConsumptionRuleDefinition(
    name="drop_exact_definition_also_pr_source_form_pairs",
    report_only_effect="remove all remaining matching pairs for the exact-definition also-pr source form",
    enrichment_effect="apply tags and metadata directly and add explicitly attested also-pr readings",
    handler=drop_source_form_pairs,
)
DROP_EXACT_DEFINITION_SOURCE_FORM_PAIRS_RULE = ConsumptionRuleDefinition(
    name="drop_exact_definition_source_form_pairs",
    report_only_effect="remove all remaining matching pairs for the exact-definition source form",
    enrichment_effect="apply tags and metadata directly to the selected dictionary form without changing Pinyin",
    handler=drop_source_form_pairs,
)
DROP_SEMICOLON_SPLIT_EXACT_DEFINITION_ALSO_PR_SOURCE_FORM_PAIRS_RULE = ConsumptionRuleDefinition(
    name="drop_semicolon_split_exact_definition_also_pr_source_form_pairs",
    report_only_effect="remove all remaining matching pairs for the semicolon-split exact-definition also-pr form",
    enrichment_effect="apply tags and metadata directly and add explicitly attested also-pr readings",
    handler=drop_source_form_pairs,
)
DROP_HTML_SUBFORM_DEFINITION_COVER_SOURCE_FORM_PAIRS_RULE = ConsumptionRuleDefinition(
    name="drop_html_subform_definition_cover_source_form_pairs",
    report_only_effect="remove all remaining matching pairs for the HTML-subform-covered source form",
    enrichment_effect="apply tags and metadata directly to every dictionary form covered by xiehanzi HTML subforms",
    handler=drop_source_form_pairs,
)
DROP_SOURCE_SEE_COLLOQUIAL_PR_SOURCE_FORM_PAIRS_RULE = ConsumptionRuleDefinition(
    name="drop_source_see_colloquial_pr_source_form_pairs",
    report_only_effect="remove all remaining matching pairs for the reciprocal-reference source form",
    enrichment_effect="apply tags and metadata and add only the explicitly attested source reading",
    handler=drop_source_form_pairs,
)
ASSERT_DEFAULT_UNRESOLVED_EMPTY_RULE = ConsumptionRuleDefinition(
    name="assert_default_unresolved_empty",
    report_only_effect="assert the terminal default_unresolved bucket is empty",
    enrichment_effect="abort the build if any source form remains unresolved",
    handler=assert_default_unresolved_empty_pairs,
)


def deck_entries_for_source_form_ids(
    deck_entries: list[dict[str, Any]], source_form_ids: set[int]
) -> list[dict[str, Any]]:
    return [deck_entries[source_form_id] for source_form_id in sorted(source_form_ids)]


def deck_entry_for_pair(deck_entries: list[dict[str, Any]], item: HskMatchingPair) -> dict[str, Any]:
    return deck_entries[item.source_form_id]


def deck_entry_with_manual_pinyin_override(
    deck_entries: list[dict[str, Any]],
    item: HskMatchingPair,
) -> dict[str, Any]:
    override = item.context.get("manual_pinyin_override")
    if override is None:
        raise ValueError(f"Manual Pinyin override bucket item lacks override context: {item!r}")

    entry = dict(deck_entry_for_pair(deck_entries, item))
    entry["raw_pinyin"] = override["raw_pinyin"]
    entry["pinyin"] = override["override_pinyin"]
    entry["manual_pinyin_override"] = override
    return entry


def target_word_and_form_from_pair(
    state: LexiconState,
    item: HskMatchingPair,
) -> tuple[LexiconWord, LexiconForm, str, str]:
    return target_word_and_form_from_target(state, item.target_report())


def target_word_and_form_from_target(
    state: LexiconState,
    target: dict[str, Any],
) -> tuple[LexiconWord, LexiconForm, str, str]:
    word_key = str(target.get("word_key") or "")
    form_key = str(target.get("form_key") or "")
    word = state.words.get(word_key)
    if word is None:
        raise ValueError(f"Target word no longer exists in state: {target!r}")

    form = word.forms.get(form_key)
    if form is None:
        raise ValueError(f"Target form no longer exists in state: {target!r}")

    return word, form, word_key, form_key


def target_identity(target: dict[str, Any]) -> tuple[str, str]:
    return str(target.get("word_key") or ""), str(target.get("form_key") or "")


def apply_entry_metadata_to_selected_form(word: LexiconWord, form: LexiconForm, entry: dict[str, Any]) -> None:
    word.add_tags(entry["tags"])
    word.set_hanzi_frequency_once(entry["frequency"])
    form.add_tags(entry["tags"])


def unique_form_key(word: LexiconWord, desired_key: str, current_key: str) -> str:
    key = desired_key
    index = 1
    while key in word.forms and key != current_key:
        key = f"{desired_key}#{index}"
        index += 1
    return key


def rekey_form(
    word: LexiconWord,
    current_key: str,
    form: LexiconForm,
    new_pinyin: str,
) -> str:
    new_key = unique_form_key(word, new_pinyin, current_key)
    form.replace_pinyin(new_pinyin)
    if new_key == current_key:
        return current_key

    rebuilt_forms: dict[str, LexiconForm] = {}
    replaced = False
    for key, value in word.forms.items():
        if key == current_key:
            if value is not form:
                raise ValueError(f"Target form key points at a different form: {current_key!r}")
            rebuilt_forms[new_key] = form
            replaced = True
        else:
            rebuilt_forms[key] = value

    if not replaced:
        raise ValueError(f"Target form key disappeared before rekey: {current_key!r}")
    word.forms = rebuilt_forms
    return new_key


def add_synthetic_words_to_state(state: LexiconState, missing_entries: list[dict[str, Any]]) -> list[LexiconWord]:
    synthetic_words = build_synthetic_words(missing_entries)
    for word in synthetic_words:
        key = word.simplified
        if key in state.words:
            raise ValueError(f"Synthetic word collides with existing lexicon word: {key}")
        state.words[key] = word
    return synthetic_words


def validate_exact_pinyin_item(entry: dict[str, Any], form: LexiconForm, item: HskMatchingPair) -> None:
    if pinyin_rule_kind(entry["pinyin"], form.pinyin_reading_string) != "exact":
        raise ValueError(f"Perfect-match bucket selected a non-exact pair: {item!r}")


def validate_format_variant_item(entry: dict[str, Any], form: LexiconForm, item: HskMatchingPair) -> None:
    if pinyin_rule_kind(entry["pinyin"], form.pinyin_reading_string) != "format_variant":
        raise ValueError(f"Format-variant bucket selected a non-format-variant pair: {item!r}")


def validate_case_variant_exact_definition_item(
    entry: dict[str, Any],
    form: LexiconForm,
    item: HskMatchingPair,
) -> None:
    if pinyin_rule_kind(entry["pinyin"], form.pinyin_reading_string) != "case_variant":
        raise ValueError(f"Case-variant bucket selected a non-case-variant pair: {item!r}")
    if not definition_sets_exact(definitions_from_meaning_html(entry["meaning_html"]), list(form.definitions)):
        raise ValueError(f"Case-variant bucket selected a non-exact-definition pair: {item!r}")


def validate_exact_definition_item(entry: dict[str, Any], form: LexiconForm, item: HskMatchingPair) -> None:
    if not definition_sets_exact(definitions_from_meaning_html(entry["meaning_html"]), list(form.definitions)):
        raise ValueError(f"Exact-definition bucket selected a non-exact-definition pair: {item!r}")


def consume_metadata_only_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
    *,
    bucket: str,
    match_type: str,
    state_effect: str,
    validate_item: Callable[[dict[str, Any], LexiconForm, HskMatchingPair], None],
    include_form_stats: bool = True,
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"][bucket]["selected_items"]
    consumed_entries: list[dict[str, Any]] = []

    for item in sorted(selected_items, key=item_source_form_id):
        word, form, _, _ = target_word_and_form_from_pair(state, item)
        entry = deck_entry_for_pair(deck_entries, item)
        validate_item(entry, form, item)
        apply_entry_metadata_to_selected_form(word, form, entry)
        form_stats["matched"] += 1
        record_form_match(form_stats, match_type)
        consumed_entries.append(entry)

    result = {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "state_effect": state_effect,
    }
    if include_form_stats:
        result["form_stats"] = form_stats
    return result


def consume_perfect_match_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    return consume_metadata_only_bucket(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
        bucket="perfect_match",
        match_type="exact",
        state_effect="applied exact-pair tags and metadata directly to the selected dictionary forms",
        validate_item=validate_exact_pinyin_item,
        include_form_stats=False,
    )


def consume_manual_pinyin_override_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"]["manual_pinyin_override"]["selected_items"]
    consumed_entries: list[dict[str, Any]] = []

    for item in sorted(selected_items, key=item_source_form_id):
        word, form, _, form_key = target_word_and_form_from_pair(state, item)
        entry = deck_entry_with_manual_pinyin_override(deck_entries, item)
        old_pinyin = form.pinyin
        match_type = pinyin_rule_kind(entry["pinyin"], form.pinyin_reading_string)
        if match_type not in {"exact", "format_variant"}:
            raise ValueError(f"Manual Pinyin override no longer matches the selected target form: {item!r}")

        word.add_tags(entry["tags"])
        word.set_hanzi_frequency_once(entry["frequency"])
        form_stats["matched"] += 1
        record_form_match(form_stats, match_type)

        xiehanzi_pinyin = numbered_pinyin(entry["pinyin"])
        if match_type != "exact":
            match_record = non_exact_match_record(
                entry=entry,
                match_type=match_type,
                cc_cedict_pinyin=old_pinyin,
                cc_cedict_definitions=list(form.definitions),
                xiehanzi_pinyin=xiehanzi_pinyin,
            )
            form_stats["non_exact_matches"].append(match_record)
            if definitions_differ(match_record["cc_cedict_definitions"], match_record["xiehanzi_definitions"]):
                form_stats["non_exact_definition_mismatches"].append(match_record)

        form.add_tags(entry["tags"])

        new_pinyin = xiehanzi_pinyin
        cased_pinyin = apply_reference_pinyin_case(new_pinyin, str(old_pinyin))
        if cased_pinyin != new_pinyin:
            form_stats["pinyin_case_preserved"].append(
                {
                    "simplified": entry["simplified"],
                    "cc_cedict_pinyin": old_pinyin,
                    "xiehanzi_pinyin": new_pinyin,
                    "merged_pinyin": cased_pinyin,
                    "match_type": match_type,
                }
            )
            new_pinyin = cased_pinyin

        if old_pinyin and old_pinyin != new_pinyin:
            override_record = {
                "simplified": entry["simplified"],
                "cc_cedict_pinyin": old_pinyin,
                "xiehanzi_pinyin": new_pinyin,
                "match_type": match_type,
                "cc_cedict_definitions": form.definitions,
                "xiehanzi_definitions": definitions_from_meaning_html(entry["meaning_html"]),
            }
            if pinyin_formatting_key(str(old_pinyin)) == pinyin_formatting_key(new_pinyin):
                form_stats["pinyin_whitespace_only"].append(override_record)
            else:
                form_stats["pinyin_substantive"].append(override_record)

        new_form_key = rekey_form(word, form_key, form, new_pinyin)
        item.target_form_key = new_form_key
        consumed_entries.append(entry)

    return {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "form_stats": form_stats,
        "state_effect": "applied configured Pinyin overrides directly to the selected dictionary forms",
    }


def consume_format_variant_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    return consume_metadata_only_bucket(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
        bucket="format_variant_unique",
        match_type="format_variant",
        state_effect="applied format-variant tags and metadata directly without changing dictionary Pinyin",
        validate_item=validate_format_variant_item,
    )


def consume_spoken_tone_variant_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"]["spoken_tone_variant"]["selected_items"]
    consumed_entries: list[dict[str, Any]] = []
    added_readings: list[dict[str, Any]] = []

    for item in sorted(selected_items, key=item_source_form_id):
        spoken_tone_variant = item.context.get("spoken_tone_variant")
        if not spoken_tone_variant or not spoken_tone_variant.get("kinds"):
            raise ValueError(f"Spoken-tone-variant bucket lacks recognized variant context: {item!r}")

        word, form, _, _ = target_word_and_form_from_pair(state, item)
        entry = deck_entry_for_pair(deck_entries, item)
        dictionary_pinyin = form.pinyin_reading_string
        if pinyin_rule_kind(entry["pinyin"], dictionary_pinyin) != "toneless":
            raise ValueError(f"Spoken-tone-variant bucket selected a non-toneless pair: {item!r}")
        apply_entry_metadata_to_selected_form(word, form, entry)

        source_pinyin = source_pinyin_in_dictionary_format(entry["pinyin"], item.dictionary_pinyin)
        old_readings = list(form.pinyin_readings)
        added = form.add_pinyin_readings(source_pinyin)
        form_stats["matched"] += 1
        record_form_match(form_stats, "spoken_tone_variant")

        added_readings.append(
            {
                "entry": entry_summary(entry),
                "target": item.target_report(),
                "spoken_tone_variant_kinds": list(spoken_tone_variant["kinds"]),
                "dictionary_primary_pinyin": form.pinyin,
                "source_pinyin": source_pinyin,
                "old_pinyin_readings": old_readings,
                "added_pinyin_readings": added,
                "new_pinyin_readings": list(form.pinyin_readings),
            }
        )
        consumed_entries.append(entry)

    return {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "added_readings": added_readings,
        "form_stats": form_stats,
        "state_effect": "added source Pinyin as accepted readings on the selected dictionary forms",
    }


def consume_case_variant_exact_definition_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    return consume_metadata_only_bucket(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
        bucket="case_variant_exact_definition",
        match_type="case_variant",
        state_effect="applied case-variant tags and metadata directly without changing dictionary Pinyin",
        validate_item=validate_case_variant_exact_definition_item,
    )


def consume_exact_definition_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    return consume_metadata_only_bucket(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
        bucket="exact_definition",
        match_type="exact_definition",
        state_effect="applied exact-definition tags and metadata directly without changing dictionary Pinyin",
        validate_item=validate_exact_definition_item,
    )


def compact_lower_pinyin_key_from_record(record: dict[str, Any]) -> str:
    return str(record.get("compact_lower") or "")


def matching_also_pr_reading_values(item: HskMatchingPair, context_key: str) -> list[str]:
    context = item.context.get(context_key)
    if not context:
        raise ValueError(f"{context_key} bucket item lacks also-pr context: {item!r}")

    extra_keys = {compact_lower_pinyin_key_from_record(record) for record in context.get("extra_source_readings", [])}
    also_pr_by_key = {
        compact_lower_pinyin_key_from_record(record): str(record.get("strict") or "")
        for record in context.get("also_pr_readings", [])
    }

    readings: list[str] = []
    for key in sorted(extra_keys):
        reading = also_pr_by_key.get(key)
        if reading and reading not in readings:
            readings.append(reading)
    if not readings:
        raise ValueError(f"{context_key} bucket has no addable extra readings: {item!r}")
    return readings


def add_also_pr_readings_to_form(
    item: HskMatchingPair,
    form: LexiconForm,
    context_key: str,
) -> dict[str, Any]:
    old_readings = list(form.pinyin_readings)
    requested_readings = [
        pinyin_reading_in_reference_spacing(reading, item.dictionary_pinyin)
        for reading in matching_also_pr_reading_values(item, context_key)
    ]
    added = form.add_pinyin_readings(" / ".join(requested_readings))
    return {
        "target": item.target_report(),
        "dictionary_primary_pinyin": form.pinyin,
        "requested_pinyin_readings": requested_readings,
        "old_pinyin_readings": old_readings,
        "added_pinyin_readings": added,
        "new_pinyin_readings": list(form.pinyin_readings),
    }


def validate_exact_definition_also_pr_item(
    entry: dict[str, Any],
    form: LexiconForm,
    item: HskMatchingPair,
) -> None:
    if not definition_sets_exact(definitions_from_meaning_html(entry["meaning_html"]), list(form.definitions)):
        raise ValueError(f"Exact-definition also-pr bucket selected a non-exact-definition pair: {item!r}")


def validate_semicolon_split_exact_definition_also_pr_item(
    _entry: dict[str, Any],
    _form: LexiconForm,
    item: HskMatchingPair,
) -> None:
    context = item.context.get("semicolon_split_exact_definition_also_pr")
    if not context:
        raise ValueError(f"Semicolon-split exact-definition also-pr bucket lacks context: {item!r}")
    if set(context["source_expanded_definitions"]) != set(context["dictionary_expanded_definitions"]):
        raise ValueError(f"Semicolon-split exact-definition also-pr bucket has mismatched definitions: {item!r}")


def consume_also_pr_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
    *,
    bucket: str,
    context_key: str,
    match_type: str,
    state_effect: str,
    validate_item: Callable[[dict[str, Any], LexiconForm, HskMatchingPair], None],
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"][bucket]["selected_items"]
    consumed_entries: list[dict[str, Any]] = []
    added_readings: list[dict[str, Any]] = []

    for item in sorted(selected_items, key=item_source_form_id):
        word, form, _, _ = target_word_and_form_from_pair(state, item)
        entry = deck_entry_for_pair(deck_entries, item)
        validate_item(entry, form, item)
        apply_entry_metadata_to_selected_form(word, form, entry)
        reading_record = add_also_pr_readings_to_form(item, form, context_key)
        word.sort_forms_by_pinyin()
        form_stats["matched"] += 1
        record_form_match(form_stats, match_type)

        added_readings.append({"entry": entry_summary(entry), **reading_record})
        consumed_entries.append(entry)

    return {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "added_readings": added_readings,
        "form_stats": form_stats,
        "state_effect": state_effect,
    }


def consume_exact_definition_also_pr_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    return consume_also_pr_bucket(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
        bucket="exact_definition_also_pr",
        context_key="exact_definition_also_pr",
        match_type="exact_definition_also_pr",
        state_effect="applied exact-definition tags and metadata and added explicitly attested also-pr readings",
        validate_item=validate_exact_definition_also_pr_item,
    )


def consume_semicolon_split_exact_definition_also_pr_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    return consume_also_pr_bucket(
        state=state,
        deck_entries=deck_entries,
        pipeline=pipeline,
        form_stats=form_stats,
        bucket="semicolon_split_exact_definition_also_pr",
        context_key="semicolon_split_exact_definition_also_pr",
        match_type="semicolon_split_exact_definition_also_pr",
        state_effect=(
            "applied semicolon-split exact-definition tags and metadata and added explicitly attested also-pr readings"
        ),
        validate_item=validate_semicolon_split_exact_definition_also_pr_item,
    )


def consume_source_see_colloquial_pr_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"]["source_see_colloquial_pr"]["selected_items"]
    consumed_entries: list[dict[str, Any]] = []
    added_readings: list[dict[str, Any]] = []

    for item in sorted(selected_items, key=item_source_form_id):
        context = item.context.get("source_see_colloquial_pr")
        if not context or not context.get("attested_source_reading"):
            raise ValueError(f"Source-see colloquial-pr bucket lacks attested reading context: {item!r}")

        word, form, _, _ = target_word_and_form_from_pair(state, item)
        entry = deck_entry_for_pair(deck_entries, item)
        reading = context["attested_source_reading"]
        if (
            word.simplified != entry["simplified"]
            or form.pinyin != item.dictionary_primary_pinyin
            or tuple(form.pinyin_readings) != item.dictionary_pinyin_readings
            or tuple(form.definitions) != item.dictionary_definitions
            or context["dictionary_colloquial_definition"] not in form.definitions
            or pinyin_rule_kind(entry["pinyin"], reading) != "exact"
        ):
            raise ValueError(f"Source-see colloquial-pr target or attested source reading changed: {item!r}")

        old_readings = list(form.pinyin_readings)
        added = form.add_pinyin_readings(reading)
        apply_entry_metadata_to_selected_form(word, form, entry)
        word.sort_forms_by_pinyin()
        form_stats["matched"] += 1
        record_form_match(form_stats, "source_see_colloquial_pr")
        consumed_entries.append(entry)
        added_readings.append(
            {
                "entry": entry_summary(entry),
                "target": item.target_report(),
                **context,
                "dictionary_primary_pinyin": form.pinyin,
                "old_pinyin_readings": old_readings,
                "added_pinyin_readings": added,
                "new_pinyin_readings": list(form.pinyin_readings),
            }
        )

    return {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "added_readings": added_readings,
        "form_stats": form_stats,
        "state_effect": "applied tags and metadata and added only the reciprocally attested source reading",
    }


def consume_missing_dictionary_word_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
) -> dict[str, Any]:
    missing_source_form_ids = bucket_source_form_ids(
        pipeline["bucket_results"]["missing_dictionary_word"]["selected_items"]
    )
    missing_entries = deck_entries_for_source_form_ids(deck_entries, missing_source_form_ids)
    synthetic_words = add_synthetic_words_to_state(state, missing_entries)
    return {
        "entries": missing_entries,
        "entry_count": len(missing_entries),
        "synthetic_words": synthetic_words,
        "state_effect": "created synthetic words/forms from xiehanzi source entries",
    }


def consume_html_subform_definition_cover_bucket(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    selected_items = pipeline["bucket_results"]["html_subform_definition_cover"]["selected_items"]
    items_by_source_form: dict[int, list[HskMatchingPair]] = {}
    for item in selected_items:
        items_by_source_form.setdefault(item.source_form_id, []).append(item)

    consumed_entries: list[dict[str, Any]] = []
    matched_targets: list[dict[str, Any]] = []

    for source_form_id in sorted(items_by_source_form):
        source_items = items_by_source_form[source_form_id]
        context = source_items[0].context.get("html_subform_definition_cover")
        if not context:
            raise ValueError(f"HTML-subform bucket lacks context: {source_items[0]!r}")

        selected_targets = {target_identity(item.target_report()) for item in source_items}
        context_targets = {target_identity(match["target"]) for match in context.get("matches", [])}
        if selected_targets != context_targets:
            raise ValueError(f"HTML-subform bucket selected pairs do not match context coverage: {source_items!r}")

        entry = deck_entries[source_form_id]
        consumed_entries.append(entry)

        for match in sorted(context["matches"], key=lambda value: int(value["subentry_index"])):
            word, form, _, _ = target_word_and_form_from_target(state, match["target"])
            if list(form.definitions) != list(match["target_definitions"]):
                raise ValueError(f"HTML-subform target definitions changed before consumption: {match!r}")
            if set(match["subentry_expanded_definitions"]) != set(match["target_expanded_definitions"]):
                raise ValueError(f"HTML-subform bucket has mismatched expanded definitions: {match!r}")

            apply_entry_metadata_to_selected_form(word, form, entry)
            form_stats["matched"] += 1
            record_form_match(form_stats, "html_subform_definition_cover")
            matched_targets.append(
                {
                    "entry": entry_summary(entry),
                    "subentry_index": match["subentry_index"],
                    "subentry_pinyin": match["subentry_pinyin"],
                    "target": match["target"],
                    "target_pinyin": form.pinyin,
                    "target_definitions": list(form.definitions),
                }
            )

    return {
        "entries": [entry_summary(entry) for entry in consumed_entries],
        "entry_count": len(consumed_entries),
        "target_form_count": len(matched_targets),
        "matched_targets": matched_targets,
        "form_stats": form_stats,
        "state_effect": (
            "applied HTML-subform tags and metadata directly without changing dictionary Pinyin or definitions"
        ),
    }


def assert_default_unresolved_bucket_empty(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    form_stats: dict[str, Any],
) -> dict[str, Any]:
    _ = state
    _ = deck_entries
    selected_items = pipeline["bucket_results"]["default_unresolved"]["selected_items"]
    if selected_items:
        sample = [
            {
                "source_form_id": item.source_form_id,
                "source": item.source_form.source_report(),
                "target": item.target_report(),
            }
            for item in selected_items[:10]
        ]
        raise ValueError(
            "xiehanzi enrichment reached state consumption with unresolved default items; "
            f"count={len(selected_items)} sample={sample!r}"
        )

    return {
        "entries": [],
        "entry_count": 0,
        "form_stats": form_stats,
        "state_effect": "asserted default_unresolved is empty; no state changes",
    }


CONSUME_MISSING_DICTIONARY_WORD_BUCKET_RULE = StateConsumptionRuleDefinition(
    name="consume_missing_dictionary_word_bucket",
    bucket="missing_dictionary_word",
    state_effect="create synthetic words/forms from xiehanzi source entries",
    handler=consume_missing_dictionary_word_bucket,
)
CONSUME_PERFECT_MATCH_BUCKET_RULE = StateConsumptionRuleDefinition(
    name="consume_perfect_match_bucket",
    bucket="perfect_match",
    state_effect="apply exact-pair tags and metadata directly to selected dictionary forms",
    handler=consume_perfect_match_bucket,
)
CONSUME_MANUAL_PINYIN_OVERRIDE_BUCKET_RULE = StateConsumptionRuleDefinition(
    name="consume_manual_pinyin_override_bucket",
    bucket="manual_pinyin_override",
    state_effect="apply configured Pinyin overrides directly to selected dictionary forms",
    handler=consume_manual_pinyin_override_bucket,
)
CONSUME_FORMAT_VARIANT_BUCKET_RULE = StateConsumptionRuleDefinition(
    name="consume_format_variant_bucket",
    bucket="format_variant_unique",
    state_effect="apply format-variant tags and metadata directly without changing dictionary Pinyin",
    handler=consume_format_variant_bucket,
)
CONSUME_SPOKEN_TONE_VARIANT_BUCKET_RULE = StateConsumptionRuleDefinition(
    name="consume_spoken_tone_variant_bucket",
    bucket="spoken_tone_variant",
    state_effect="add source Pinyin as accepted readings on selected dictionary forms",
    handler=consume_spoken_tone_variant_bucket,
)
CONSUME_CASE_VARIANT_EXACT_DEFINITION_BUCKET_RULE = StateConsumptionRuleDefinition(
    name="consume_case_variant_exact_definition_bucket",
    bucket="case_variant_exact_definition",
    state_effect="apply case-variant tags and metadata directly without changing dictionary Pinyin",
    handler=consume_case_variant_exact_definition_bucket,
)
CONSUME_EXACT_DEFINITION_ALSO_PR_BUCKET_RULE = StateConsumptionRuleDefinition(
    name="consume_exact_definition_also_pr_bucket",
    bucket="exact_definition_also_pr",
    state_effect="apply exact-definition tags and metadata and add explicitly attested also-pr readings",
    handler=consume_exact_definition_also_pr_bucket,
)
CONSUME_EXACT_DEFINITION_BUCKET_RULE = StateConsumptionRuleDefinition(
    name="consume_exact_definition_bucket",
    bucket="exact_definition",
    state_effect="apply exact-definition tags and metadata directly without changing dictionary Pinyin",
    handler=consume_exact_definition_bucket,
)
CONSUME_SEMICOLON_SPLIT_EXACT_DEFINITION_ALSO_PR_BUCKET_RULE = StateConsumptionRuleDefinition(
    name="consume_semicolon_split_exact_definition_also_pr_bucket",
    bucket="semicolon_split_exact_definition_also_pr",
    state_effect="apply semicolon-split exact-definition tags and metadata and add explicitly attested readings",
    handler=consume_semicolon_split_exact_definition_also_pr_bucket,
)
CONSUME_HTML_SUBFORM_DEFINITION_COVER_BUCKET_RULE = StateConsumptionRuleDefinition(
    name="consume_html_subform_definition_cover_bucket",
    bucket="html_subform_definition_cover",
    state_effect="apply HTML-subform tags and metadata directly without changing dictionary Pinyin or definitions",
    handler=consume_html_subform_definition_cover_bucket,
)
CONSUME_SOURCE_SEE_COLLOQUIAL_PR_BUCKET_RULE = StateConsumptionRuleDefinition(
    name="consume_source_see_colloquial_pr_bucket",
    bucket="source_see_colloquial_pr",
    state_effect="apply tags and metadata and add only the reciprocally attested source reading; keep definitions",
    handler=consume_source_see_colloquial_pr_bucket,
)
ASSERT_DEFAULT_UNRESOLVED_BUCKET_EMPTY_RULE = StateConsumptionRuleDefinition(
    name="assert_default_unresolved_bucket_empty",
    bucket="default_unresolved",
    state_effect="assert default_unresolved is empty and make no state changes",
    handler=assert_default_unresolved_bucket_empty,
)


def apply_pipeline_enrichment_to_state(
    state: LexiconState,
    deck_entries: list[dict[str, Any]],
    pipeline: dict[str, Any],
    state_consumption_rules: tuple[StateConsumptionRuleDefinition, ...],
) -> dict[str, Any]:
    bucket_results: dict[str, dict[str, Any]] = {}
    form_stats = new_form_stats()

    for rule in state_consumption_rules:
        result = rule.apply_to_state(state, deck_entries, pipeline, form_stats)
        form_stats = result.get("form_stats", form_stats)
        result.setdefault("state_effect", rule.state_effect)
        result["state_consumption_rule"] = rule.name
        bucket_results[rule.bucket] = result

    missing_dictionary_word = bucket_results["missing_dictionary_word"]
    default_unresolved = bucket_results["default_unresolved"]

    output: dict[str, Any] = {
        bucket: result
        for bucket, result in bucket_results.items()
        if bucket not in {"missing_dictionary_word", "default_unresolved"}
    }

    return {
        "synthetic_words": missing_dictionary_word["synthetic_words"],
        "missing_dictionary_word": {
            key: value for key, value in missing_dictionary_word.items() if key != "synthetic_words"
        },
        "missing_deck_entries": missing_dictionary_word["entries"],
        **output,
        "default_unresolved": {
            key: value for key, value in default_unresolved.items() if key not in {"entries", "form_stats"}
        },
        "form_stats": form_stats,
    }
