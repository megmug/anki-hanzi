"""Matching rules and pair helpers for xiehanzi-to-CC-CEDICT alignment."""

from __future__ import annotations

import re
from collections.abc import Callable
from collections import Counter
from dataclasses import dataclass
from typing import Any, cast

from anki_hanzi.lexicon import LexiconForm, LexiconState, LexiconWord
from anki_hanzi.pinyin import numbered_pinyin_token_pairs
from anki_hanzi.enrichment.hsk.rule_helpers import (
    definition_sets_exact,
    definitions_from_meaning_html,
    normalize_matching_definition,
    pinyin_rule_kind as classify_pinyin,
    pinyin_rule_readings as pinyin_readings,
    strip_html_text,
)
from anki_hanzi.enrichment.hsk.model import (
    HskMatchingPair,
    HskSourceForm,
    MatchingRuleResult,
    PairId,
    SourcePreludeRuleResult,
    bucket_source_form_ids,
    group_pairs_by_source_form,
    matching_pair_identity,
)


SourcePreludeMatchingHandler = Callable[
    [dict[int, HskSourceForm], dict[str, list["TargetFormRef"]], set[int], str, str],
    SourcePreludeRuleResult,
]
PairMatchingHandler = Callable[[list[HskMatchingPair], str, str], MatchingRuleResult]
MatchingRuleHandler = SourcePreludeMatchingHandler | PairMatchingHandler
PairContext = dict[str, Any]
PairContextPredicate = Callable[[HskMatchingPair], PairContext | None]
PairPredicate = Callable[[HskMatchingPair], bool]

ALSO_PR_RE = re.compile(r"also\s+pr\.\s*\[([^\]]+)\]", re.IGNORECASE)
PINYIN_BLOCK_RE = re.compile(
    r'<span\s+class="pinYinWrapper"[^>]*>(?P<pinyin>.*?)</span>\s*<ul>(?P<definitions>.*?)</ul>',
    re.IGNORECASE | re.DOTALL,
)
SEMICOLON_SPLIT_RE = re.compile(r"\s*;\s*")
MANUAL_PINYIN_OVERRIDES = {
    ("标致", "7-9"): {
        "pinyin": "biao1zhi5",
        "reason": "known xiehanzi TSV pinyin defect",
    },
    ("疼爱", "7-9"): {
        "pinyin": "teng2ai4",
        "reason": "known xiehanzi TSV pinyin defect",
    },
    ("脚踏实地", "7-9"): {
        "pinyin": "jiao3ta4shi2di4",
        "reason": "known xiehanzi TSV pinyin defect",
    },
    ("蹊跷", "7-9"): {
        "pinyin": "qi1qiao1",
        "reason": "known xiehanzi TSV pinyin defect",
    },
}


@dataclass(frozen=True)
class MatchingRuleDefinition:
    name: str
    scope: str
    requires: tuple[str, ...]
    handler: MatchingRuleHandler
    selected_pair: str | None = None

    def match_source_prelude(
        self,
        source_forms_by_id: dict[int, HskSourceForm],
        target_form_index: dict[str, list["TargetFormRef"]],
        remaining_source_form_ids: set[int],
        bucket: str,
    ) -> SourcePreludeRuleResult:
        if self.scope != "source_prelude":
            raise ValueError(f"matching rule {self.name!r} is not a source prelude rule")
        handler = cast(SourcePreludeMatchingHandler, self.handler)
        return handler(source_forms_by_id, target_form_index, remaining_source_form_ids, bucket, self.name)

    def match_pairs(self, working_pairs: list[HskMatchingPair], bucket: str) -> MatchingRuleResult:
        if self.scope not in {"pair_pipeline", "terminal"}:
            raise ValueError(f"matching rule {self.name!r} is not a pair-pipeline rule")
        handler = cast(PairMatchingHandler, self.handler)
        return handler(working_pairs, bucket, self.name)


@dataclass(frozen=True)
class TargetFormRef:
    word_key: str
    form_key: str
    word: LexiconWord
    form: LexiconForm


def simplified_matching_key(value: str) -> str:
    return str(value or "")


def build_target_form_index(state: LexiconState) -> dict[str, list[TargetFormRef]]:
    target_form_index: dict[str, list[TargetFormRef]] = {}
    for word_key in sorted(state.words):
        word = state.words[word_key]
        key = simplified_matching_key(word.simplified)
        if not key:
            continue
        target_form_index.setdefault(key, []).extend(
            TargetFormRef(word_key=word_key, form_key=form_key, word=word, form=form)
            for form_key, form in word.forms.items()
        )
    return target_form_index


