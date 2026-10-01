"""Build-ID route planning for Hanzi deck migrations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .handlers.base import MigrationStepHandler


@dataclass(frozen=True)
class DefaultStrategy:
    name: str
    description: str
    handler: MigrationStepHandler
    valid_from: str | None = None
    valid_until: str | None = None


@dataclass(frozen=True)
class SpecialTransition:
    name: str
    description: str
    from_build: str
    to_build: str
    handler: MigrationStepHandler


@dataclass(frozen=True)
class PlannedMigrationStep:
    from_build: str
    to_build: str
    kind: str
    name: str
    description: str
    handler: MigrationStepHandler


@dataclass(frozen=True)
class MigrationRoute:
    source_build: str
    target_build: str
    target_is_unknown_future: bool
    latest_known_build: str
    steps: tuple[PlannedMigrationStep, ...]
    problems: tuple[str, ...]

    @property
    def can_apply(self) -> bool:
        return not self.problems and bool(self.steps)


def _index_or_none(build_id: str | None, known_index: dict[str, int]) -> int | None:
    if build_id is None:
        return None
    return known_index[build_id]


def _boundary_in_range(build_id: str | None, start: int, end: int, known_index: dict[str, int]) -> bool:
    index = _index_or_none(build_id, known_index)
    return index is not None and start < index < end


def _default_covers(
    strategy: DefaultStrategy,
    *,
    from_index: int,
    to_index: int,
    known_index: dict[str, int],
) -> bool:
    valid_from_index = _index_or_none(strategy.valid_from, known_index)
    valid_until_index = _index_or_none(strategy.valid_until, known_index)
    if valid_from_index is not None and from_index < valid_from_index:
        return False
    if valid_until_index is not None and to_index > valid_until_index:
        return False
    return True


def _default_sort_key(strategy: DefaultStrategy, known_index: dict[str, int]) -> tuple[int, int]:
    valid_from_index = _index_or_none(strategy.valid_from, known_index)
    valid_until_index = _index_or_none(strategy.valid_until, known_index)
    return (
        valid_from_index if valid_from_index is not None else -1,
        -(valid_until_index if valid_until_index is not None else len(known_index)),
    )


def _select_default(
    strategies: Sequence[DefaultStrategy],
    *,
    from_index: int,
    to_index: int,
    known_index: dict[str, int],
) -> DefaultStrategy | None:
    candidates = [
        strategy
        for strategy in strategies
        if _default_covers(strategy, from_index=from_index, to_index=to_index, known_index=known_index)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda strategy: _default_sort_key(strategy, known_index), reverse=True)[0]


def plan_route(
    *,
    source_build: str,
    target_build: str,
    known_builds: Sequence[str],
    default_strategies: Sequence[DefaultStrategy],
    special_transitions: Sequence[SpecialTransition],
) -> MigrationRoute:
    known_index = {build_id: index for index, build_id in enumerate(known_builds)}
    latest_known_build = known_builds[-1] if known_builds else "<unknown>"
    problems: list[str] = []

    if not known_builds or any(not build_id for build_id in known_builds):
        problems.append("Known migration builds must not be empty or contain empty IDs.")
    if len(known_index) != len(known_builds):
        problems.append("Known migration builds must not contain duplicate IDs.")

    for strategy in default_strategies:
        unknown_bounds = [
            build_id
            for build_id in (strategy.valid_from, strategy.valid_until)
            if build_id is not None and build_id not in known_index
        ]
        if unknown_bounds:
            problems.append(f"Default strategy {strategy.name!r} references unknown builds: {unknown_bounds}")
            continue
        valid_from = _index_or_none(strategy.valid_from, known_index)
        valid_until = _index_or_none(strategy.valid_until, known_index)
        if valid_from is not None and valid_until is not None and valid_from > valid_until:
            problems.append(f"Default strategy {strategy.name!r} has a reversed validity range.")

    transition_ranges: list[tuple[int, int, SpecialTransition]] = []
    for transition in special_transitions:
        from_index = known_index.get(transition.from_build)
        to_index = known_index.get(transition.to_build)
        if from_index is None or to_index is None:
            problems.append(f"Special transition {transition.name!r} references an unknown build.")
        elif from_index >= to_index:
            problems.append(f"Special transition {transition.name!r} must move forward between distinct builds.")
        else:
            transition_ranges.append((from_index, to_index, transition))
    transition_ranges.sort(key=lambda item: (item[0], item[1]))
    for previous, current in zip(transition_ranges, transition_ranges[1:]):
        if current[0] < previous[1]:
            problems.append(f"Special transitions {previous[2].name!r} and {current[2].name!r} overlap.")

    source_index = known_index.get(source_build)
    if source_index is None:
        problems.append(f"Source build is not known by this migrator: {source_build}")

    target_is_unknown_future = target_build not in known_index
    target_index = len(known_builds) if target_is_unknown_future else known_index[target_build]
    if source_index is not None and target_index < source_index:
        problems.append(f"Target build {target_build} is older than source build {source_build}; downgrades are not supported.")
    for from_index, to_index, transition in transition_ranges:
        if source_index is not None and from_index < source_index < to_index <= target_index:
            problems.append(
                f"Route cannot apply special transition {transition.name!r}: "
                f"source build {source_build} is already past its required start {transition.from_build}."
            )
    if problems:
        return MigrationRoute(
            source_build=source_build,
            target_build=target_build,
            target_is_unknown_future=target_is_unknown_future,
            latest_known_build=latest_known_build,
            steps=(),
            problems=tuple(problems),
        )

    if target_index == source_index:
        strategy = _select_default(
            default_strategies,
            from_index=source_index,
            to_index=target_index,
            known_index=known_index,
        )
        if strategy is None:
            return MigrationRoute(
                source_build=source_build,
                target_build=target_build,
                target_is_unknown_future=target_is_unknown_future,
                latest_known_build=latest_known_build,
                steps=(),
                problems=(f"No migration strategy covers same-build migration for {source_build}.",),
            )
        return MigrationRoute(
            source_build=source_build,
            target_build=target_build,
            target_is_unknown_future=target_is_unknown_future,
            latest_known_build=latest_known_build,
            steps=(
                PlannedMigrationStep(
                    from_build=source_build,
                    to_build=target_build,
                    kind="default",
                    name=strategy.name,
                    description=strategy.description,
                    handler=strategy.handler,
                ),
            ),
            problems=(),
        )

    breakpoints_by_index: dict[int, str] = {source_index: source_build}
    if target_is_unknown_future:
        if source_index < len(known_builds) - 1:
            breakpoints_by_index[len(known_builds) - 1] = latest_known_build
        breakpoints_by_index[target_index] = target_build
    else:
        breakpoints_by_index[target_index] = target_build

    active_transitions = [
        (start, end, transition)
        for start, end, transition in transition_ranges
        if source_index <= start < end <= target_index
    ]
    for from_index, to_index, transition in active_transitions:
        breakpoints_by_index[from_index] = transition.from_build
        breakpoints_by_index[to_index] = transition.to_build

    for strategy in default_strategies:
        if _boundary_in_range(strategy.valid_from, source_index, target_index, known_index):
            breakpoints_by_index[known_index[strategy.valid_from]] = strategy.valid_from
        if _boundary_in_range(strategy.valid_until, source_index, target_index, known_index):
            breakpoints_by_index[known_index[strategy.valid_until]] = strategy.valid_until

    # A special transition is indivisible, even if default ranges change inside it.
    breakpoints = sorted(
        (index, build_id)
        for index, build_id in breakpoints_by_index.items()
        if not any(start < index < end for start, end, _ in active_transitions)
    )
    special_by_edge = {
        (transition.from_build, transition.to_build): transition
        for transition in special_transitions
    }
    steps: list[PlannedMigrationStep] = []

    for (from_index, from_build), (to_index, to_build) in zip(breakpoints, breakpoints[1:]):
        transition = special_by_edge.get((from_build, to_build))
        if transition is not None:
            steps.append(
                PlannedMigrationStep(
                    from_build=from_build,
                    to_build=to_build,
                    kind="special",
                    name=transition.name,
                    description=transition.description,
                    handler=transition.handler,
                )
            )
            continue

        strategy = _select_default(
            default_strategies,
            from_index=from_index,
            to_index=to_index,
            known_index=known_index,
        )
        if strategy is None:
            problems.append(f"No migration strategy covers {from_build} -> {to_build}.")
            continue
        steps.append(
            PlannedMigrationStep(
                from_build=from_build,
                to_build=to_build,
                kind="default",
                name=strategy.name,
                description=strategy.description,
                handler=strategy.handler,
            )
        )

    return MigrationRoute(
        source_build=source_build,
        target_build=target_build,
        target_is_unknown_future=target_is_unknown_future,
        latest_known_build=latest_known_build,
        steps=tuple(steps),
        problems=tuple(problems),
    )
