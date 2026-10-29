"""Known migration checkpoints and strategies."""

from __future__ import annotations

import json
from pathlib import Path

from .handlers import CurrentDefaultMigration, ErhuaR5DisplayMigration
from .routing import DefaultStrategy, MigrationRoute, SpecialTransition, plan_route


BUILD_INFO_PATH = Path(__file__).resolve().parent / "build_info.json"
ERHUA_R5_DISPLAY_SOURCE_BUILD = "b11023a"
ERHUA_R5_DISPLAY_TARGET_BUILD = "fd6ecb0"

CURRENT_DEFAULT = CurrentDefaultMigration()
ERHUA_R5_DISPLAY = ErhuaR5DisplayMigration()

DEFAULT_STRATEGIES = (
    DefaultStrategy(
        name=CURRENT_DEFAULT.name,
        description=CURRENT_DEFAULT.description,
        valid_from=None,
        valid_until=None,
        handler=CURRENT_DEFAULT,
    ),
)

def read_build_info() -> dict:
    if not BUILD_INFO_PATH.exists():
        return {}
    try:
        return json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def known_build_ids() -> tuple[str, ...]:
    build_info = read_build_info()
    raw_build_ids = build_info.get("known_build_ids")
    if isinstance(raw_build_ids, list):
        build_ids = [build_id for build_id in raw_build_ids if isinstance(build_id, str) and build_id]
        if build_ids:
            return tuple(dict.fromkeys(build_ids))

    current_build_id = build_info.get("build_id")
    if isinstance(current_build_id, str) and current_build_id:
        return (current_build_id,)
    return ()


SPECIAL_TRANSITIONS: tuple[SpecialTransition, ...] = (
    SpecialTransition(
        name=ERHUA_R5_DISPLAY.name,
        description=ERHUA_R5_DISPLAY.description,
        from_build=ERHUA_R5_DISPLAY_SOURCE_BUILD,
        to_build=ERHUA_R5_DISPLAY_TARGET_BUILD,
        handler=ERHUA_R5_DISPLAY,
    ),
)


def special_transitions() -> tuple[SpecialTransition, ...]:
    return SPECIAL_TRANSITIONS


def plan_migration_route(source_build: str, target_build: str):
    known_builds = known_build_ids()
    if not known_builds:
        return MigrationRoute(
            source_build=source_build,
            target_build=target_build,
            target_is_unknown_future=True,
            latest_known_build="<unknown>",
            steps=(),
            problems=("Migrator package does not contain known build IDs.",),
        )
    return plan_route(
        source_build=source_build,
        target_build=target_build,
        known_builds=known_builds,
        default_strategies=DEFAULT_STRATEGIES,
        special_transitions=special_transitions(),
    )