def build_source_forms(deck_entries: list[dict[str, Any]]) -> dict[int, HskSourceForm]:
    return {
        source_form_id: HskSourceForm(source_form_id=source_form_id, entry=entry)
        for source_form_id, entry in enumerate(deck_entries)
    }


def candidate_count_bucket(count: int) -> str:
    if count >= 4:
        return "4+"
    return str(count)


def matching_pair_report(
    source_form: HskSourceForm,
    target: TargetFormRef,
    *,
    bucket: str,
    candidate_index: int,
    matching_rule: str,
) -> HskMatchingPair:
    form = target.form
    return HskMatchingPair(
        source_form=source_form,
        target_word_key=target.word_key,
        target_form_key=target.form_key,
        dictionary_simplified=target.word.simplified,
        dictionary_pinyin=form.pinyin_reading_string,
        dictionary_primary_pinyin=form.pinyin,
        dictionary_pinyin_readings=tuple(form.pinyin_readings),
        dictionary_tags=tuple(form.tags),
        dictionary_definitions=tuple(form.definitions),
        source_definitions=tuple(definitions_from_meaning_html(source_form.entry["meaning_html"])),
        candidate_index=candidate_index,
        bucket=bucket,
        matching_rule=matching_rule,
    )


def missing_dictionary_word_report(
    source_form: HskSourceForm,
    *,
    bucket: str,
    matching_rule: str,
) -> HskSourceForm:
    return source_form.assigned_to(bucket=bucket, matching_rule=matching_rule)


def matching_pair_for_bucket(
    item: HskMatchingPair,
    *,
    bucket: str,
    matching_rule: str,
) -> HskMatchingPair:
    return item.assigned_to(bucket=bucket, matching_rule=matching_rule)


