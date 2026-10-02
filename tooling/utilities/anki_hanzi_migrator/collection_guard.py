"""Read-only protection of database records outside a migration's deck tree."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.dbproxy import DBProxy


@dataclass(frozen=True)
class TableSnapshot:
    columns: tuple[str, ...]
    key_columns: tuple[str, ...]
    rows: dict[tuple, tuple]


def _table_snapshot(db: DBProxy, table: str, keys: tuple[str, ...], scope: str, condition: str) -> TableSnapshot:
    columns = tuple(row[1] for row in db.all(f'PRAGMA table_info("{table}")'))
    if not columns or not set(keys).issubset(columns):
        raise ValueError(f"Cannot protect database table {table!r}: unsupported schema")

    # Anki's database bridge uses JSON. Encode blobs losslessly and retain SQLite
    # storage types so an empty blob, NULL, and an empty string remain distinct.
    projection = ", ".join(
        f'typeof("{column}"), CASE WHEN typeof("{column}") = \'blob\' THEN hex("{column}") ELSE "{column}" END'
        for column in columns
    )
    key_positions = tuple(columns.index(key) * 2 + 1 for key in keys)
    rows = {}
    for row in db.all(f'{scope} SELECT {projection} FROM "{table}" WHERE {condition}'):
        key = tuple(row[position] for position in key_positions)
        if key in rows:
            raise ValueError(f"Cannot protect database table {table!r}: duplicate key {key}")
        rows[key] = tuple(row)
    return TableSnapshot(columns, keys, rows)


def snapshot_unrelated_database(collection: Collection, deck_root: str) -> dict[str, TableSnapshot]:
    decks = collection.decks.all_names_and_ids()
    if sum(deck.name == deck_root for deck in decks) != 1:
        raise ValueError(f"Cannot identify migration deck root {deck_root!r} for database protection")
    deck_ids = [int(deck.id) for deck in decks if deck.name == deck_root or deck.name.startswith(deck_root + "::")]
    values = ", ".join(f"({did})" for did in deck_ids)
    scope = f"""
        WITH scope_decks(id) AS (VALUES {values}),
        scope_cards AS (
            SELECT id, nid FROM cards
            WHERE did IN scope_decks OR odid IN scope_decks
        ),
        scope_notes(id) AS (
            SELECT DISTINCT nid FROM scope_cards
            EXCEPT SELECT nid FROM cards WHERE id NOT IN (SELECT id FROM scope_cards)
        ),
        scope_notetypes(id) AS (
            SELECT mid FROM notes WHERE id IN scope_notes
            EXCEPT SELECT mid FROM notes WHERE id NOT IN scope_notes
        )
    """
    tables = {
        "decks": (("id",), "id NOT IN scope_decks"),
        "cards": (("id",), "id NOT IN (SELECT id FROM scope_cards)"),
        "notes": (("id",), "id NOT IN scope_notes"),
        "revlog": (("id",), "cid NOT IN (SELECT id FROM scope_cards)"),
        "notetypes": (("id",), "id NOT IN scope_notetypes"),
        "fields": (("ntid", "ord"), "ntid NOT IN scope_notetypes"),
        "templates": (("ntid", "ord"), "ntid NOT IN scope_notetypes"),
        # Presets are shared resources; migration may assign, not modify them.
        "deck_config": (("id",), "1"),
    }
    return {
        table: _table_snapshot(collection.db, table, keys, scope, condition)
        for table, (keys, condition) in tables.items()
    }


def compare_unrelated_database(before: dict[str, TableSnapshot], after: dict[str, TableSnapshot]) -> dict[str, Any]:
    tables = {}
    problems = []
    for table in sorted(before.keys() | after.keys()):
        if table not in before or table not in after:
            problems.append(f"Protected table missing from database snapshot: {table}")
            continue
        old, new = before[table], after[table]
        summary: dict[str, Any] = {"before_count": len(old.rows), "after_count": len(new.rows)}
        tables[table] = summary
        if old.columns != new.columns or old.key_columns != new.key_columns:
            summary["schema_changed"] = True
            problems.append(f"Protected table schema changed: {table}")
            continue

        def key_fields(key: tuple) -> dict[str, Any]:
            return dict(zip(old.key_columns, key))

        added = sorted(new.rows.keys() - old.rows.keys())
        removed = sorted(old.rows.keys() - new.rows.keys())
        changed = [key for key in sorted(old.rows.keys() & new.rows.keys()) if old.rows[key] != new.rows[key]]
        if added or removed or changed:
            summary["added"] = [key_fields(key) for key in added]
            summary["removed"] = [key_fields(key) for key in removed]
            summary["changed"] = [
                {
                    "key": key_fields(key),
                    "columns": [
                        column
                        for index, column in enumerate(old.columns)
                        if old.rows[key][index * 2 : index * 2 + 2] != new.rows[key][index * 2 : index * 2 + 2]
                    ],
                }
                for key in changed
            ]
            problems.append(f"{table}: {len(added)} added, {len(removed)} removed, {len(changed)} changed")
    return {"success": not problems, "tables": tables, "problems": problems}
