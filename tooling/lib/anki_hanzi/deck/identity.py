"""Stable deck, note, model, and tag identity helpers."""

from __future__ import annotations

import hashlib

import genanki


TAG_NAMESPACE = "hanzi"


def stable_id(label: str) -> int:
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    return (int.from_bytes(digest[:4], "big") % (1 << 30)) + (1 << 30)


def stable_hex_id(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def note_pinyin_id_key(card_type: str, pinyin: str) -> str:
    if card_type == "Meaning":
        return str(pinyin or "").strip()
    return ""


def stable_note_id(card_type: str, simplified: str, pinyin: str) -> str:
    return stable_hex_id(f"{card_type}\0{str(simplified or '').strip()}\0{note_pinyin_id_key(card_type, pinyin)}")


def stable_note_guid(note_id: str) -> str:
    return genanki.guid_for(str(note_id or "").strip())


def anki_tag_name(tag: str) -> str:
    tag = tag.strip()
    if not tag:
        return ""
    if tag.casefold().startswith(f"{TAG_NAMESPACE}::"):
        return TAG_NAMESPACE + tag[len(TAG_NAMESPACE) :]
    if ":" in tag:
        return f"{TAG_NAMESPACE}::" + "::".join(part for part in tag.split(":") if part)
    return f"{TAG_NAMESPACE}::{tag}"


def anki_tag_names(tags: tuple[str, ...]) -> list[str]:
    return sorted({formatted for tag in tags if (formatted := anki_tag_name(tag))})