def matching_result(
    selected_items: list[HskMatchingPair],
    remaining_items: list[HskMatchingPair],
) -> MatchingRuleResult:
    return {
        "selected_items": selected_items,
        "remaining_items": remaining_items,
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


def split_pairs_by_selected_ids(
    working_pairs: list[HskMatchingPair],
    selected_pair_ids: set[PairId],
    *,
    bucket: str,
    matching_rule: str,
    context_by_pair_id: dict[PairId, PairContext] | None = None,
    context_name: str | None = None,
) -> MatchingRuleResult:
    selected_items: list[HskMatchingPair] = []
    remaining_items: list[HskMatchingPair] = []

    for pair in working_pairs:
        pair_id = matching_pair_identity(pair)
        if pair_id in selected_pair_ids:
            selected_items.append(
                pair.assigned_to(
                    bucket=bucket,
                    matching_rule=matching_rule,
                    context_name=context_name,
                    context=context_by_pair_id[pair_id] if context_by_pair_id is not None else None,
                )
            )
        else:
            remaining_items.append(pair)

    return matching_result(selected_items, remaining_items)


def select_unique_pair_ids_by_source(
    working_pairs: list[HskMatchingPair],
    predicate: PairPredicate,
) -> set[PairId]:
    selected_pair_ids: set[PairId] = set()

    for source_pairs in group_pairs_by_source_form(working_pairs).values():
        matching_pairs = [pair for pair in source_pairs if predicate(pair)]
        if len(matching_pairs) != 1:
            continue
        selected_pair_ids.add(matching_pair_identity(matching_pairs[0]))

    return selected_pair_ids


def select_unique_pair_contexts_by_source(
    working_pairs: list[HskMatchingPair],
    context_for_pair: PairContextPredicate,
) -> dict[PairId, PairContext]:
    context_by_pair_id: dict[PairId, PairContext] = {}

    for source_pairs in group_pairs_by_source_form(working_pairs).values():
        matching_pairs: list[tuple[HskMatchingPair, PairContext]] = []
        for pair in source_pairs:
            context = context_for_pair(pair)
            if context is not None:
                matching_pairs.append((pair, context))

        if len(matching_pairs) != 1:
            continue

        pair, context = matching_pairs[0]
        pair_id = matching_pair_identity(pair)
        context_by_pair_id[pair_id] = context

    return context_by_pair_id


def manual_pinyin_override_for_source(source: dict[str, Any]) -> dict[str, str] | None:
    override = MANUAL_PINYIN_OVERRIDES.get((source["simplified"], source["deck_level"]))
    if override is None:
        return None
    return {
        "raw_pinyin": source["pinyin"],
        "override_pinyin": override["pinyin"],
        "reason": override["reason"],
    }


def spoken_tone_variant_kinds(source_pinyin: str, dictionary_pinyin: str) -> tuple[str, ...]:
    kinds: set[str] = set()
    source_readings = pinyin_readings(source_pinyin)
    dictionary_readings = pinyin_readings(dictionary_pinyin)
    if len(source_readings) != len(dictionary_readings):
        return ()

    for source_reading, dictionary_reading in zip(source_readings, dictionary_readings):
        source_tokens = numbered_pinyin_token_pairs(source_reading.strict)
        dictionary_tokens = numbered_pinyin_token_pairs(dictionary_reading.strict)
        if len(source_tokens) != len(dictionary_tokens):
            return ()

        for (source_base, source_tone), (dictionary_base, dictionary_tone) in zip(
            source_tokens,
            dictionary_tokens,
        ):
            if source_base != dictionary_base:
                return ()
            if source_tone == dictionary_tone:
                continue
            if source_base == "yi" and source_tone in {"2", "4"} and dictionary_tone == "1":
                kinds.add("yi_sandhi")
                continue
            if source_base == "bu" and source_tone == "2" and dictionary_tone == "4":
                kinds.add("bu_sandhi")
                continue
            if {source_tone, dictionary_tone} & {"5"} and source_tone != dictionary_tone:
                kinds.add("neutral_tone_diff")
                continue
            return ()

    return tuple(sorted(kinds))


def unique_pinyin_reading_records(value: str) -> list[dict[str, str]]:
    readings: list[dict[str, str]] = []
    seen: set[str] = set()
    for reading in pinyin_readings(value):
        if reading.compact_lower in seen:
            continue
        readings.append(
            {
                "strict": reading.strict,
                "compact_lower": reading.compact_lower,
            }
        )
        seen.add(reading.compact_lower)
    return readings


def also_pr_definition_readings(definitions: list[str]) -> list[dict[str, str]]:
    readings: list[dict[str, str]] = []
    seen: set[str] = set()
    for definition in definitions:
        for value in ALSO_PR_RE.findall(definition or ""):
            for reading in unique_pinyin_reading_records(value):
                key = reading["compact_lower"]
                if key in seen:
                    continue
                readings.append(reading)
                seen.add(key)
    return readings


def also_pr_pinyin_context(pair: HskMatchingPair) -> dict[str, Any] | None:
    source_readings = unique_pinyin_reading_records(pair.source_form.entry["pinyin"])
    dictionary_readings = unique_pinyin_reading_records(pair.dictionary_pinyin)
    also_pr_readings = also_pr_definition_readings(list(pair.dictionary_definitions))
    source_keys = {reading["compact_lower"] for reading in source_readings}
    dictionary_keys = {reading["compact_lower"] for reading in dictionary_readings}
    also_pr_keys = {reading["compact_lower"] for reading in also_pr_readings}
    extra_source_readings = [
        reading
        for reading in source_readings
        if reading["compact_lower"] in also_pr_keys and reading["compact_lower"] not in dictionary_keys
    ]

    if not source_keys or not extra_source_readings:
        return None
    if not source_keys <= dictionary_keys | also_pr_keys:
        return None

    return {
        "source_readings": source_readings,
        "dictionary_readings": dictionary_readings,
        "also_pr_readings": also_pr_readings,
        "extra_source_readings": extra_source_readings,
    }


def exact_definition_also_pr_context(pair: HskMatchingPair) -> dict[str, Any] | None:
    if not pair_definition_sets_exact(pair):
        return None
    return also_pr_pinyin_context(pair)


def split_semicolon_definitions(definitions: list[str]) -> list[str]:
    split_definitions: list[str] = []
    seen: set[str] = set()
    for definition in definitions:
        for part in SEMICOLON_SPLIT_RE.split(definition):
            value = part.strip()
            if not value or value in seen:
                continue
            split_definitions.append(value)
            seen.add(value)
    return split_definitions


def semicolon_split_definition_set(definitions: list[str]) -> set[str]:
    values = {normalize_matching_definition(definition) for definition in split_semicolon_definitions(definitions)}
    values.discard("")
    return values


def semicolon_split_definition_sets_exact(left: list[str], right: list[str]) -> bool:
    left_set = semicolon_split_definition_set(left)
    right_set = semicolon_split_definition_set(right)
    return bool(left_set) and left_set == right_set


def semicolon_split_exact_definition_also_pr_context(pair: HskMatchingPair) -> dict[str, Any] | None:
    source_definitions = list(pair.source_definitions)
    dictionary_definitions = list(pair.dictionary_definitions)
    if not semicolon_split_definition_sets_exact(source_definitions, dictionary_definitions):
        return None

    also_pr_context = also_pr_pinyin_context(pair)
    if also_pr_context is None:
        return None

    return {
        **also_pr_context,
        "source_expanded_definitions": split_semicolon_definitions(source_definitions),
        "dictionary_expanded_definitions": split_semicolon_definitions(dictionary_definitions),
    }


def source_html_subentries(meaning_html: str) -> list[dict[str, Any]]:
    subentries: list[dict[str, Any]] = []
    for index, match in enumerate(PINYIN_BLOCK_RE.finditer(meaning_html or ""), start=1):
        pinyin = strip_html_text(match.group("pinyin"))
        definitions = definitions_from_meaning_html(match.group("definitions"))
        if not pinyin or not definitions:
            continue
        subentries.append(
            {
                "index": index,
                "pinyin": pinyin,
                "definitions": definitions,
                "expanded_definitions": split_semicolon_definitions(definitions),
            }
        )
    return subentries


def html_subform_match_context(source_pairs: list[HskMatchingPair]) -> dict[str, Any] | None:
    if not source_pairs:
        return None

    source_meaning_html = str(source_pairs[0].source_form.entry.get("meaning_html") or "")
    subentries = source_html_subentries(source_meaning_html)
    if not subentries:
        return None

    matches: list[dict[str, Any]] = []
    matched_pair_ids: set[tuple[int, int]] = set()
    for subentry in subentries:
        matching_pairs: list[HskMatchingPair] = []
        for pair in source_pairs:
            if classify_pinyin(subentry["pinyin"], pair.dictionary_pinyin) != "exact":
                continue
            if not semicolon_split_definition_sets_exact(
                list(subentry["definitions"]),
                list(pair.dictionary_definitions),
            ):
                continue
            matching_pairs.append(pair)

        if len(matching_pairs) != 1:
            return None

        pair = matching_pairs[0]
        pair_id = matching_pair_identity(pair)
        if pair_id in matched_pair_ids:
            return None
        matched_pair_ids.add(pair_id)

        dictionary_definitions = list(pair.dictionary_definitions)
        row_pinyin_match = classify_pinyin(pair.source_form.entry["pinyin"], pair.dictionary_pinyin)
        matches.append(
            {
                "subentry_index": subentry["index"],
                "subentry_pinyin": subentry["pinyin"],
                "subentry_definitions": list(subentry["definitions"]),
                "subentry_expanded_definitions": list(subentry["expanded_definitions"]),
                "target": pair.target_report(),
                "target_pinyin": pair.dictionary_pinyin,
                "target_definitions": dictionary_definitions,
                "target_expanded_definitions": split_semicolon_definitions(dictionary_definitions),
                "row_pinyin_match": row_pinyin_match,
            }
        )

    source_pair_ids = {matching_pair_identity(pair) for pair in source_pairs}
    if matched_pair_ids != source_pair_ids:
        return None

    return {
        "source_subentry_count": len(subentries),
        "matched_target_count": len(matches),
        "row_pinyin": source_pairs[0].source_form.entry["pinyin"],
        "row_pinyin_matched_target_count": sum(
            1 for match in matches if match["row_pinyin_match"] in {"exact", "format_variant", "case_variant"}
        ),
        "matches": matches,
    }


def pair_pinyin_kind(pair: HskMatchingPair) -> str:
    return classify_pinyin(pair.source_form.entry["pinyin"], pair.dictionary_pinyin)


def pair_definition_sets_exact(pair: HskMatchingPair) -> bool:
    return definition_sets_exact(
        list(pair.source_definitions),
        list(pair.dictionary_definitions),
    )


def match_missing_dictionary_word_sources(
    source_forms_by_id: dict[int, HskSourceForm],
    target_form_index: dict[str, list[TargetFormRef]],
    remaining_source_form_ids: set[int],
    bucket: str,
    matching_rule: str,
) -> SourcePreludeRuleResult:
    selected_items = [
        missing_dictionary_word_report(source_forms_by_id[source_form_id], bucket=bucket, matching_rule=matching_rule)
        for source_form_id in sorted(remaining_source_form_ids)
        if source_forms_by_id[source_form_id].source_key not in target_form_index
    ]
    return {
        "selected_items": selected_items,
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


def materialize_simplified_match_pairs(
    source_forms_by_id: dict[int, HskSourceForm],
    target_form_index: dict[str, list[TargetFormRef]],
    source_form_ids: set[int],
) -> dict[str, Any]:
    working_pairs: list[HskMatchingPair] = []

    for source_form_id in sorted(source_form_ids):
        source_form = source_forms_by_id[source_form_id]
        target_refs = target_form_index.get(source_form.source_key, [])
        source_form.candidate_count = len(target_refs)

        for candidate_index, target in enumerate(target_refs, start=1):
            working_pairs.append(
                matching_pair_report(
                    source_form,
                    target,
                    bucket="simplified_match_working_set",
                    candidate_index=candidate_index,
                    matching_rule="simplified_match",
                )
            )

    target_form_count = sum(len(target_refs) for target_refs in target_form_index.values())
    virtual_pair_count = len(source_form_ids) * target_form_count
    return {
        "working_pairs": working_pairs,
        "source_form_count": len(source_form_ids),
        "target_form_count": target_form_count,
        "virtual_pair_count": virtual_pair_count,
        "simplified_match_pair_count": len(working_pairs),
        "simplified_mismatch_pair_count": virtual_pair_count - len(working_pairs),
    }


def match_manual_pinyin_override_pairs(
    working_pairs: list[HskMatchingPair],
    bucket: str,
    matching_rule: str,
) -> MatchingRuleResult:
    overrides_by_pair_id: dict[PairId, dict[str, str]] = {}

    for source_pairs in group_pairs_by_source_form(working_pairs).values():
        override = manual_pinyin_override_for_source(source_pairs[0].source_form.entry)
        if override is None:
            continue

        corrected_matching_pairs = [
            pair
            for pair in source_pairs
            if classify_pinyin(override["override_pinyin"], pair.dictionary_pinyin) in {"exact", "format_variant"}
        ]
        if len(corrected_matching_pairs) != 1:
            continue

        pair_id = matching_pair_identity(corrected_matching_pairs[0])
        overrides_by_pair_id[pair_id] = override

    return split_pairs_by_selected_ids(
        working_pairs,
        set(overrides_by_pair_id),
        bucket=bucket,
        matching_rule=matching_rule,
        context_by_pair_id=overrides_by_pair_id,
        context_name="manual_pinyin_override",
    )


def match_strict_pinyin_exact_unique_pairs(
    working_pairs: list[HskMatchingPair],
    bucket: str,
    matching_rule: str,
) -> MatchingRuleResult:
    return match_unique_pinyin_kind_pairs(
        working_pairs,
        bucket=bucket,
        matching_rule=matching_rule,
        pinyin_kind="exact",
    )


def match_format_variant_unique_pairs(
    working_pairs: list[HskMatchingPair],
    bucket: str,
    matching_rule: str,
) -> MatchingRuleResult:
    return match_unique_pinyin_kind_pairs(
        working_pairs,
        bucket=bucket,
        matching_rule=matching_rule,
        pinyin_kind="format_variant",
    )


def match_spoken_tone_variant_pairs(
    working_pairs: list[HskMatchingPair],
    bucket: str,
    matching_rule: str,
) -> MatchingRuleResult:
    def context_for_pair(pair: HskMatchingPair) -> PairContext | None:
        if pair_pinyin_kind(pair) != "toneless":
            return None
        kinds = spoken_tone_variant_kinds(pair.source_form.entry["pinyin"], pair.dictionary_pinyin)
        if not kinds:
            return None
        return {"kinds": list(kinds)}

    context_by_pair_id = select_unique_pair_contexts_by_source(working_pairs, context_for_pair)
    return split_pairs_by_selected_ids(
        working_pairs,
        set(context_by_pair_id),
        bucket=bucket,
        matching_rule=matching_rule,
        context_by_pair_id=context_by_pair_id,
        context_name="spoken_tone_variant",
    )


def match_case_variant_exact_definition_pairs(
    working_pairs: list[HskMatchingPair],
    bucket: str,
    matching_rule: str,
) -> MatchingRuleResult:
    selected_pair_ids = select_unique_pair_ids_by_source(
        working_pairs,
        lambda pair: pair_pinyin_kind(pair) == "case_variant" and pair_definition_sets_exact(pair),
    )
    return split_pairs_by_selected_ids(
        working_pairs,
        selected_pair_ids,
        bucket=bucket,
        matching_rule=matching_rule,
    )


def match_exact_definition_also_pr_pairs(
    working_pairs: list[HskMatchingPair],
    bucket: str,
    matching_rule: str,
) -> MatchingRuleResult:
    context_by_pair_id = select_unique_pair_contexts_by_source(working_pairs, exact_definition_also_pr_context)
    return split_pairs_by_selected_ids(
        working_pairs,
        set(context_by_pair_id),
        bucket=bucket,
        matching_rule=matching_rule,
        context_by_pair_id=context_by_pair_id,
        context_name="exact_definition_also_pr",
    )


def match_exact_definition_pairs(
    working_pairs: list[HskMatchingPair],
    bucket: str,
    matching_rule: str,
) -> MatchingRuleResult:
    selected_pair_ids = select_unique_pair_ids_by_source(working_pairs, pair_definition_sets_exact)
    return split_pairs_by_selected_ids(
        working_pairs,
        selected_pair_ids,
        bucket=bucket,
        matching_rule=matching_rule,
    )


def match_semicolon_split_exact_definition_also_pr_pairs(
    working_pairs: list[HskMatchingPair],
    bucket: str,
    matching_rule: str,
) -> MatchingRuleResult:
    context_by_pair_id = select_unique_pair_contexts_by_source(
        working_pairs,
        semicolon_split_exact_definition_also_pr_context,
    )
    return split_pairs_by_selected_ids(
        working_pairs,
        set(context_by_pair_id),
        bucket=bucket,
        matching_rule=matching_rule,
        context_by_pair_id=context_by_pair_id,
        context_name="semicolon_split_exact_definition_also_pr",
    )


def match_html_subform_definition_cover_pairs(
    working_pairs: list[HskMatchingPair],
    bucket: str,
    matching_rule: str,
) -> MatchingRuleResult:
    context_by_pair_id: dict[PairId, PairContext] = {}
    for source_pairs in group_pairs_by_source_form(working_pairs).values():
        context = html_subform_match_context(source_pairs)
        if context is None:
            continue

        for pair in source_pairs:
            pair_id = matching_pair_identity(pair)
            context_by_pair_id[pair_id] = context

    return split_pairs_by_selected_ids(
        working_pairs,
        set(context_by_pair_id),
        bucket=bucket,
        matching_rule=matching_rule,
        context_by_pair_id=context_by_pair_id,
        context_name="html_subform_definition_cover",
    )


def match_source_see_colloquial_pr_pairs(
    working_pairs: list[HskMatchingPair],
    bucket: str,
    matching_rule: str,
) -> MatchingRuleResult:
    def context_for_pair(pair: HskMatchingPair) -> PairContext | None:
        source = pair.source_form.entry
        if pair.source_form.candidate_count != 1 or source["simplified"] != pair.dictionary_simplified:
            return None
        if "/" in source["pinyin"] or "/" in pair.dictionary_pinyin:
            return None
        source_readings = pinyin_readings(source["pinyin"])
        target_readings = pinyin_readings(pair.dictionary_pinyin)
        if len(source_readings) != 1 or len(target_readings) != 1:
            return None
        if source_readings[0].strict == target_readings[0].strict:
            return None

        subentries = source_html_subentries(source["meaning_html"])
        if len(subentries) != 2 or len(list(PINYIN_BLOCK_RE.finditer(source["meaning_html"]))) != 2:
            return None
        if any("/" in subentry["pinyin"] for subentry in subentries):
            return None
        if set(pair.source_definitions) != {
            definition for subentry in subentries for definition in subentry["definitions"]
        }:
            return None
        source_blocks = [
            subentry for subentry in subentries if classify_pinyin(subentry["pinyin"], source["pinyin"]) == "exact"
        ]
        target_blocks = [
            subentry
            for subentry in subentries
            if classify_pinyin(subentry["pinyin"], pair.dictionary_pinyin) == "exact"
        ]
        if len(source_blocks) != 1 or len(target_blocks) != 1:
            return None
        reference = f"see {pair.dictionary_simplified}[{pair.dictionary_pinyin}]"
        if source_blocks[0]["definitions"] != [reference]:
            return None

        # Require a reciprocal, standalone pronunciation declaration, not a mention inside a gloss.
        attestations: list[tuple[str, str]] = []
        for definition in pair.dictionary_definitions:
            match = re.fullmatch(r"colloquial pr\. (\[[^\[\]]+\](?: or \[[^\[\]]+\])*)", definition)
            if match is None:
                continue
            for value in re.findall(r"\[([^\[\]]+)\]", match.group(1)):
                if value == source_readings[0].strict:
                    attestations.append((definition, value))
        if len(attestations) != 1:
            return None

        definition, reading = attestations[0]
        return {
            "source_reference": reference,
            "dictionary_colloquial_definition": definition,
            "attested_source_reading": reading,
        }

    context_by_pair_id = select_unique_pair_contexts_by_source(working_pairs, context_for_pair)
    return split_pairs_by_selected_ids(
        working_pairs,
        set(context_by_pair_id),
        bucket=bucket,
        matching_rule=matching_rule,
        context_by_pair_id=context_by_pair_id,
        context_name="source_see_colloquial_pr",
    )


def match_unique_pinyin_kind_pairs(
    working_pairs: list[HskMatchingPair],
    *,
    bucket: str,
    matching_rule: str,
    pinyin_kind: str,
) -> MatchingRuleResult:
    selected_pair_ids = select_unique_pair_ids_by_source(
        working_pairs,
        lambda pair: pair_pinyin_kind(pair) == pinyin_kind,
    )
    return split_pairs_by_selected_ids(
        working_pairs,
        selected_pair_ids,
        bucket=bucket,
        matching_rule=matching_rule,
    )


def match_default_unresolved_pairs(
    working_pairs: list[HskMatchingPair], bucket: str, matching_rule: str
) -> MatchingRuleResult:
    selected_items = [
        matching_pair_for_bucket(pair, bucket=bucket, matching_rule=matching_rule) for pair in working_pairs
    ]
    return {
        "selected_items": selected_items,
        "remaining_items": [],
        "selected_source_form_ids": bucket_source_form_ids(selected_items),
    }


MISSING_DICTIONARY_WORD_RULE = MatchingRuleDefinition(
    name="missing_dictionary_word",
    scope="source_prelude",
    requires=("No exact Simplified target word exists in CC-CEDICT",),
    handler=match_missing_dictionary_word_sources,
)
STRICT_PINYIN_EXACT_UNIQUE_RULE = MatchingRuleDefinition(
    name="strict_pinyin_exact_unique",
    scope="pair_pipeline",
    requires=(
        "The working set already contains only exact Simplified-compatible pairs",
        "Exactly one remaining pair for the source form has complete strict numbered preserve-case Pinyin-list equality",
    ),
    selected_pair="the unique complete strict numbered preserve-case Pinyin-list exact pair",
    handler=match_strict_pinyin_exact_unique_pairs,
)
MANUAL_PINYIN_OVERRIDE_UNIQUE_RULE = MatchingRuleDefinition(
    name="manual_pinyin_override_unique",
    scope="pair_pipeline",
    requires=(
        "The source form has a configured manual Pinyin correction",
        "Exactly one remaining pair matches the corrected Pinyin with complete strict numbered preserve-case "
        "or compact preserve-case Pinyin-list equality",
    ),
    selected_pair="the unique pair targeted by the configured corrected Pinyin value",
    handler=match_manual_pinyin_override_pairs,
)
FORMAT_VARIANT_UNIQUE_RULE = MatchingRuleDefinition(
    name="format_variant_unique",
    scope="pair_pipeline",
    requires=(
        "The working set already contains only exact Simplified-compatible pairs",
        "Exactly one remaining pair for the source form has complete compact preserve-case Pinyin-list equality",
        "The strict numbered preserve-case Pinyin reading lists differ only by spacing or separator formatting",
    ),
    selected_pair="the unique complete compact preserve-case Pinyin-list format-variant pair",
    handler=match_format_variant_unique_pairs,
)
SPOKEN_TONE_VARIANT_UNIQUE_RULE = MatchingRuleDefinition(
    name="spoken_tone_variant_unique",
    scope="pair_pipeline",
    requires=(
        "The working set already contains only exact Simplified-compatible pairs",
        "Exactly one remaining pair for the source form has toneless Pinyin equality",
        "The source and dictionary Pinyin have the same reading count, syllable count, and syllable bases",
        "Every tone difference is explained by recognized spoken variants: 一 sandhi, 不 sandhi, or neutral tone differences",
    ),
    selected_pair="the unique recognized spoken-tone-variant pair",
    handler=match_spoken_tone_variant_pairs,
)
CASE_VARIANT_EXACT_DEFINITION_UNIQUE_RULE = MatchingRuleDefinition(
    name="case_variant_exact_definition_unique",
    scope="pair_pipeline",
    requires=(
        "The working set already contains only exact Simplified-compatible pairs",
        "Exactly one remaining pair for the source form has complete compact lower-case Pinyin-list equality",
        "The strict numbered preserve-case Pinyin reading lists differ by case after spacing and separator normalization",
        "The complete non-empty normalized source and dictionary definition sets are identical",
    ),
    selected_pair="the unique exact-definition case-variant pair",
    handler=match_case_variant_exact_definition_pairs,
)
EXACT_DEFINITION_ALSO_PR_UNIQUE_RULE = MatchingRuleDefinition(
    name="exact_definition_also_pr_unique",
    scope="pair_pipeline",
    requires=(
        "The working set already contains only exact Simplified-compatible pairs",
        "No higher-priority pair-pipeline step consumed this source form",
        "Exactly one remaining pair for the source form has complete normalized definition-set equality",
        "Every source Pinyin reading is either already on the dictionary form or explicitly listed in the "
        "dictionary definitions as also pr.",
        "At least one source Pinyin reading is an extra also-pr reading not already on the dictionary form",
    ),
    selected_pair="the unique exact-definition pair whose source Pinyin is fully explained by also-pr readings",
    handler=match_exact_definition_also_pr_pairs,
)
EXACT_DEFINITION_UNIQUE_RULE = MatchingRuleDefinition(
    name="exact_definition_unique",
    scope="pair_pipeline",
    requires=(
        "The working set already contains only exact Simplified-compatible pairs",
        "No higher-priority pair-pipeline step consumed this source form",
        "Exactly one remaining pair for the source form has complete normalized definition-set equality",
    ),
    selected_pair="the unique exact-definition pair",
    handler=match_exact_definition_pairs,
)
SEMICOLON_SPLIT_EXACT_DEFINITION_ALSO_PR_UNIQUE_RULE = MatchingRuleDefinition(
    name="semicolon_split_exact_definition_also_pr_unique",
    scope="pair_pipeline",
    requires=(
        "The working set already contains only exact Simplified-compatible pairs",
        "No higher-priority pair-pipeline step consumed this source form",
        "Exactly one remaining pair for the source form has complete normalized definition-set equality after "
        "rule-local semicolon splitting",
        "Every source Pinyin reading is either already on the dictionary form or explicitly listed in the "
        "dictionary definitions as also pr.",
        "At least one source Pinyin reading is an extra also-pr reading not already on the dictionary form",
    ),
    selected_pair=(
        "the unique semicolon-split exact-definition pair whose source Pinyin is fully explained by also-pr readings"
    ),
    handler=match_semicolon_split_exact_definition_also_pr_pairs,
)
HTML_SUBFORM_DEFINITION_COVER_UNIQUE_RULE = MatchingRuleDefinition(
    name="html_subform_definition_cover_unique",
    scope="pair_pipeline",
    requires=(
        "No higher-priority pair-pipeline step consumed this source form",
        "The xiehanzi HTML contains one or more Pinyin/definition subentries",
        "Each HTML subentry has exactly one strict numbered preserve-case Pinyin dictionary candidate whose "
        "normalized definition set matches after rule-local semicolon splitting",
        "The matched subentries cover every remaining dictionary candidate for the source form exactly once",
    ),
    selected_pair="all pairs in the source form whose dictionary forms are covered by xiehanzi HTML subentries",
    handler=match_html_subform_definition_cover_pairs,
)
SOURCE_SEE_COLLOQUIAL_PR_UNIQUE_RULE = MatchingRuleDefinition(
    name="source_see_colloquial_pr_unique",
    scope="pair_pipeline",
    requires=(
        "No higher-priority pair-pipeline step consumed this source form",
        "The source has exactly one dictionary candidate with identical Simplified and a different single reading",
        "The source HTML contains exactly two Pinyin/definition blocks covering all source definitions: one for "
        "the source reading and one for the dictionary reading, matched with strict numbered preserve-case equality",
        "The source-reading block contains only the exact see Simplified[dictionary Pinyin] reference",
        "Exactly one bracketed numbered reading in standalone colloquial pr. [reading] (or [reading]) definitions "
        "equals the source reading converted to strict numbered preserve-case Pinyin",
    ),
    selected_pair="the sole dictionary candidate with a reciprocal source-reference/colloquial-reading link",
    handler=match_source_see_colloquial_pr_pairs,
)
DEFAULT_UNRESOLVED_RULE = MatchingRuleDefinition(
    name="default_unresolved",
    scope="terminal",
    requires=("No higher-priority pair-pipeline step consumed this source form",),
    handler=match_default_unresolved_pairs,
)


def candidate_count_buckets_for_source_forms(
    source_forms_by_id: dict[int, HskSourceForm],
    source_form_ids: set[int],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for source_form_id in source_form_ids:
        candidate_count = source_forms_by_id[source_form_id].candidate_count
        counts[candidate_count_bucket(candidate_count)] += 1
    return counts
