"""Build deck note entries from enriched lexicon state data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anki_hanzi.audio.generation import AudioGenerator
from anki_hanzi.deck.config import DeckSelection
from anki_hanzi.deck.identity import stable_note_id
from anki_hanzi.lexicon import LexiconForm, LexiconState, LexiconWord
from anki_hanzi.pinyin import numbered_to_display
from anki_hanzi.rendering.meaning_html import render_meaning_form, render_meaning_html


@dataclass(frozen=True)
class EnrichedWordEntry:
    simplified: str
    pinyin: str
    meaning_html: str
    audio_filename_primary: str
    audio_filename_secondary: str
    tags: tuple[str, ...] = ()

    @property
    def audio_ref(self) -> str:
        if not self.audio_filename_primary and not self.audio_filename_secondary:
            return ""
        return f"[sound:{self.audio_filename_primary}][sound:{self.audio_filename_secondary}]"

    @property
    def audio_filenames(self) -> tuple[str, str]:
        return (self.audio_filename_primary, self.audio_filename_secondary)

    def fields(self, card_type: str, build_id: str) -> list[str]:
        note_id = stable_note_id(card_type, self.simplified, self.pinyin)
        return [
            self.simplified,
            self.pinyin,
            self.meaning_html,
            self.audio_ref,
            note_id,
            build_id,
        ]


@dataclass(frozen=True)
class _SelectedMeaningForm:
    display_pinyin: str
    form: LexiconForm
    tags: frozenset[str]


def _normalize_simplified(value: Any) -> str:
    return str(value or "").strip()


def _resolve_display_pinyin(form: LexiconForm) -> str:
    return " / ".join(_resolve_display_pinyin_readings(form))


def _resolve_display_pinyin_readings(form: LexiconForm) -> list[str]:
    readings: list[str] = []
    for reading in form.pinyin_readings or [form.pinyin]:
        display_pinyin = numbered_to_display(reading).strip()
        if display_pinyin:
            readings.append(display_pinyin)
    return readings


def _form_selection_tags(form: LexiconForm) -> set[str]:
    return set(form.tags)


def _is_form_selected(
    effective_tags: set[str],
    mode: str,
    selection_tags: set[str],
    is_individual: bool,
) -> bool:
    if is_individual:
        return True
    if mode == "all":
        return True
    if mode == "tagged":
        return bool(effective_tags & selection_tags)
    return False


def _note_tags(tags: set[str]) -> tuple[str, ...]:
    return tuple(sorted(tags))


def _assert_unique_form_display_pinyin(word: LexiconWord, forms: list[LexiconForm]) -> None:
    seen: dict[str, LexiconForm] = {}
    for form in forms:
        for display_pinyin in _resolve_display_pinyin_readings(form):
            existing = seen.get(display_pinyin)
            if existing is not None and existing is not form:
                raise ValueError(
                    f"Word {word.simplified!r} has multiple forms with overlapping display Pinyin "
                    f"{display_pinyin!r}: {existing.pinyin_readings!r} and {form.pinyin_readings!r}"
                )
            seen[display_pinyin] = form


def _selected_meaning_forms(
    word: LexiconWord,
    forms: list[LexiconForm],
    mode: str,
    selection_tags: set[str],
    is_individual: bool,
) -> list[_SelectedMeaningForm]:
    selected_forms: list[_SelectedMeaningForm] = []
    for form in forms:
        display_pinyin = _resolve_display_pinyin(form)
        if not display_pinyin.strip():
            continue

        effective_tags = _form_selection_tags(form)
        if _is_form_selected(effective_tags, mode, selection_tags, is_individual):
            selected_forms.append(
                _SelectedMeaningForm(
                    display_pinyin=display_pinyin,
                    form=form,
                    tags=frozenset(effective_tags),
                )
            )
    return selected_forms


def _word_tags(word: LexiconWord, forms: list[LexiconForm]) -> set[str]:
    tags = set(word.tags)
    for form in forms:
        tags.update(form.tags)
    return tags


def _selected_word_forms(
    word: LexiconWord,
    forms: list[LexiconForm],
    mode: str,
    selection_tags: set[str],
    is_individual: bool,
) -> list[LexiconForm]:
    if is_individual or mode == "all":
        return forms

    if mode != "tagged":
        return []

    word_tags = set(word.tags)
    for form in forms:
        if (word_tags | set(form.tags)) & selection_tags:
            return forms
    return []


def _display_pinyin_readings(forms: list[LexiconForm]) -> str:
    readings: list[str] = []
    seen: set[str] = set()
    for form in forms:
        for display_pinyin in _resolve_display_pinyin_readings(form):
            display_key = display_pinyin.strip()
            if not display_key or display_key in seen:
                continue
            seen.add(display_key)
            readings.append(display_pinyin)
    return " / ".join(readings)


def flatten_entries_by_card_type(entries_by_card_type: dict[str, list[EnrichedWordEntry]]) -> list[EnrichedWordEntry]:
    entries: list[EnrichedWordEntry] = []
    for card_type_entries in entries_by_card_type.values():
        entries.extend(card_type_entries)
    return entries


def unique_audio_entries(entries: list[EnrichedWordEntry]) -> list[EnrichedWordEntry]:
    deduped: list[EnrichedWordEntry] = []
    seen: set[str] = set()
    for entry in entries:
        word = entry.simplified.strip()
        if not word or word in seen:
            continue
        seen.add(word)
        deduped.append(entry)
    return deduped


def build_entries_from_state(
    state: LexiconState,
    selection: DeckSelection,
    audio_generator: AudioGenerator,
) -> tuple[dict[str, list[EnrichedWordEntry]], dict[str, Any]]:
    meaning_entries: list[EnrichedWordEntry] = []
    pinyin_entries: list[EnrichedWordEntry] = []
    write_entries: list[EnrichedWordEntry] = []
    matched_individual_simplified: set[str] = set()
    rendered_meaning_html_used = 0
    seen_meaning_entry_keys: set[tuple[str, str]] = set()
    seen_word_level_words: set[str] = set()
    selection_tags = set(selection.tags)

    for word in state.sorted_words():
        simplified = _normalize_simplified(word.simplified)

        is_individual = simplified in selection.individual_simplified
        mode = selection.mode

        rendered_definition_html = render_meaning_html(word)

        forms = word.forms_in_order()
        _assert_unique_form_display_pinyin(word, forms)

        selected_word_forms = _selected_word_forms(
            word=word,
            forms=forms,
            mode=mode,
            selection_tags=selection_tags,
            is_individual=is_individual,
        )
        display_readings = _display_pinyin_readings(selected_word_forms)
        if display_readings and simplified not in seen_word_level_words:
            seen_word_level_words.add(simplified)
            audio_filename_primary, audio_filename_secondary = audio_generator.filenames_for_text(simplified)
            word_level_entry = EnrichedWordEntry(
                simplified=simplified,
                pinyin=display_readings,
                meaning_html=rendered_definition_html,
                audio_filename_primary=audio_filename_primary,
                audio_filename_secondary=audio_filename_secondary,
                tags=_note_tags(_word_tags(word, forms)),
            )
            pinyin_entries.append(word_level_entry)
            write_entries.append(word_level_entry)

        word_entry_count = 0
        for meaning_form in _selected_meaning_forms(
            word=word,
            forms=forms,
            mode=mode,
            selection_tags=selection_tags,
            is_individual=is_individual,
        ):
            display_pinyin = meaning_form.display_pinyin
            entry_key = (simplified, display_pinyin)
            if entry_key in seen_meaning_entry_keys:
                continue
            seen_meaning_entry_keys.add(entry_key)

            if is_individual:
                matched_individual_simplified.add(simplified)

            audio_filename_primary, audio_filename_secondary = audio_generator.filenames_for_text(simplified)
            entry = EnrichedWordEntry(
                simplified=simplified,
                pinyin=display_pinyin,
                meaning_html=render_meaning_form(word, meaning_form.form),
                audio_filename_primary=audio_filename_primary,
                audio_filename_secondary=audio_filename_secondary,
                tags=_note_tags(set(meaning_form.tags)),
            )
            meaning_entries.append(entry)
            word_entry_count += 1

        if word_entry_count:
            rendered_meaning_html_used += 1

    entries_by_card_type = {
        "Meaning": sorted(meaning_entries, key=lambda entry: entry.simplified),
        "Pinyin": sorted(pinyin_entries, key=lambda entry: entry.simplified),
        "Write": sorted(write_entries, key=lambda entry: entry.simplified),
    }

    selection_report = {
        **selection.report(),
        "entries_by_card_type": {card_type: len(entries) for card_type, entries in entries_by_card_type.items()},
        "matched_individual_simplified": sorted(matched_individual_simplified),
        "unmatched_individual_simplified": sorted(selection.individual_simplified - matched_individual_simplified),
        "meaning_html": {
            "rendered_from_data": rendered_meaning_html_used,
        },
    }

    return entries_by_card_type, selection_report
