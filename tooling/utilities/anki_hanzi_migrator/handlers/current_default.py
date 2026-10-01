"""Current default stateful migration handler."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import tempfile
import time
import traceback
import zipfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    from aqt import mw
except Exception:  # pragma: no cover - Anki provides this at add-on runtime.
    mw = None

from .base import MigrationStepHandler, ReportItem, report_item

IMPORTED_ROOT = "汉字 (Hànzì)"

ALLOW_DESTRUCTIVE_MIGRATION = True
ALLOW_SKIPPED_TOUCHED_KINDS = set()
ALLOW_SKIPPED_TOUCHED_SIMPLIFIED = set()
HANZI_NOTETYPE_PREFIX = "汉字 (Hànzì)::"

FIELD_SEPARATOR = "\x1f"
KINDS = ["Meaning", "Pinyin", "Write"]
KIND_SUFFIXES = {
    "meaning": "Meaning",
    "pinyin": "Pinyin",
    "write": "Write",
}

CARD_COLUMNS = [
    "id",
    "nid",
    "did",
    "ord",
    "mod",
    "usn",
    "type",
    "queue",
    "due",
    "ivl",
    "factor",
    "reps",
    "lapses",
    "left",
    "odue",
    "odid",
    "flags",
    "data",
]

SCHEDULE_COPY_COLUMNS = [
    "type",
    "queue",
    "due",
    "ivl",
    "factor",
    "reps",
    "lapses",
    "left",
    "odue",
    "odid",
    "flags",
    "data",
]

REVLOG_COLUMNS = [
    "id",
    "cid",
    "usn",
    "ease",
    "ivl",
    "lastIvl",
    "factor",
    "time",
    "type",
]


def plain_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalized_match_text(value):
    return re.sub(r"\s+", "", plain_text(value)).lower()


def normalized_pinyin_reading_keys(value):
    keys = []
    for reading in re.split(r"\s*/\s*", plain_text(value)):
        key = normalized_match_text(reading)
        if key and key not in keys:
            keys.append(key)
    return keys


def split_fields(flds):
    return (flds or "").split(FIELD_SEPARATOR)


def row_dict(columns, row):
    return {column: row[idx] for idx, column in enumerate(columns)}


def ids2str_local(ids):
    ids = [int(id_) for id_ in ids]
    if not ids:
        return "()"
    return "(" + ",".join(str(id_) for id_ in ids) + ")"


def all_decks_from_mw():
    try:
        return [(int(item.id), item.name) for item in mw.col.decks.all_names_and_ids()]
    except Exception:
        return [(int(did), deck["name"]) for did, deck in mw.col.decks.decks.items()]


def deck_name_from_mw(did):
    deck = mw.col.decks.get(did)
    return deck.get("name", str(did)) if deck else str(did)


def deck_id_by_name(name):
    matches = [did for did, deck_name in all_decks_from_mw() if deck_name == name]
    if len(matches) != 1:
        raise Exception(f"Expected exactly one deck named {name!r}, found {len(matches)}")
    return matches[0]


def deck_ids_under(root):
    return [did for did, name in all_decks_from_mw() if name == root or name.startswith(root + "::")]


def cards_in_decks(dids):
    if not dids:
        return []
    return mw.col.db.list(f"select id from cards where did in {ids2str_local(dids)} order by id")


def table_columns(table_name):
    return {row[1] for row in mw.col.db.all(f"pragma table_info({table_name})")}


def get_mw_notetype(mid):
    notetype = mw.col.models.get(mid)
    if not notetype:
        raise Exception(f"Missing notetype {mid}")
    return notetype


def notetype_field_names(notetype):
    return [field.get("name", "") for field in notetype.get("flds", [])]


def template_name(notetype, ordinal):
    templates = notetype.get("tmpls", [])
    if 0 <= ordinal < len(templates):
        return templates[ordinal].get("name", "")
    return ""


def infer_kind(notetype_name, template_name_value, deck_name_value):
    haystacks = [notetype_name or "", template_name_value or "", deck_name_value or ""]
    for haystack in haystacks:
        lowered = haystack.lower()
        for suffix, kind in KIND_SUFFIXES.items():
            if re.search(r"(^|[^a-z])" + re.escape(suffix) + r"([^a-z]|$)", lowered):
                return kind
    return None


def infer_scope(tags_value, deck_name_value=""):
    """Extract HSK scope from note tags or deck name.

    Tags are now on notes, e.g. 'hsk:1' or 'hanzi::hsk::1'.
    For old notes without tags, falls back to deck name parsing.
    """
    # Try tags first (new structure)
    tags = (tags_value or "").strip()
    hsk_levels = re.findall(r"(?:^|\s)(?:Hanzi::)?hsk(?:::|:)(7-9|\d+)(?=\s|$)", tags, re.IGNORECASE)
    if hsk_levels:
        levels = sorted(hsk_levels, key=lambda x: int(x.replace("7-9", "79")))
        return "HSK " + levels[0]
    if re.search(r"(?:^|\s)(?:Hanzi::)?extra(?=\s|$)", tags, re.IGNORECASE):
        return "Extra"

    # Fallback to deck name (old structure)
    deck_name_value = deck_name_value or ""
    hsk_match = re.search(r"HSK\s+(7-9|\d+)", deck_name_value)
    if hsk_match:
        return "HSK " + hsk_match.group(1)
    parts = deck_name_value.split("::")
    for part in parts:
        if part == "Extra":
            return "Extra"
    return None


def fields_by_name(field_names, flds):
    values = split_fields(flds)
    return {name: values[idx] if idx < len(values) else "" for idx, name in enumerate(field_names)}


def card_touch_state_class(card, revlog_count):
    data = (card.get("data") or "").strip()
    has_reps_or_lapses = int(card.get("reps") or 0) > 0 or int(card.get("lapses") or 0) > 0
    has_revlog = int(revlog_count or 0) > 0
    has_card_data = data not in ("", "{}")
    is_new_suspended = int(card.get("type") or 0) == 0 and int(card.get("queue") or 0) == -1

    if is_new_suspended and not has_reps_or_lapses and not has_card_data and has_revlog:
        return "revlog_only_new_suspended"
    if has_reps_or_lapses or has_card_data:
        return "scheduler_state"
    if has_revlog:
        return "revlog_only"
    return "untouched"


def card_is_touched(card, revlog_count):
    return card_touch_state_class(card, revlog_count) not in {
        "untouched",
        "revlog_only_new_suspended",
    }


def touch_reasons(record):
    card = record.get("card", {})
    data = (card.get("data") or "").strip()
    reasons = []
    if int(card.get("reps") or 0) > 0:
        reasons.append("reps")
    if int(card.get("lapses") or 0) > 0:
        reasons.append("lapses")
    if int(record.get("revlog_count") or 0) > 0:
        reasons.append("revlog")
    if data not in ("", "{}"):
        reasons.append("card_data")
    return reasons


def touch_state_class(record):
    return card_touch_state_class(record.get("card", {}), record.get("revlog_count"))


def normalized_note_pinyin(value):
    return " ".join(str(value or "").split()).casefold()


def stable_note_id(kind, simplified, pinyin):
    simplified = plain_text(simplified)
    pinyin = normalized_note_pinyin(plain_text(pinyin))
    if not kind or not simplified or not pinyin:
        return None
    return hashlib.sha256(f"{kind}\0{simplified}\0{pinyin}".encode("utf-8")).hexdigest()


def build_key(fields, kind):
    note_id = (fields.get("NoteID", "") or "").strip()
    if note_id:
        return note_id
    return stable_note_id(kind, fields.get("Simplified", ""), fields.get("Pinyin", ""))


def build_loose_key(record):
    keys = build_loose_keys(record)
    return keys[0] if keys else None


def build_loose_keys(record):
    fields = record.get("fields", {})
    kind = record.get("kind")
    simplified = normalized_match_text(fields.get("Simplified", ""))
    if kind in ("Pinyin", "Write"):
        if not simplified:
            return []
        return [f"{kind}::{simplified}"]

    if not kind or not simplified:
        return []

    keys = [
        f"{kind}::{simplified}::{pinyin_key}" for pinyin_key in normalized_pinyin_reading_keys(fields.get("Pinyin", ""))
    ]
    full_pinyin_key = normalized_match_text(fields.get("Pinyin", ""))
    full_key = f"{kind}::{simplified}::{full_pinyin_key}" if full_pinyin_key else None
    if full_key and full_key not in keys:
        keys.append(full_key)
    return keys


def card_summary(record):
    fields = record.get("fields", {})
    card = record.get("card", {})
    return {
        "key": record.get("key"),
        "loose_key": record.get("loose_key") or build_loose_key(record),
        "loose_keys": build_loose_keys(record),
        "scope": record.get("scope"),
        "kind": record.get("kind"),
        "note_id_field": fields.get("NoteID", ""),
        "build_id_field": fields.get("BuildID", ""),
        "deck": record.get("deck_name"),
        "notetype": record.get("notetype_name"),
        "template": record.get("template_name"),
        "card_id": card.get("id"),
        "note_id": record.get("note_id"),
        "simplified": plain_text(fields.get("Simplified", "")),
        "pinyin": plain_text(fields.get("Pinyin", "")),
        "queue": card.get("queue"),
        "type": card.get("type"),
        "reps": card.get("reps"),
        "lapses": card.get("lapses"),
        "revlog_count": record.get("revlog_count"),
        "touch_reasons": touch_reasons(record),
        "touch_state_class": touch_state_class(record),
        "card_data": card.get("data"),
        "touched": record.get("touched"),
        "suspended": record.get("suspended"),
    }


def card_row(card_id):
    row = mw.col.db.first(
        "select id, nid, did, ord, mod, usn, type, queue, due, ivl, factor, reps, lapses, left, odue, odid, flags, data "
        "from cards where id = ?",
        card_id,
    )
    if not row:
        raise Exception(f"Card not found: {card_id}")
    return row_dict(CARD_COLUMNS, row)


def collect_current_records(root):
    dids = deck_ids_under(root)
    if not dids:
        raise Exception(f"No decks found under root={root!r}")

    cids = cards_in_decks(dids)
    records = []
    unknown_kind = []

    for cid in cids:
        card = card_row(cid)
        note_row = mw.col.db.first(
            "select id, guid, mid, flds, tags from notes where id = ?",
            card["nid"],
        )
        if not note_row:
            continue

        note_id, guid, mid, flds, tags = note_row
        notetype = get_mw_notetype(mid)
        field_names = notetype_field_names(notetype)
        tmpl_name = template_name(notetype, card["ord"])
        deck_name = deck_name_from_mw(card["did"])
        kind = infer_kind(notetype.get("name", ""), tmpl_name, deck_name)
        scope = infer_scope(tags, deck_name)
        fields = fields_by_name(field_names, flds)
        revlog_count = int(mw.col.db.scalar("select count(*) from revlog where cid = ?", card["id"]) or 0)
        record = {
            "key": build_key(fields, kind),
            "scope": scope,
            "kind": kind,
            "note_id": int(note_id),
            "note_guid": guid,
            "notetype_id": int(mid),
            "notetype_name": notetype.get("name", ""),
            "template_name": tmpl_name,
            "deck_id": int(card["did"]),
            "deck_name": deck_name,
            "fields": fields,
            "card": card,
            "revlog_count": revlog_count,
            "touched": card_is_touched(card, revlog_count),
            "suspended": int(card["queue"]) == -1,
            "tags": tags,
        }
        record["loose_key"] = build_loose_key(record)
        records.append(record)
        if not kind:
            unknown_kind.append(record)

    return {
        "root": root,
        "deck_ids": dids,
        "card_ids": cids,
        "records": records,
        "unknown_kind": unknown_kind,
        "unknown_scope": [],
    }


def source_notetypes_from_records(records):
    by_id = {}
    for record in records:
        by_id[int(record["notetype_id"])] = record["notetype_name"]
    return by_id


OLD_HANZI_NOTETYPE_PREFIX = "Basic - New HSK (2025) - "


def is_hanzi_notetype_name(name):
    if not name:
        return False
    return name.startswith(HANZI_NOTETYPE_PREFIX) or name.startswith(OLD_HANZI_NOTETYPE_PREFIX)


def remove_empty_source_notetypes(source_notetypes):
    removed = []
    skipped = []

    for mid, original_name in sorted(source_notetypes.items(), key=lambda item: item[1]):
        notetype = mw.col.models.get(mid)
        current_name = notetype.get("name", "") if notetype else original_name
        remaining_notes = int(mw.col.db.scalar("select count(*) from notes where mid = ?", mid) or 0)

        if not notetype:
            skipped.append(
                {
                    "notetype_id": mid,
                    "notetype_name": original_name,
                    "reason": "notetype already missing",
                    "remaining_notes": remaining_notes,
                }
            )
            continue

        if remaining_notes:
            skipped.append(
                {
                    "notetype_id": mid,
                    "notetype_name": current_name,
                    "reason": "notetype still has notes",
                    "remaining_notes": remaining_notes,
                }
            )
            continue

        if not is_hanzi_notetype_name(current_name):
            skipped.append(
                {
                    "notetype_id": mid,
                    "notetype_name": current_name,
                    "reason": "not an expected hanzi notetype name",
                    "remaining_notes": remaining_notes,
                }
            )
            continue

        mw.col.models.remove(mid)
        removed.append(
            {
                "notetype_id": mid,
                "notetype_name": current_name,
            }
        )

    return {"removed": removed, "skipped": skipped}


def index_by_key(records):
    by_key = {}
    duplicates = {}
    missing_key = []
    for record in records:
        key = record.get("key")
        if not key:
            missing_key.append(record)
            continue
        if key in by_key:
            duplicates.setdefault(key, [by_key[key]]).append(record)
        else:
            by_key[key] = record
    return by_key, duplicates, missing_key


def resolve_source_duplicate_keys(source_by_key, source_duplicates):
    resolved_by_key = dict(source_by_key)
    resolved = []
    unresolved = []

    for key, records in source_duplicates.items():
        touched = [record for record in records if record.get("touched")]

        if len(touched) > 1:
            unresolved.append(
                {
                    "key": key,
                    "reason": "multiple touched source cards map to one target card",
                    "cards": [card_summary(record) for record in records],
                }
            )
            continue

        if len(touched) == 1:
            chosen = touched[0]
        else:
            continue

        resolved_by_key[key] = chosen
        resolved.append(
            {
                "key": key,
                "reason": "single touched source card chosen",
                "chosen": card_summary(chosen),
                "ignored": [card_summary(record) for record in records if record is not chosen],
            }
        )

    return resolved_by_key, resolved, unresolved


def index_by_loose_key(records):
    by_key = {}
    for record in records:
        for key in build_loose_keys(record):
            by_key.setdefault(key, []).append(record)
    return by_key


def unique_records(records):
    by_key = {}
    for record in records:
        key = record.get("key")
        if key and key not in by_key:
            by_key[key] = record
    return list(by_key.values())


def build_match_plan(source_by_key, target_by_key):
    matches_by_source_key = {}
    matched_target_keys = set()
    exact_source_keys = sorted(set(source_by_key) & set(target_by_key))

    for source_key in exact_source_keys:
        matches_by_source_key[source_key] = {
            "source_key": source_key,
            "target_key": source_key,
            "match_type": "exact",
        }
        matched_target_keys.add(source_key)

    loose_target_index = index_by_loose_key(
        [record for key, record in target_by_key.items() if key not in matched_target_keys]
    )

    for source_key in sorted(set(source_by_key) - set(matches_by_source_key)):
        source_record = source_by_key[source_key]
        loose_keys = build_loose_keys(source_record)
        if not loose_keys:
            continue

        candidates = unique_records(
            [
                record
                for loose_key in loose_keys
                for record in loose_target_index.get(loose_key, [])
                if record.get("key") not in matched_target_keys
            ]
        )
        if len(candidates) != 1:
            continue

        target_key = candidates[0]["key"]
        matched_loose_keys = [
            loose_key for loose_key in loose_keys if candidates[0] in loose_target_index.get(loose_key, [])
        ]
        matches_by_source_key[source_key] = {
            "source_key": source_key,
            "target_key": target_key,
            "match_type": "loose",
            "loose_key": matched_loose_keys[0] if matched_loose_keys else loose_keys[0],
            "loose_keys": loose_keys,
            "matched_loose_keys": matched_loose_keys,
        }
        matched_target_keys.add(target_key)

    unmatched_source_keys = sorted(set(source_by_key) - set(matches_by_source_key))
    target_only_keys = sorted(set(target_by_key) - matched_target_keys)
    return {
        "matches_by_source_key": matches_by_source_key,
        "matched_source_keys": sorted(matches_by_source_key),
        "matched_target_keys": sorted(matched_target_keys),
        "exact_source_keys": [
            key
            for key in exact_source_keys
            if key in matches_by_source_key and matches_by_source_key[key]["match_type"] == "exact"
        ],
        "loose_source_keys": [key for key, match in matches_by_source_key.items() if match["match_type"] == "loose"],
        "unmatched_source_keys": unmatched_source_keys,
        "target_only_keys": target_only_keys,
    }


def match_plan_mismatches(expected_plan, actual_plan):
    expected = expected_plan["matches_by_source_key"]
    actual = actual_plan["matches_by_source_key"]
    mismatches = []
    for source_key in sorted(set(expected) | set(actual)):
        expected_target = expected.get(source_key, {}).get("target_key")
        actual_target = actual.get(source_key, {}).get("target_key")
        if expected_target != actual_target:
            mismatches.append(
                {"key": source_key, "expected_target": expected_target, "actual_target": actual_target}
            )
    return mismatches


def target_inventory_mismatches(expected_by_key, actual_by_key):
    return [
        {"key": key, "reason": "missing target" if key in expected_by_key else "unexpected target"}
        for key in sorted(set(expected_by_key) ^ set(actual_by_key))
    ]


def special_match_source_keys(match_plan):
    return [
        key
        for key, match in match_plan["matches_by_source_key"].items()
        if match.get("match_type") not in {"exact", "loose"}
    ]


def special_match_type_counts(match_plan):
    return dict(
        sorted(
            Counter(
                match.get("match_type", "unknown")
                for match in match_plan["matches_by_source_key"].values()
                if match.get("match_type") not in {"exact", "loose"}
            ).items()
        )
    )


@contextmanager
def extract_apkg_collection(apkg_path):
    if not os.path.exists(apkg_path):
        raise Exception(f"APKG_PATH does not exist: {apkg_path}")

    with tempfile.TemporaryDirectory(prefix="hanzi-state-apply-preview-") as tempdir:
        with zipfile.ZipFile(apkg_path) as archive:
            names = archive.namelist()
            db_name = None
            for candidate in ["collection.anki21", "collection.anki2"]:
                if candidate in names:
                    db_name = candidate
                    break
            if not db_name:
                raise Exception("APKG contains no collection.anki2/collection.anki21")
            db_path = os.path.join(tempdir, db_name)
            with archive.open(db_name) as source, open(db_path, "wb") as target:
                target.write(source.read())
        yield db_path, db_name


def load_legacy_apkg_metadata(conn):
    row = conn.execute("select models, decks from col").fetchone()
    if not row:
        raise Exception("APKG collection has no col row")
    models_json, decks_json = row
    models = {int(mid): model for mid, model in json.loads(models_json).items()}
    decks = {int(did): deck for did, deck in json.loads(decks_json).items()}
    return models, decks


def collect_target_records_from_apkg(apkg_path):
    with extract_apkg_collection(apkg_path) as (db_path, db_name):
        conn = sqlite3.connect(db_path)
        try:
            models, decks = load_legacy_apkg_metadata(conn)
            rows = conn.execute(
                "select cards.id, cards.nid, cards.did, cards.ord, cards.mod, cards.usn, "
                "cards.type, cards.queue, cards.due, cards.ivl, cards.factor, cards.reps, "
                "cards.lapses, cards.left, cards.odue, cards.odid, cards.flags, cards.data, "
                "notes.guid, notes.mid, notes.flds, notes.tags "
                "from cards join notes on cards.nid = notes.id order by cards.id"
            ).fetchall()

            records = []
            unknown_kind = []
            for row in rows:
                card = row_dict(CARD_COLUMNS, row[: len(CARD_COLUMNS)])
                guid, mid, flds, tags = row[len(CARD_COLUMNS) :]
                mid = int(mid)
                model = models.get(mid)
                if not model:
                    raise Exception(f"APKG missing model {mid}")
                field_names = [field.get("name", "") for field in model.get("flds", [])]
                templates = model.get("tmpls", [])
                tmpl_name = templates[card["ord"]].get("name", "") if 0 <= card["ord"] < len(templates) else ""
                deck = decks.get(int(card["did"]), {})
                deck_name = deck.get("name", str(card["did"]))
                kind = infer_kind(model.get("name", ""), tmpl_name, deck_name)
                scope = infer_scope(tags, deck_name)
                fields = fields_by_name(field_names, flds)
                revlog_count = int(
                    conn.execute("select count(*) from revlog where cid = ?", (card["id"],)).fetchone()[0] or 0
                )
                record = {
                    "key": build_key(fields, kind),
                    "scope": scope,
                    "kind": kind,
                    "note_id": int(card["nid"]),
                    "note_guid": guid,
                    "notetype_id": mid,
                    "notetype_name": model.get("name", ""),
                    "template_name": tmpl_name,
                    "deck_id": int(card["did"]),
                    "deck_name": deck_name,
                    "fields": fields,
                    "card": card,
                    "revlog_count": revlog_count,
                    "touched": card_is_touched(card, revlog_count),
                    "suspended": int(card["queue"]) == -1,
                    "tags": tags,
                }
                record["loose_key"] = build_loose_key(record)
                records.append(record)
                if not kind:
                    unknown_kind.append(record)

            return {
                "db_name": db_name,
                "records": records,
                "unknown_kind": unknown_kind,
                "unknown_scope": [],
            }
        finally:
            conn.close()


def revlog_rows_for_card(card_id):
    rows = mw.col.db.all(
        "select id, cid, usn, ease, ivl, lastIvl, factor, time, type from revlog where cid = ? order by id",
        card_id,
    )
    return [row_dict(REVLOG_COLUMNS, row) for row in rows]


def snapshot_source_state(source_records):
    snapshot = {}
    for record in source_records:
        source_card_id = record["card"]["id"]
        item = {
            "summary": card_summary(record),
            "key": record["key"],
            "touched": record["touched"],
            "suspended": record["suspended"],
            "card": dict(record["card"]),
            "revlog": revlog_rows_for_card(source_card_id) if record["touched"] else [],
        }
        snapshot[record["key"]] = item
    return snapshot


def preset_id_by_name(name):
    configs = mw.col.decks.all_config()
    matches = [conf for conf in configs if conf.get("name") == name]
    if len(matches) != 1:
        raise Exception(f"Expected exactly one deck preset named {name!r}, found {len(matches)}")
    return int(matches[0]["id"])


def get_import_options():
    try:
        options = mw.col._backend.get_import_anki_package_presets()
    except Exception:
        from anki.import_export_pb2 import ImportAnkiPackageOptions

        options = ImportAnkiPackageOptions()
    options.with_scheduling = False
    options.with_deck_configs = False
    return options


def import_apkg(apkg_path):
    from anki.import_export_pb2 import ImportAnkiPackageRequest
    from aqt.operations import on_op_finished

    options = get_import_options()
    request = ImportAnkiPackageRequest(package_path=apkg_path, options=options)

    mw.progress.start(label="Importing Xiehanzi APKG...", immediate=True)
    try:
        result = mw.col.import_anki_package(request)
    finally:
        mw.progress.finish()

    try:
        on_op_finished(mw, result, None)
    except Exception:
        pass

    import_log = getattr(result, "log", None)
    return {
        "with_scheduling": options.with_scheduling,
        "with_deck_configs": options.with_deck_configs,
        "merge_notetypes": options.merge_notetypes,
        "update_notes": options.update_notes,
        "update_notetypes": options.update_notetypes,
        "found_notes": getattr(import_log, "found_notes", "?") if import_log else "?",
        "new": len(import_log.new) if import_log else "?",
        "updated": len(import_log.updated) if import_log else "?",
        "duplicate": len(import_log.duplicate) if import_log else "?",
        "conflicting": len(import_log.conflicting) if import_log else "?",
    }


def set_deck_preset_for_tree(root, preset_id):
    changed = []
    for did in deck_ids_under(root):
        deck = mw.col.decks.get(did)
        if not deck:
            continue
        mw.col.decks.set_config_id_for_deck_dict(deck, preset_id)
        mw.col.decks.update(deck, preserve_usn=False)
        changed.append(did)
    return changed


def copy_full_card_state(source_card, target_card_id, copy_columns, now):
    parts = []
    values = []
    for column in copy_columns:
        parts.append(f"{column}=?")
        values.append(source_card.get(column))

    card_cols = table_columns("cards")
    if "mod" in card_cols:
        parts.append("mod=?")
        values.append(now)
    if "usn" in card_cols:
        parts.append("usn=-1")

    values.append(target_card_id)
    mw.col.db.execute(f"update cards set {', '.join(parts)} where id=?", *values)


def suspend_target_cards(target_card_ids, now):
    if not target_card_ids:
        return 0
    card_cols = table_columns("cards")
    parts = ["queue=-1"]
    values = []
    if "mod" in card_cols:
        parts.append("mod=?")
        values.append(now)
    if "usn" in card_cols:
        parts.append("usn=-1")
    mw.col.db.execute(
        f"update cards set {', '.join(parts)} where id in {ids2str_local(target_card_ids)}",
        *values,
    )
    return len(target_card_ids)


def insert_revlog_rows(source_rows, target_card_id):
    mw.col.db.execute("delete from revlog where cid = ?", target_card_id)
    for row in source_rows:
        # Revlog IDs are review timestamps. Preserve them, including when Anki
        # leaves the original history behind after removing the source deck.
        existing = mw.col.db.first(
            "select id, cid, usn, ease, ivl, lastIvl, factor, time, type from revlog where id = ?",
            row["id"],
        )
        if existing is not None:
            if row_dict(REVLOG_COLUMNS, existing) != row:
                raise Exception(f"Conflicting review history at timestamp {row['id']}; refusing to overwrite it")
            mw.col.db.execute("delete from revlog where id = ?", row["id"])
        mw.col.db.execute(
            "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row["id"],
            target_card_id,
            -1,
            row["ease"],
            row["ivl"],
            row["lastIvl"],
            row["factor"],
            row["time"],
            row["type"],
        )


def revlog_state_mismatch(source_rows, target_card_id):
    expected = [
        {**row, "cid": target_card_id, "usn": -1}
        for row in sorted(source_rows, key=lambda row: row["id"])
    ]
    actual = revlog_rows_for_card(target_card_id)
    if expected == actual:
        return None

    mismatch = {"expected": len(expected), "actual": len(actual)}
    for index in range(max(len(expected), len(actual))):
        expected_row = expected[index] if index < len(expected) else None
        actual_row = actual[index] if index < len(actual) else None
        if expected_row != actual_row:
            mismatch["first_differing_row"] = {"expected": expected_row, "actual": actual_row}
            break
    return mismatch


def count_where(table, column, ids, extra=""):
    if not ids:
        return 0
    row = mw.col.db.first(f"select count(*) from {table} where {column} in {ids2str_local(ids)} {extra}")
    return int(row[0] or 0)


def summarize_kind_counts(records):
    counts = {}
    for kind in KINDS:
        subset = [record for record in records if record.get("kind") == kind]
        counts[kind] = {
            "total": len(subset),
            "touched": sum(1 for record in subset if record.get("touched")),
            "suspended": sum(1 for record in subset if record.get("suspended")),
        }
    return counts


def summarize_build_id_counts(records):
    return dict(
        sorted(Counter((record.get("fields", {}).get("BuildID", "") or "<missing>") for record in records).items())
    )


def summarize_touch_state_classes(records):
    return dict(sorted(Counter(touch_state_class(record) for record in records).items()))


def summarize_touch_reason_sets(records):
    return dict(sorted(Counter("+".join(touch_reasons(record)) or "none" for record in records).items()))


def validate_preflight(
    source_info,
    target_preview_info,
    preset_id,
    *,
    apkg_path,
    old_root,
    imported_root,
    match_plan_builder=build_match_plan,
):
    source_records = source_info["records"]
    target_preview_records = target_preview_info["records"]
    source_by_key, source_duplicates, source_missing_key = index_by_key(source_records)
    source_by_key, resolved_source_duplicates, unresolved_source_duplicates = resolve_source_duplicate_keys(
        source_by_key, source_duplicates
    )
    touched_source_by_key = {key: record for key, record in source_by_key.items() if record.get("touched")}
    target_by_key, target_duplicates, target_missing_key = index_by_key(target_preview_records)

    match_plan = match_plan_builder(touched_source_by_key, target_by_key)
    unmatched_source = [touched_source_by_key[key] for key in match_plan["unmatched_source_keys"]]
    touched_unmatched = unmatched_source
    touched_missing_key = [record for record in source_missing_key if record.get("touched")]
    touched_unknown_kind = [record for record in source_info["unknown_kind"] if record.get("touched")]
    disallowed_touched_unmatched = [
        record
        for record in touched_unmatched
        if record.get("kind") not in ALLOW_SKIPPED_TOUCHED_KINDS
        and plain_text(record["fields"].get("Simplified", "")) not in ALLOW_SKIPPED_TOUCHED_SIMPLIFIED
    ]
    source_note_ids_by_notetype = {}
    source_card_counts_by_notetype = Counter()
    for record in source_records:
        mid = int(record["notetype_id"])
        source_note_ids_by_notetype.setdefault(mid, set()).add(int(record["note_id"]))
        source_card_counts_by_notetype[mid] += 1

    problems = []
    if not ALLOW_DESTRUCTIVE_MIGRATION:
        problems.append("ALLOW_DESTRUCTIVE_MIGRATION is False")
    if not os.path.exists(apkg_path):
        problems.append(f"APKG_PATH does not exist: {apkg_path}")
    if imported_root != old_root and deck_ids_under(imported_root):
        problems.append(f"Imported root already exists before migration: {imported_root}")
    outside_target_decks = sorted(
        {
            record.get("deck_name") or "<missing>"
            for record in target_preview_records
            if record.get("deck_name") != imported_root
            and not (record.get("deck_name") or "").startswith(imported_root + "::")
        }
    )
    if outside_target_decks:
        problems.append(
            f"Target APKG contains cards outside the expected root {imported_root!r}: "
            + ", ".join(outside_target_decks)
        )
    if touched_unknown_kind:
        problems.append(f"Touched source cards with unknown kind: {len(touched_unknown_kind)}")
    if target_preview_info["unknown_kind"]:
        problems.append(f"Target preview cards with unknown kind: {len(target_preview_info['unknown_kind'])}")
    if unresolved_source_duplicates:
        problems.append(f"Duplicate source keys with conflicting learned state: {len(unresolved_source_duplicates)}")
    if target_duplicates:
        problems.append(f"Duplicate target preview keys: {len(target_duplicates)}")
    if touched_missing_key:
        problems.append(f"Touched source cards without key: {len(touched_missing_key)}")
    if target_missing_key:
        problems.append(f"Target preview cards without key: {len(target_missing_key)}")
    target_missing_note_id_field = [
        record for record in target_preview_records if not (record.get("fields", {}).get("NoteID", "") or "").strip()
    ]
    if target_missing_note_id_field:
        problems.append(f"Target preview cards without NoteID field: {len(target_missing_note_id_field)}")
    for mid, source_note_ids in sorted(source_note_ids_by_notetype.items()):
        source_name = next(record["notetype_name"] for record in source_records if int(record["notetype_id"]) == mid)
        if not is_hanzi_notetype_name(source_name):
            problems.append(f"Source notetype {source_name!r} ({mid}) is not an expected hanzi notetype")
        total_notes_for_notetype = int(mw.col.db.scalar("select count(*) from notes where mid = ?", mid) or 0)
        if total_notes_for_notetype != len(source_note_ids):
            problems.append(
                f"Source notetype {source_name!r} ({mid}) is used outside {old_root!r}: "
                f"{total_notes_for_notetype} total notes vs {len(source_note_ids)} notes under root"
            )
        else:
            total_cards_for_notetype = int(
                mw.col.db.scalar(
                    "select count(*) from cards join notes on cards.nid = notes.id where notes.mid = ?", mid
                ) or 0
            )
            if total_cards_for_notetype != source_card_counts_by_notetype[mid]:
                problems.append(
                    f"Source notetype {source_name!r} ({mid}) has cards outside {old_root!r}: "
                    f"{total_cards_for_notetype} total cards vs {source_card_counts_by_notetype[mid]} cards under root"
                )
    if disallowed_touched_unmatched:
        problems.append(
            "Touched unmatched source cards are not explicitly allowed: "
            + ", ".join(
                sorted(
                    {
                        f"{plain_text(record['fields'].get('Simplified', ''))}/{record.get('kind')}"
                        for record in disallowed_touched_unmatched
                    }
                )
            )
        )

    return {
        "source_by_key": touched_source_by_key,
        "target_preview_by_key": target_by_key,
        "match_plan": match_plan,
        "unmatched_source": unmatched_source,
        "touched_unmatched": touched_unmatched,
        "disallowed_touched_unmatched": disallowed_touched_unmatched,
        "resolved_source_duplicates": resolved_source_duplicates,
        "unresolved_source_duplicates": unresolved_source_duplicates,
        "target_preset_id": preset_id,
        "problems": problems,
    }


def _build_report_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _build_id_text(counts: dict[str, int] | None) -> str:
    if not counts:
        return "unknown"
    return ", ".join(f"{build_id}: {count}" for build_id, count in sorted(counts.items()))


def _kind_count_text(kind_counts: dict[str, dict[str, int]] | None) -> str:
    if not kind_counts:
        return "no cards"
    parts = []
    for kind in ("Meaning", "Pinyin", "Write"):
        data = kind_counts.get(kind)
        if data:
            parts.append(f"{kind}: {data.get('total', 0)} total, {data.get('touched', 0)} touched")
    return "; ".join(parts) if parts else "no cards"


def _match_type_counts_text(counts: dict[str, int] | None) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{match_type}: {count}" for match_type, count in sorted(counts.items()))


def _card_label(card: dict[str, Any]) -> str:
    if "source" in card and "target" in card:
        match_type = card.get("match_type")
        loose_key = card.get("loose_key")
        suffix = f" via {loose_key}" if loose_key else f" ({match_type})" if match_type else ""
        return f"{_summary_label(card['source'])} -> {_summary_label(card['target'])}{suffix}"
    if "summary" in card:
        return _summary_label(card["summary"])
    if "chosen" in card:
        ignored = card.get("ignored", [])
        reason = card.get("reason")
        reason_text = f"{reason}: " if reason else ""
        return f"{reason_text}{_summary_label(card['chosen'])}; ignored {len(ignored)} duplicate cards"

    kind = card.get("kind", "?")
    simplified = card.get("simplified", "?")
    pinyin = card.get("pinyin", "?")
    state_class = card.get("touch_state_class")
    suffix = f" ({state_class})" if state_class else ""
    return f"{simplified} / {pinyin} / {kind}{suffix}"


def _summary_label(value: Any) -> str:
    if isinstance(value, dict):
        if any(key in value for key in ("source", "target", "summary", "chosen", "kind", "simplified", "pinyin")):
            return _card_label(value)
        if "key" in value:
            reason = value.get("reason")
            return f"{value['key']}: {reason}" if reason else str(value["key"])
    return str(value)


def _sample_lines(values: list[Any], limit: int = 12) -> list[str]:
    lines = [_summary_label(value) for value in values[:limit]]
    remaining = len(values) - len(lines)
    if remaining > 0:
        lines.append(f"... and {remaining} more")
    return lines


class CurrentDefaultMigration(MigrationStepHandler):
    key = "current_default"
    name = "Current default migration"
    description = "Stateful NoteID/loose-key migration used by the current add-on."

    def build_match_plan(self, source_by_key, target_by_key):
        return build_match_plan(source_by_key, target_by_key)

    def deck_preset_name(self, deck_root: str) -> str | None:
        deck_ids = deck_ids_under(deck_root)
        if not deck_ids:
            return None

        current_conf = mw.col.decks.get(deck_ids[0]).get("conf")
        for config in mw.col.decks.all_config():
            if config.get("id") == current_conf:
                return config.get("name")
        return None

    def _single_build_id(self, build_id_counts: dict[str, int]) -> tuple[str | None, list[str]]:
        problems = []
        build_ids = [build_id for build_id in build_id_counts if build_id and build_id != "<missing>"]
        if not build_ids:
            problems.append("No BuildID field was found on any Hanzi card.")
            return None, problems
        if len(build_ids) != 1 or "<missing>" in build_id_counts:
            problems.append(
                "Expected every Hanzi card to have the same BuildID. "
                f"Found {build_id_counts}; migration is blocked because the deck state is inconsistent."
            )
            return None, problems
        return build_ids[0], problems

    def _append_build_id_integrity_problems(
        self,
        preflight: dict[str, Any],
        *,
        source_records: list[dict[str, Any]],
        target_records: list[dict[str, Any]],
    ) -> None:
        source_counts = summarize_build_id_counts(source_records)
        target_counts = summarize_build_id_counts(target_records)
        _, source_problems = self._single_build_id(source_counts)
        _, target_problems = self._single_build_id(target_counts)
        preflight["problems"].extend(f"Source build check failed: {problem}" for problem in source_problems)
        preflight["problems"].extend(f"Target build check failed: {problem}" for problem in target_problems)

    def current_deck_build_info(self, deck_root: str) -> dict[str, Any]:
        source_info = collect_current_records(deck_root)
        records = source_info["records"]
        build_id_counts = summarize_build_id_counts(records)
        build_id, problems = self._single_build_id(build_id_counts)
        return {
            "build_id": build_id,
            "build_id_counts": build_id_counts,
            "cards": len(records),
            "kind_counts": summarize_kind_counts(records),
            "problems": problems,
        }

    def target_apkg_build_info(self, apkg_path: str) -> dict[str, Any]:
        target_info = collect_target_records_from_apkg(apkg_path)
        records = target_info["records"]
        build_id_counts = summarize_build_id_counts(records)
        build_id, problems = self._single_build_id(build_id_counts)
        return {
            "build_id": build_id,
            "build_id_counts": build_id_counts,
            "cards": len(records),
            "kind_counts": summarize_kind_counts(records),
            "problems": problems,
        }

    def available_deck_roots(self) -> list[dict[str, Any]]:
        roots = sorted({name.split("::")[0] for _, name in all_decks_from_mw()})
        candidates: list[dict[str, Any]] = []

        for root in roots:
            try:
                info = collect_current_records(root)
            except Exception:
                continue
            records = info["records"]
            hanzi_records = [record for record in records if is_hanzi_notetype_name(record.get("notetype_name", ""))]
            if not hanzi_records:
                continue
            candidates.append(
                {
                    "root": root,
                    "cards": len(hanzi_records),
                    "touched_cards": sum(1 for record in hanzi_records if record.get("touched")),
                    "build_id_counts": summarize_build_id_counts(hanzi_records),
                }
            )

        return candidates

    def _preflight_problem_report(self, preflight: dict[str, Any]) -> dict[str, Any]:
        touched_unmatched_records = preflight["touched_unmatched"]
        disallowed_touched_unmatched_records = preflight["disallowed_touched_unmatched"]
        return {
            "problems": preflight["problems"],
            "touched_unmatched_count": len(touched_unmatched_records),
            "touched_unmatched_state_classes": summarize_touch_state_classes(touched_unmatched_records),
            "touched_unmatched_touch_reasons": summarize_touch_reason_sets(touched_unmatched_records),
            "touched_unmatched": [card_summary(record) for record in touched_unmatched_records],
            "disallowed_touched_unmatched_count": len(disallowed_touched_unmatched_records),
            "disallowed_touched_unmatched_state_classes": summarize_touch_state_classes(
                disallowed_touched_unmatched_records
            ),
            "disallowed_touched_unmatched_touch_reasons": summarize_touch_reason_sets(
                disallowed_touched_unmatched_records
            ),
            "disallowed_touched_unmatched": [card_summary(record) for record in disallowed_touched_unmatched_records],
            "resolved_source_duplicate_keys": len(preflight["resolved_source_duplicates"]),
            "unresolved_source_duplicate_keys": len(preflight["unresolved_source_duplicates"]),
            "resolved_source_duplicate_samples": preflight["resolved_source_duplicates"][:20],
            "unresolved_source_duplicate_samples": preflight["unresolved_source_duplicates"][:10],
        }

    def prepare_preflight(self, *, apkg_path: str, deck_root: str, target_preset_name: str) -> dict[str, Any]:
        old_root = deck_root
        final_root = deck_root
        target_preset_id = preset_id_by_name(target_preset_name)

        source_info = collect_current_records(deck_root)
        target_preview_info = collect_target_records_from_apkg(apkg_path)
        preflight = validate_preflight(
            source_info,
            target_preview_info,
            target_preset_id,
            apkg_path=apkg_path,
            old_root=old_root,
            imported_root=IMPORTED_ROOT,
            match_plan_builder=self.build_match_plan,
        )
        source_records = source_info["records"]
        self._append_build_id_integrity_problems(
            preflight,
            source_records=source_records,
            target_records=target_preview_info["records"],
        )
        learned_source_records = list(preflight["source_by_key"].values())
        touched_unmatched = preflight["touched_unmatched"]
        match_plan = preflight["match_plan"]
        special_source_keys = special_match_source_keys(match_plan)
        problem_report = self._preflight_problem_report(preflight) if preflight["problems"] else {}

        report_data = {
            "schema": "hanzi-stateful-migration-preflight-v1",
            "can_apply": not preflight["problems"],
            "config": {
                "apkg_path": apkg_path,
                "old_root": old_root,
                "imported_root": IMPORTED_ROOT,
                "final_root": final_root,
                "target_preset_name": target_preset_name,
                "target_preset_id": target_preset_id,
            },
            "source": {
                "cards": len(source_records),
                "learned_keyed_cards": len(learned_source_records),
                "kind_counts": summarize_kind_counts(source_records),
                "build_id_counts": summarize_build_id_counts(source_records),
                "touched_cards": len(learned_source_records),
                "revlog_rows_total_for_touched": sum(record["revlog_count"] for record in learned_source_records),
            },
            "target_preview": {
                "cards": len(target_preview_info["records"]),
                "kind_counts": summarize_kind_counts(target_preview_info["records"]),
                "build_id_counts": summarize_build_id_counts(target_preview_info["records"]),
            },
            "match": {
                "matched_learned_cards": len(match_plan["matched_source_keys"]),
                "exact_matched_learned_cards": len(match_plan["exact_source_keys"]),
                "special_matched_learned_cards": len(special_source_keys),
                "special_match_type_counts": special_match_type_counts(match_plan),
                "loose_matched_learned_cards": len(match_plan["loose_source_keys"]),
                "touched_unmatched_cards": len(touched_unmatched),
                "resolved_source_duplicate_keys": len(preflight["resolved_source_duplicates"]),
                "unresolved_source_duplicate_keys": len(preflight["unresolved_source_duplicates"]),
                "target_only_cards": len(match_plan["target_only_keys"]),
            },
            "problems": preflight["problems"],
            "problem_details": problem_report,
        }

        lines = [
            "HANZI STATEFUL MIGRATION PREFLIGHT",
            f"source root: {deck_root}",
            f"source build IDs: {report_data['source']['build_id_counts']}",
            f"target build IDs: {report_data['target_preview']['build_id_counts']}",
            f"learned/touched source cards: {len(learned_source_records)}",
            f"matched learned cards: {len(match_plan['matched_source_keys'])}",
            f"exact matches: {len(match_plan['exact_source_keys'])}",
            f"special matches: {len(special_source_keys)}",
            f"loose matches: {len(match_plan['loose_source_keys'])}",
            f"touched unmatched cards: {len(touched_unmatched)}",
        ]
        if preflight["problems"]:
            lines.append("status: blocked")
            lines.append("problems:")
            lines.extend(f"  {problem}" for problem in preflight["problems"])
        else:
            lines.append("status: ready to apply after full collection backup")

        return {
            "can_apply": not preflight["problems"],
            "text": "\n".join(lines) + "\n\n" + _build_report_json(report_data),
            "json": report_data,
        }

    def apply(self, *, apkg_path: str, deck_root: str, target_preset_name: str) -> dict[str, Any]:
        old_root = deck_root
        final_root = deck_root
        imported_root = IMPORTED_ROOT
        report_data = None
        state_savepoint_started = False

        try:
            collection_mod_before = getattr(mw.col, "mod", None)
            old_root_did = deck_id_by_name(old_root)
            target_preset_id = preset_id_by_name(target_preset_name)

            source_info = collect_current_records(old_root)
            target_preview_info = collect_target_records_from_apkg(apkg_path)
            preflight = validate_preflight(
                source_info,
                target_preview_info,
                target_preset_id,
                apkg_path=apkg_path,
                old_root=old_root,
                imported_root=IMPORTED_ROOT,
                match_plan_builder=self.build_match_plan,
            )

            source_records = source_info["records"]
            self._append_build_id_integrity_problems(
                preflight,
                source_records=source_records,
                target_records=target_preview_info["records"],
            )
            learned_source_records = list(preflight["source_by_key"].values())
            source_notetypes = source_notetypes_from_records(source_records)
            source_by_key = preflight["source_by_key"]
            touched_source = learned_source_records
            touched_unmatched = preflight["touched_unmatched"]
            source_snapshot = snapshot_source_state(touched_source)

            if preflight["problems"]:
                raise Exception("Preflight failed:\n" + _build_report_json(self._preflight_problem_report(preflight)))

            mw.progress.start(label="Deleting old Xiehanzi root deck...", immediate=True)
            try:
                mw.col.decks.remove([old_root_did])
            finally:
                mw.progress.finish()

            notetype_cleanup = remove_empty_source_notetypes(source_notetypes)
            if notetype_cleanup["skipped"]:
                raise Exception(
                    "Old hanzi notetype cleanup was not clean:\n"
                    + json.dumps(notetype_cleanup, ensure_ascii=False, indent=2, sort_keys=True)
                )

            import_result = import_apkg(apkg_path)

            if not deck_ids_under(IMPORTED_ROOT):
                roots = sorted(
                    {name.split("::")[0] for _, name in all_decks_from_mw() if name.startswith(IMPORTED_ROOT)}
                )
                if len(roots) != 1:
                    raise Exception(f"Could not find imported root {IMPORTED_ROOT!r}; candidates: {roots}")
                imported_root = roots[0]
            else:
                imported_root = IMPORTED_ROOT

            target_info = collect_current_records(imported_root)
            target_records = target_info["records"]
            target_by_key, target_duplicates, target_missing_key = index_by_key(target_records)
            target_card_ids = [record["card"]["id"] for record in target_records]

            if target_duplicates:
                raise Exception(f"Duplicate target keys after import: {len(target_duplicates)}")
            if target_missing_key:
                raise Exception(f"Target cards without key after import: {len(target_missing_key)}")
            if target_info["unknown_kind"]:
                raise Exception(f"Unknown target kind after import: {len(target_info['unknown_kind'])}")

            imported_inventory_mismatches = target_inventory_mismatches(preflight["target_preview_by_key"], target_by_key)
            if imported_inventory_mismatches:
                raise Exception(
                    "Imported target inventory differs from preflight. Restore the collection backup:\n"
                    + _build_report_json(imported_inventory_mismatches)
                )

            # Keep the preflight's promised transfers as the verification baseline.
            match_plan = preflight["match_plan"]
            imported_match_plan = self.build_match_plan(source_by_key, target_by_key)
            import_match_mismatches = match_plan_mismatches(match_plan, imported_match_plan)
            if import_match_mismatches:
                raise Exception(
                    "Imported card matches differ from preflight. Restore the collection backup:\n"
                    + _build_report_json(import_match_mismatches)
                )
            matches_by_source_key = match_plan["matches_by_source_key"]
            matched_source_keys = match_plan["matched_source_keys"]
            touched_matched_source_keys = matched_source_keys
            touched_matched_target_keys = {
                matches_by_source_key[key]["target_key"] for key in touched_matched_source_keys
            }

            copy_columns = [col for col in SCHEDULE_COPY_COLUMNS if col in table_columns("cards")]
            now = int(time.time())

            mw.col.db.execute("savepoint hanzi_stateful_apply")
            state_savepoint_started = True
            try:
                full_state_copied = 0
                revlog_rows_inserted = 0
                default_suspended_set = 0

                if target_card_ids:
                    mw.col.db.execute(f"delete from revlog where cid in {ids2str_local(target_card_ids)}")
                    default_suspended_set = suspend_target_cards(target_card_ids, now)

                for source_key in touched_matched_source_keys:
                    source_item = source_snapshot[source_key]
                    target_key = matches_by_source_key[source_key]["target_key"]
                    target_card_id = target_by_key[target_key]["card"]["id"]

                    copy_full_card_state(source_item["card"], target_card_id, copy_columns, now)
                    insert_revlog_rows(source_item["revlog"], target_card_id)
                    full_state_copied += 1
                    revlog_rows_inserted += len(source_item["revlog"])

                preset_changed_decks = set_deck_preset_for_tree(imported_root, target_preset_id)

                imported_root_did = deck_id_by_name(imported_root)
                if imported_root != final_root:
                    mw.col.decks.rename(imported_root_did, final_root)

                mw.col.db.execute("delete from revlog where cid not in (select id from cards)")

                mw.col.db.execute("release savepoint hanzi_stateful_apply")
                state_savepoint_started = False
            except Exception:
                if state_savepoint_started:
                    mw.col.db.execute("rollback to savepoint hanzi_stateful_apply")
                    mw.col.db.execute("release savepoint hanzi_stateful_apply")
                    state_savepoint_started = False
                raise

            final_info = collect_current_records(final_root)
            final_records = final_info["records"]
            final_by_key, final_duplicates, final_missing_key = index_by_key(final_records)
            final_card_ids = [record["card"]["id"] for record in final_records]
            final_hanzi_notetype_names = sorted(
                {record["notetype_name"] for record in final_records if is_hanzi_notetype_name(record["notetype_name"])}
            )
            final_plus_notetype_names = [name for name in final_hanzi_notetype_names if name.endswith("+")]

            schedule_mismatches = []
            revlog_mismatches = []
            default_suspended_mismatches = []

            final_match_plan = self.build_match_plan(source_by_key, final_by_key)
            final_matches_by_source_key = final_match_plan["matches_by_source_key"]
            final_match_mismatches = match_plan_mismatches(match_plan, final_match_plan)
            final_inventory_mismatches = target_inventory_mismatches(preflight["target_preview_by_key"], final_by_key)

            for source_key in touched_matched_source_keys:
                source_item = source_snapshot[source_key]
                expected_target_key = matches_by_source_key[source_key]["target_key"]
                target_record = final_by_key.get(expected_target_key)
                if not target_record:
                    schedule_mismatches.append({"key": source_key, "reason": "missing final target"})
                    continue
                target_card = card_row(target_record["card"]["id"])
                for column in copy_columns:
                    if target_card.get(column) != source_item["card"].get(column):
                        schedule_mismatches.append(
                            {
                                "key": source_key,
                                "column": column,
                                "source": source_item["card"].get(column),
                                "target": target_card.get(column),
                            }
                        )
                        break
                revlog_mismatch = revlog_state_mismatch(source_item["revlog"], target_record["card"]["id"])
                if revlog_mismatch is not None:
                    revlog_mismatches.append({"key": source_key, **revlog_mismatch})

            for target_key, target_record in final_by_key.items():
                if target_key in touched_matched_target_keys:
                    continue
                target_card = card_row(target_record["card"]["id"])
                if int(target_card["queue"]) != -1:
                    default_suspended_mismatches.append(
                        {
                            "key": target_key,
                            "queue": target_card["queue"],
                            "summary": card_summary(target_record),
                        }
                    )

            preset_counts = Counter(mw.col.decks.get(did)["conf"] for did in deck_ids_under(final_root))
            queue_counts = Counter(
                int(row[0])
                for row in mw.col.db.all(f"select queue from cards where id in {ids2str_local(final_card_ids)}")
            )

            skipped_touched_revlog_rows = sum(record["revlog_count"] for record in touched_unmatched)
            final_revlog_on_final_cards = count_where("revlog", "cid", final_card_ids)
            orphaned_revlog_rows = int(
                mw.col.db.scalar("select count(*) from revlog where cid not in (select id from cards)") or 0
            )
            default_only_target_keys = final_match_plan["target_only_keys"]
            skipped_touched_kind_counts = Counter(record.get("kind") for record in touched_unmatched)
            loose_match_samples = []
            for source_key in sorted(final_match_plan["loose_source_keys"]):
                final_match = final_matches_by_source_key[source_key]
                loose_match_samples.append(
                    {
                        "source": card_summary(source_by_key[source_key]),
                        "target": card_summary(final_by_key[final_match["target_key"]]),
                    }
                )
            special_match_samples = []
            final_special_source_keys = sorted(special_match_source_keys(final_match_plan))
            for source_key in final_special_source_keys:
                final_match = final_matches_by_source_key[source_key]
                special_match_samples.append(
                    {
                        "match_type": final_match.get("match_type"),
                        "source": card_summary(source_by_key[source_key]),
                        "target": card_summary(final_by_key[final_match["target_key"]]),
                        "details": {
                            key: value
                            for key, value in final_match.items()
                            if key not in {"source_key", "target_key", "match_type"}
                        },
                    }
                )

            verify_problems = []
            if final_inventory_mismatches:
                verify_problems.append(f"Final target inventory differs from preflight: {len(final_inventory_mismatches)}")
            if final_match_mismatches:
                verify_problems.append(f"Final matches differ from preflight: {len(final_match_mismatches)}")
            if final_duplicates:
                verify_problems.append(f"Final duplicate keys: {len(final_duplicates)}")
            if final_missing_key:
                verify_problems.append(f"Final missing keys: {len(final_missing_key)}")
            if schedule_mismatches:
                verify_problems.append(f"Schedule mismatches: {len(schedule_mismatches)}")
            if revlog_mismatches:
                verify_problems.append(f"Revlog mismatches: {len(revlog_mismatches)}")
            if final_revlog_on_final_cards != revlog_rows_inserted:
                verify_problems.append(
                    "Final revlog row total unexpected: "
                    f"{final_revlog_on_final_cards} final rows vs {revlog_rows_inserted} inserted rows"
                )
            if default_suspended_mismatches:
                verify_problems.append(f"Default-suspended fresh card mismatches: {len(default_suspended_mismatches)}")
            if orphaned_revlog_rows:
                verify_problems.append(f"Orphaned revlog rows still present: {orphaned_revlog_rows}")
            if preset_counts != Counter({target_preset_id: len(deck_ids_under(final_root))}):
                verify_problems.append(f"Deck preset counts unexpected: {dict(preset_counts)}")
            if final_plus_notetype_names:
                verify_problems.append(
                    f"Imported hanzi notetypes still have plus suffixes: {final_plus_notetype_names}"
                )

            mw.reset()

            report_data = {
                "schema": "hanzi-stateful-migration-v1",
                "applied": not verify_problems,
                "config": {
                    "apkg_path": apkg_path,
                    "old_root": old_root,
                    "imported_root": imported_root,
                    "final_root": final_root,
                    "target_preset_name": target_preset_name,
                    "target_preset_id": target_preset_id,
                    "skipped_touched_kinds_allowed": sorted(ALLOW_SKIPPED_TOUCHED_KINDS),
                    "skipped_touched_simplified_allowed": sorted(ALLOW_SKIPPED_TOUCHED_SIMPLIFIED),
                },
                "import_result": import_result,
                "source": {
                    "cards": len(source_records),
                    "learned_keyed_cards": len(learned_source_records),
                    "kind_counts": summarize_kind_counts(source_records),
                    "build_id_counts": summarize_build_id_counts(source_records),
                    "touched_cards": len(touched_source),
                    "revlog_rows_total_for_touched": sum(record["revlog_count"] for record in touched_source),
                },
                "match": {
                    "matched_learned_cards": len(matched_source_keys),
                    "exact_matched_learned_cards": len(match_plan["exact_source_keys"]),
                    "special_matched_learned_cards": len(special_match_source_keys(match_plan)),
                    "special_match_type_counts": special_match_type_counts(match_plan),
                    "loose_matched_learned_cards": len(match_plan["loose_source_keys"]),
                    "resolved_source_duplicate_keys": len(preflight["resolved_source_duplicates"]),
                    "default_only_target_cards": len(default_only_target_keys),
                    "touched_matched_cards": len(touched_matched_source_keys),
                    "touched_skipped_cards": len(touched_unmatched),
                    "touched_skipped_kind_counts": dict(
                        sorted(skipped_touched_kind_counts.items(), key=lambda item: str(item[0]))
                    ),
                    "default_suspended_target_cards": default_suspended_set,
                },
                "apply": {
                    "full_state_copied": full_state_copied,
                    "old_notetypes_removed": len(notetype_cleanup["removed"]),
                    "default_suspended_set": default_suspended_set,
                    "revlog_rows_inserted": revlog_rows_inserted,
                    "skipped_touched_revlog_rows": skipped_touched_revlog_rows,
                    "preset_changed_decks": len(preset_changed_decks),
                },
                "final": {
                    "cards": len(final_records),
                    "kind_counts": summarize_kind_counts(final_records),
                    "build_id_counts": summarize_build_id_counts(final_records),
                    "hanzi_notetype_names": final_hanzi_notetype_names,
                    "queue_counts": dict(sorted(queue_counts.items())),
                    "revlog_rows_on_final_cards": final_revlog_on_final_cards,
                    "orphaned_revlog_rows": orphaned_revlog_rows,
                    "preset_counts": dict(preset_counts),
                },
                "samples": {
                    "skipped_touched_unmatched": [card_summary(record) for record in touched_unmatched[:20]],
                    "old_notetypes_removed": notetype_cleanup["removed"],
                    "resolved_source_duplicates": preflight["resolved_source_duplicates"][:20],
                    "resolved_source_duplicate_keys": [
                        item["key"] for item in preflight["resolved_source_duplicates"][:100]
                    ],
                    "special_matches": special_match_samples,
                    "loose_matches": loose_match_samples,
                    "match_plan_mismatches": final_match_mismatches,
                    "target_inventory_mismatches": final_inventory_mismatches,
                    "schedule_mismatches": schedule_mismatches[:20],
                    "revlog_mismatches": revlog_mismatches[:20],
                    "default_suspended_mismatches": default_suspended_mismatches[:20],
                },
                "verify_problems": verify_problems,
                "collection_mod_before": collection_mod_before,
                "collection_mod_after": getattr(mw.col, "mod", None),
            }

            status = (
                "HANZI STATEFUL MIGRATION APPLIED: all learned card states transferred successfully"
                if not verify_problems
                else "HANZI STATEFUL MIGRATION NEEDS ATTENTION: state transfer verification failed"
            )
            lines = [
                status,
                f"final root: {final_root}",
                f"matched learned cards: {len(matched_source_keys)}",
                f"special matches: {len(special_match_source_keys(match_plan))}",
                f"loose matches: {len(match_plan['loose_source_keys'])}",
                f"resolved duplicate source keys: {len(preflight['resolved_source_duplicates'])}",
                f"full states copied: {full_state_copied}",
                f"old hanzi notetypes removed: {len(notetype_cleanup['removed'])}",
                f"default-suspended target cards set: {default_suspended_set}",
                f"revlog rows inserted: {revlog_rows_inserted}",
                f"touched cards skipped intentionally: {len(touched_unmatched)}",
                f"skipped revlog rows: {skipped_touched_revlog_rows}",
                f"default-only target cards: {len(default_only_target_keys)}",
                f"final queue counts: {dict(sorted(queue_counts.items()))}",
                f"deck preset set: {target_preset_name} / {target_preset_id}",
            ]
            if verify_problems:
                lines.append("verify problems:")
                lines.extend(f"  {problem}" for problem in verify_problems)
            else:
                lines.append(
                    "state verification: all learned schedules/revlogs, default suspension, presets, and note types verified"
                )
            lines.append("Full JSON copied to clipboard")
            report = "\n".join(lines) + "\n\n" + _build_report_json(report_data)

        except Exception:
            tb = traceback.format_exc()
            rollback_note = ""
            if state_savepoint_started:
                try:
                    mw.col.db.execute("rollback to savepoint hanzi_stateful_apply")
                    mw.col.db.execute("release savepoint hanzi_stateful_apply")
                    rollback_note = "State-apply savepoint rolled back."
                except Exception:
                    rollback_note = "State-apply rollback failed:\n" + traceback.format_exc()
            try:
                mw.reset()
            except Exception:
                pass
            report = "HANZI STATEFUL MIGRATION FAILED\n\n" + rollback_note + "\n\n" + tb

        self._copy_report_to_clipboard(report)
        return {
            "success": bool(report_data and report_data.get("applied") and not report_data.get("verify_problems")),
            "text": report,
            "json": report_data,
        }

    def _copy_report_to_clipboard(self, report: str) -> None:
        try:
            from aqt.qt import QApplication

            QApplication.clipboard().setText(report)
        except Exception:
            pass

    def preflight_items(self, report_json: dict[str, Any]) -> list[ReportItem]:
        source = report_json.get("source", {})
        target = report_json.get("target_preview", {})
        config = report_json.get("config", {})
        match = report_json.get("match", {})
        problems = report_json.get("problems", [])
        problem_details = report_json.get("problem_details", {})
        learned_cards = source.get("learned_keyed_cards", 0)
        matched_cards = match.get("matched_learned_cards", 0)
        exact_cards = match.get("exact_matched_learned_cards", 0)
        special_cards = match.get("special_matched_learned_cards", 0)
        loose_cards = match.get("loose_matched_learned_cards", 0)
        touched_unmatched = match.get("touched_unmatched_cards", 0)
        resolved_duplicates = match.get("resolved_source_duplicate_keys", 0)
        unresolved_duplicates = match.get("unresolved_source_duplicate_keys", 0)

        items = [
            report_item(
                "ok",
                "Existing deck",
                (
                    f"{config.get('old_root', '?')} | {source.get('cards', 0)} cards | "
                    f"{source.get('touched_cards', 0)} touched | builds {_build_id_text(source.get('build_id_counts'))}"
                ),
                [_kind_count_text(source.get("kind_counts"))],
            ),
            report_item(
                "ok",
                "Target APKG",
                (
                    f"{Path(config.get('apkg_path', '?')).name} | {target.get('cards', 0)} cards | "
                    f"builds {_build_id_text(target.get('build_id_counts'))}"
                ),
                [_kind_count_text(target.get("kind_counts"))],
            ),
            report_item(
                "ok",
                "Deck preset",
                f"{config.get('target_preset_name', '?')} / {config.get('target_preset_id', '?')}",
            ),
        ]

        if problems:
            match_status = "error"
        elif special_cards or loose_cards:
            match_status = "warn"
        elif matched_cards == learned_cards and exact_cards == learned_cards:
            match_status = "ok"
        else:
            match_status = "warn"
        items.append(
            report_item(
                match_status,
                "Learned card matching",
                (
                    f"{matched_cards} of {learned_cards} learned/touched cards matched; "
                    f"{exact_cards} exact, {special_cards} special "
                    f"({_match_type_counts_text(match.get('special_match_type_counts'))}), "
                    f"{loose_cards} loose, {touched_unmatched} unmatched."
                ),
            )
        )

        duplicate_status = "error" if unresolved_duplicates else "warn" if resolved_duplicates else "ok"
        duplicate_details = []
        duplicate_details.extend(
            f"resolved: {_summary_label(sample)}"
            for sample in problem_details.get("resolved_source_duplicate_samples", [])[:8]
        )
        duplicate_details.extend(
            f"unresolved: {_summary_label(sample)}"
            for sample in problem_details.get("unresolved_source_duplicate_samples", [])[:8]
        )
        items.append(
            report_item(
                duplicate_status,
                "Duplicate source keys",
                f"{resolved_duplicates} resolved, {unresolved_duplicates} unresolved.",
                duplicate_details,
            )
        )

        disallowed_unmatched = problem_details.get("disallowed_touched_unmatched", [])
        problem_lines = [str(problem) for problem in problems]
        if disallowed_unmatched:
            problem_lines.append("Unmatched touched cards:")
            problem_lines.extend(_sample_lines(disallowed_unmatched))
        items.append(
            report_item(
                "error" if problems else "ok",
                "Preflight decision",
                "Ready to apply after a full collection backup." if not problems else "Migration is blocked.",
                problem_lines,
            )
        )
        return items

    def result_items(self, report_json: dict[str, Any] | None) -> list[ReportItem]:
        if not report_json:
            return [
                report_item(
                    "error",
                    "Migration result",
                    "The migration finished without a structured JSON report. Open the full report for details.",
                )
            ]

        source = report_json.get("source", {})
        final = report_json.get("final", {})
        match = report_json.get("match", {})
        apply = report_json.get("apply", {})
        samples = report_json.get("samples", {})
        config = report_json.get("config", {})
        verify_problems = report_json.get("verify_problems", [])
        applied = bool(report_json.get("applied"))

        items = [
            report_item(
                "ok" if applied and not verify_problems else "error",
                "Verification",
                (
                    "All learned schedules, revlogs, default suspension, presets, and note types verified."
                    if applied and not verify_problems
                    else "Migration needs attention."
                ),
                [str(problem) for problem in verify_problems],
            ),
            report_item(
                "ok",
                "Deck replacement",
                (
                    f"{config.get('old_root', '?')} -> {config.get('final_root', '?')} | "
                    f"{source.get('cards', 0)} source cards, {final.get('cards', 0)} final cards | "
                    f"target builds {_build_id_text(final.get('build_id_counts'))}"
                ),
            ),
        ]

        special_matches = match.get("special_matched_learned_cards", 0)
        loose_matches = match.get("loose_matched_learned_cards", 0)
        skipped_cards = match.get("touched_skipped_cards", 0)
        items.append(
            report_item(
                "warn" if special_matches or loose_matches or skipped_cards else "ok",
                "Learned state transfer",
                (
                    f"{apply.get('full_state_copied', 0)} full states copied from "
                    f"{match.get('matched_learned_cards', 0)} matched learned cards; "
                    f"{special_matches} special matches "
                    f"({_match_type_counts_text(match.get('special_match_type_counts'))}); "
                    f"{loose_matches} loose matches; {skipped_cards} intentionally skipped."
                ),
                _sample_lines(samples.get("special_matches", []), 8)
                + _sample_lines(samples.get("loose_matches", []), 8)
                + _sample_lines(samples.get("skipped_touched_unmatched", []), 8),
            )
        )
        items.append(
            report_item(
                "ok" if not samples.get("revlog_mismatches") else "error",
                "Review history",
                f"{apply.get('revlog_rows_inserted', 0)} revlog rows inserted.",
                [str(sample) for sample in samples.get("revlog_mismatches", [])[:8]],
            )
        )
        items.append(
            report_item(
                "ok" if not samples.get("default_suspended_mismatches") else "error",
                "Default suspension",
                (
                    f"{apply.get('default_suspended_set', 0)} target cards set to default suspended; "
                    f"{match.get('default_only_target_cards', 0)} cards remained default-only."
                ),
                [str(sample) for sample in samples.get("default_suspended_mismatches", [])[:8]],
            )
        )
        items.append(
            report_item(
                "ok",
                "Cleanup and preset",
                (
                    f"{apply.get('old_notetypes_removed', 0)} old Hanzi note types removed; "
                    f"preset set to {config.get('target_preset_name', '?')} / {config.get('target_preset_id', '?')}."
                ),
                [str(sample) for sample in samples.get("old_notetypes_removed", [])],
            )
        )
        items.append(
            report_item(
                "ok",
                "Final queues",
                f"{final.get('queue_counts', {})}",
            )
        )
        return items
