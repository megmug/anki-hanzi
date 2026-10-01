"""Minimal Anki UI for the stateful Hanzi deck migrator."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any

from aqt import mw
from aqt.qt import (
    QAction,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showCritical, showInfo, showWarning

from . import registry
from .routing import MigrationRoute, PlannedMigrationStep


ADDON_DIR = Path(__file__).resolve().parent
BUILD_INFO_PATH = ADDON_DIR / "build_info.json"


def _build_info() -> dict[str, Any]:
    if not BUILD_INFO_PATH.exists():
        return {}
    try:
        return json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _copy_text(text: str) -> None:
    QApplication.clipboard().setText(text)


def _top_level_window():
    return mw if mw is not None else None


def _item(status: str, title: str, detail: str, details: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "title": title,
        "detail": detail,
        "details": details or [],
    }


def _badge_html(status: str) -> str:
    styles = {
        "ok": ("&#10003;", "#1b7f3b", "#dff5e5"),
        "warn": ("!", "#9a6700", "#fff4ce"),
        "error": ("&#10005;", "#b42318", "#fde7e9"),
        "info": ("i", "#2457a6", "#e7f0ff"),
    }
    symbol, color, background = styles.get(status, styles["info"])
    return (
        f'<span style="color:{color}; background:{background}; border-radius:9px; '
        f'font-size:18px; font-weight:700; padding:1px 7px;">{symbol}</span>'
    )


def _item_widget(item: dict[str, Any]) -> QWidget:
    frame = QFrame()
    frame.setStyleSheet(
        "QFrame { border: 1px solid #d0d0d0; border-radius: 6px; padding: 8px; } QLabel { border: none; }"
    )
    layout = QHBoxLayout(frame)
    badge = QLabel(_badge_html(item["status"]))
    badge.setMinimumWidth(44)
    layout.addWidget(badge)

    body = QLabel()
    body.setWordWrap(True)
    details = "".join(
        f"<li>{html.escape(str(detail))}</li>" for detail in item.get("details", []) if str(detail).strip()
    )
    details_html = f"<ul>{details}</ul>" if details else ""
    body.setText(
        f"<div><b>{html.escape(item['title'])}</b><br><span>{html.escape(item['detail'])}</span>{details_html}</div>"
    )
    layout.addWidget(body)
    return frame


class RawReportDialog(QDialog):
    def __init__(self, *, title: str, report_text: str) -> None:
        super().__init__(_top_level_window())
        self.setWindowTitle(title)
        self.setMinimumSize(760, 560)
        self._report_text = report_text

        layout = QVBoxLayout(self)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(report_text)
        layout.addWidget(text)

        buttons = QDialogButtonBox()
        copy_report = QPushButton("Copy Report")
        buttons.addButton(copy_report, QDialogButtonBox.ButtonRole.ActionRole)
        close_button = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        copy_report.clicked.connect(lambda: _copy_text(self._report_text))
        close_button.clicked.connect(self.accept)
        layout.addWidget(buttons)


class ReportDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        message: str,
        items: list[dict[str, Any]],
        report_text: str,
        primary_button_label: str | None = None,
    ) -> None:
        super().__init__(_top_level_window())
        self.setWindowTitle(title)
        self.setMinimumSize(760, 560)
        self._accepted_for_apply = False
        self._report_text = report_text

        layout = QVBoxLayout(self)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        item_layout = QVBoxLayout(content)
        for item in items:
            item_layout.addWidget(_item_widget(item))
        item_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox()
        copy_report = QPushButton("Copy Report")
        show_report = QPushButton("View Report...")
        buttons.addButton(copy_report, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(show_report, QDialogButtonBox.ButtonRole.ActionRole)

        if primary_button_label:
            apply_button = QPushButton(primary_button_label)
            buttons.addButton(apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
            apply_button.clicked.connect(self._apply)
            close_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        else:
            close_button = buttons.addButton(QDialogButtonBox.StandardButton.Ok)

        close_button.clicked.connect(self.reject)
        copy_report.clicked.connect(lambda: _copy_text(self._report_text))
        show_report.clicked.connect(self._show_report)
        layout.addWidget(buttons)

    @property
    def accepted_for_apply(self) -> bool:
        return self._accepted_for_apply

    def _apply(self) -> None:
        self._accepted_for_apply = True
        self.accept()

    def _show_report(self) -> None:
        dialog = RawReportDialog(title=f"{self.windowTitle()} Report", report_text=self._report_text)
        dialog.exec()


def _select_deck_root() -> str | None:
    candidates = registry.CURRENT_DEFAULT.available_deck_roots()
    if not candidates:
        showWarning("No Anki Hanzi deck root could be detected.")
        return None

    labels = [
        f"{item['root']}  ({item['cards']} cards, {item['touched_cards']} touched, builds {item['build_id_counts']})"
        for item in candidates
    ]
    label, ok = QInputDialog.getItem(
        _top_level_window(),
        "Select Hanzi Deck",
        "Deck root to migrate:",
        labels,
        0,
        False,
    )
    if not ok or not label:
        return None
    return candidates[labels.index(label)]["root"]


def _select_apkg() -> str | None:
    QMessageBox.information(
        _top_level_window(),
        "Select Target APKG",
        (
            "Select the Anki Hanzi APKG you want to migrate to.\n\n"
            "This is the target deck package, not the migrator add-on package."
        ),
    )
    path, _ = QFileDialog.getOpenFileName(
        _top_level_window(),
        "Select Target Anki Hanzi APKG",
        str(Path.home() / "Downloads"),
        "Anki Packages (*.apkg)",
    )
    return path or None


def _browse_apkg_for_build(build_id: str) -> str | None:
    while True:
        path, _ = QFileDialog.getOpenFileName(
            _top_level_window(),
            f"Select APKG for Build {build_id}",
            str(Path.home() / "Downloads"),
            "Anki Packages (*.apkg)",
        )
        if not path:
            return None
        try:
            info = registry.CURRENT_DEFAULT.target_apkg_build_info(path)
        except Exception as exc:
            showWarning(f"Could not read APKG build information:\n\n{exc}")
            continue
        if info["problems"]:
            showWarning("Selected APKG is not usable:\n\n" + "\n".join(info["problems"]))
            continue
        if info["build_id"] == build_id:
            return path
        showWarning(f"Selected APKG has build {info['build_id']}, but this step requires build {build_id}.")


def _select_preset(deck_root: str) -> str | None:
    presets = sorted(config.get("name", "") for config in mw.col.decks.all_config() if config.get("name"))
    if not presets:
        showWarning("No Anki deck presets were found.")
        return None

    default_index = 0
    try:
        current_preset = registry.CURRENT_DEFAULT.deck_preset_name(deck_root)
        if current_preset in presets:
            default_index = presets.index(current_preset)
    except Exception:
        pass

    preset, ok = QInputDialog.getItem(
        _top_level_window(),
        "Select Deck Preset",
        "Deck preset to apply after migration:",
        presets,
        default_index,
        False,
    )
    return preset if ok and preset else None


def _resolve_preset(deck_root: str) -> str | None:
    try:
        preset = registry.CURRENT_DEFAULT.deck_preset_name(deck_root)
    except Exception:
        preset = None
    if preset:
        return preset

    showWarning("The current deck preset could not be detected automatically. Please select it manually.")
    return _select_preset(deck_root)


def _confirm_backup() -> bool:
    message = (
        "Before applying this destructive migration, make sure you have exported a full Anki collection backup "
        "including media. The add-on does not create an automatic backup in this first version.\n\n"
        "Continue only after you have a usable backup."
    )
    result = QMessageBox.warning(
        _top_level_window(),
        "Confirm Full Collection Backup",
        message,
        QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
        QMessageBox.StandardButton.Cancel,
    )
    return result == QMessageBox.StandardButton.Ok


def _build_summary(build_id: str, info: dict[str, Any]) -> str:
    return f"Build ID: {build_id} | Cards: {info['cards']}"


def _required_intermediate_builds(route: MigrationRoute) -> list[str]:
    required = []
    for step in route.steps:
        if step.to_build == route.target_build:
            continue
        if step.to_build not in required:
            required.append(step.to_build)
    return required


def _required_apkg_builds(route: MigrationRoute) -> list[str]:
    required = []
    for step in route.steps:
        if step.to_build not in required:
            required.append(step.to_build)
    return required


def _missing_intermediate_builds(route: MigrationRoute, apkg_paths: dict[str, str] | None) -> list[str]:
    selected = apkg_paths or {}
    return [build_id for build_id in _required_intermediate_builds(route) if build_id not in selected]


def _missing_apkg_builds(route: MigrationRoute, apkg_paths: dict[str, str] | None) -> list[str]:
    selected = apkg_paths or {}
    return [build_id for build_id in _required_apkg_builds(route) if build_id not in selected]


def _route_report_text(
    *,
    route: MigrationRoute,
    source_info: dict[str, Any],
    target_info: dict[str, Any],
    apkg_paths: dict[str, str] | None = None,
) -> str:
    data = {
        "schema": "hanzi-stateful-migration-route-v1",
        "can_apply": route.can_apply,
        "source": source_info,
        "target": target_info,
        "route": {
            "source_build": route.source_build,
            "target_build": route.target_build,
            "target_is_unknown_future": route.target_is_unknown_future,
            "latest_known_build": route.latest_known_build,
            "problems": list(route.problems),
            "required_apkg_builds": _required_apkg_builds(route),
            "missing_apkg_builds": _missing_apkg_builds(route, apkg_paths),
            "required_intermediate_builds": _required_intermediate_builds(route),
            "missing_intermediate_builds": _missing_intermediate_builds(route, apkg_paths),
            "steps": [
                {
                    "from_build": step.from_build,
                    "to_build": step.to_build,
                    "kind": step.kind,
                    "name": step.name,
                    "description": step.description,
                    "apkg_path": (apkg_paths or {}).get(step.to_build),
                }
                for step in route.steps
            ],
        },
    }
    lines = [
        "HANZI STATEFUL MIGRATION ROUTE",
        f"source build: {route.source_build}",
        f"target build: {route.target_build}",
        f"target unknown future: {route.target_is_unknown_future}",
        f"steps: {len(route.steps)}",
    ]
    if route.problems:
        lines.append("status: blocked")
        lines.extend(f"  {problem}" for problem in route.problems)
    else:
        lines.append("status: route ready")
    return "\n".join(lines) + "\n\n" + _json_text(data)


def _route_overview_items(
    *,
    route: MigrationRoute,
    source_info: dict[str, Any],
    target_info: dict[str, Any],
) -> list[dict[str, Any]]:
    items = [
        _item(
            "ok" if not source_info["problems"] else "error",
            "Source build",
            _build_summary(route.source_build, source_info),
            source_info["problems"],
        ),
        _item(
            "warn" if route.target_is_unknown_future else "ok",
            "Target build",
            _build_summary(route.target_build, target_info),
            (
                [f"Target is not in the known checkpoint list; treating it as future after {route.latest_known_build}."]
                if route.target_is_unknown_future
                else []
            )
            + target_info["problems"],
        ),
    ]
    if route.problems:
        items.append(_item("error", "Migration route", "Route planning failed.", list(route.problems)))
        return items

    step_details = [
        f"{index}. {step.from_build} -> {step.to_build}: {step.kind} / {step.name}"
        for index, step in enumerate(route.steps, 1)
    ]
    items.append(_item("ok", "Migration route", f"{len(route.steps)} step(s) planned.", step_details))
    return items


class PackageRequirementsDialog(QDialog):
    def __init__(
        self,
        *,
        route: MigrationRoute,
        source_info: dict[str, Any],
        target_info: dict[str, Any],
        apkg_paths: dict[str, str],
    ) -> None:
        super().__init__(_top_level_window())
        self.setWindowTitle("Anki Hanzi Migration Packages")
        self.setMinimumSize(860, 620)
        self._route = route
        self._source_info = source_info
        self._target_info = target_info
        self._apkg_paths = dict(apkg_paths)
        self._accepted_for_apply = False
        self._status_labels: dict[str, QLabel] = {}
        self._path_labels: dict[str, QLabel] = {}
        self._continue_button: QPushButton | None = None

        layout = QVBoxLayout(self)
        message = QLabel(
            "Review the planned route and select every APKG required by the migration before any preflight runs."
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        for item in _route_overview_items(route=route, source_info=source_info, target_info=target_info):
            content_layout.addWidget(_item_widget(item))

        package_title = QLabel("<b>Required APKG packages</b>")
        content_layout.addWidget(package_title)
        for build_id in _required_apkg_builds(route):
            content_layout.addWidget(self._package_row(build_id))
        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox()
        copy_report = QPushButton("Copy Report")
        show_report = QPushButton("View Report...")
        buttons.addButton(copy_report, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(show_report, QDialogButtonBox.ButtonRole.ActionRole)
        if route.can_apply:
            self._continue_button = QPushButton("Continue")
            buttons.addButton(self._continue_button, QDialogButtonBox.ButtonRole.AcceptRole)
            self._continue_button.clicked.connect(self._continue)
            close_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        else:
            close_button = buttons.addButton(QDialogButtonBox.StandardButton.Ok)
        close_button.clicked.connect(self.reject)
        copy_report.clicked.connect(lambda: _copy_text(self._report_text()))
        show_report.clicked.connect(self._show_report)
        layout.addWidget(buttons)
        self._refresh_rows()

    @property
    def accepted_for_apply(self) -> bool:
        return self._accepted_for_apply

    @property
    def apkg_paths(self) -> dict[str, str]:
        return dict(self._apkg_paths)

    def _package_row(self, build_id: str) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { border: 1px solid #d0d0d0; border-radius: 6px; padding: 8px; } QLabel { border: none; }"
        )
        layout = QHBoxLayout(frame)

        status = QLabel()
        status.setMinimumWidth(72)
        layout.addWidget(status)
        self._status_labels[build_id] = status

        role = "Final target" if build_id == self._route.target_build else "Intermediate target"
        build = QLabel(f"<b>{html.escape(build_id)}</b><br>{role}")
        build.setMinimumWidth(180)
        layout.addWidget(build)

        path_label = QLabel()
        path_label.setWordWrap(True)
        layout.addWidget(path_label, 1)
        self._path_labels[build_id] = path_label

        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda _checked=False, selected_build=build_id: self._browse(selected_build))
        layout.addWidget(browse)
        return frame

    def _browse(self, build_id: str) -> None:
        path = _browse_apkg_for_build(build_id)
        if path is None:
            return
        self._apkg_paths[build_id] = path
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        for build_id in _required_apkg_builds(self._route):
            path = self._apkg_paths.get(build_id)
            self._status_labels[build_id].setText(_badge_html("ok" if path else "warn"))
            self._path_labels[build_id].setText(
                html.escape(str(Path(path).name if path else "No APKG selected yet."))
            )
        if self._continue_button is not None:
            self._continue_button.setEnabled(not _missing_apkg_builds(self._route, self._apkg_paths))

    def _report_text(self) -> str:
        return _route_report_text(
            route=self._route,
            source_info=self._source_info,
            target_info=self._target_info,
            apkg_paths=self._apkg_paths,
        )

    def _show_report(self) -> None:
        dialog = RawReportDialog(title=f"{self.windowTitle()} Report", report_text=self._report_text())
        dialog.exec()

    def _continue(self) -> None:
        if _missing_apkg_builds(self._route, self._apkg_paths):
            showWarning("Select every required APKG before continuing.")
            return
        self._accepted_for_apply = True
        self.accept()


def _plan_route(deck_root: str, target_apkg_path: str) -> tuple[MigrationRoute, dict[str, Any], dict[str, Any]]:
    source_info = registry.CURRENT_DEFAULT.current_deck_build_info(deck_root)
    target_info = registry.CURRENT_DEFAULT.target_apkg_build_info(target_apkg_path)
    if source_info["build_id"] is None or target_info["build_id"] is None:
        source_build = source_info["build_id"] or "<unknown-source>"
        target_build = target_info["build_id"] or "<unknown-target>"
        route = registry.plan_migration_route(source_build, target_build)
        return route, source_info, target_info
    return registry.plan_migration_route(source_info["build_id"], target_info["build_id"]), source_info, target_info


def _collect_required_apkgs(
    route: MigrationRoute,
    final_apkg_path: str,
    source_info: dict[str, Any],
    target_info: dict[str, Any],
) -> dict[str, str] | None:
    dialog = PackageRequirementsDialog(
        route=route,
        source_info=source_info,
        target_info=target_info,
        apkg_paths={route.target_build: final_apkg_path},
    )
    dialog.exec()
    if not dialog.accepted_for_apply:
        return None
    return dialog.apkg_paths


def _step_context_item(step: PlannedMigrationStep, index: int, total: int, apkg_path: str) -> dict[str, Any]:
    return _item(
        "ok",
        f"Migration step {index}/{total}",
        f"{step.from_build} -> {step.to_build} using {step.name}",
        [step.description, f"Target APKG: {Path(apkg_path).name}"],
    )


def _validate_current_step_source(deck_root: str, step: PlannedMigrationStep) -> str | None:
    current_info = registry.CURRENT_DEFAULT.current_deck_build_info(deck_root)
    if current_info["problems"]:
        return "Current deck build could not be identified:\n" + "\n".join(current_info["problems"])
    if current_info["build_id"] != step.from_build:
        return f"Current deck build is {current_info['build_id']}, but next step requires {step.from_build}."
    return None


def _validate_current_step_target(apkg_path: str, step: PlannedMigrationStep) -> str | None:
    target_info = registry.CURRENT_DEFAULT.target_apkg_build_info(apkg_path)
    if target_info["problems"]:
        return "Target APKG build could not be identified:\n" + "\n".join(target_info["problems"])
    if target_info["build_id"] != step.to_build:
        return f"Target APKG build is {target_info['build_id']}, but this step requires {step.to_build}."
    return None


def _apkg_digest(apkg_path: str) -> str:
    digest = hashlib.sha256()
    with open(apkg_path, "rb") as package:
        for chunk in iter(lambda: package.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_migration() -> None:
    if not _confirm_backup():
        showInfo("Migration cancelled. No changes were applied.")
        return

    deck_root = _select_deck_root()
    if not deck_root:
        return

    preset_name = _resolve_preset(deck_root)
    if not preset_name:
        return

    apkg_path = _select_apkg()
    if not apkg_path:
        return

    try:
        route, source_info, target_info = _plan_route(deck_root, apkg_path)
    except Exception as exc:
        showCritical(f"Migration route planning failed:\n\n{exc}")
        return

    apkg_paths = _collect_required_apkgs(route, apkg_path, source_info, target_info)
    if apkg_paths is None:
        showInfo("Migration cancelled. No changes were applied.")
        return

    build_info = _build_info()
    title_suffix = f" ({build_info.get('build_id')})" if build_info.get("build_id") else ""

    for index, step in enumerate(route.steps, 1):
        step_apkg_path = apkg_paths[step.to_build]
        try:
            package_digest = _apkg_digest(step_apkg_path)
            source_problem = _validate_current_step_source(deck_root, step)
            if source_problem:
                raise ValueError(source_problem)
            target_problem = _validate_current_step_target(step_apkg_path, step)
            if target_problem:
                raise ValueError(target_problem)
            preflight = step.handler.prepare_preflight(
                apkg_path=step_apkg_path,
                deck_root=deck_root,
                target_preset_name=preset_name,
            )
        except Exception as exc:
            showCritical(f"Preflight failed before a report could be created:\n\n{exc}")
            return

        dialog = ReportDialog(
            title=f"Anki Hanzi Migration Step {index}/{len(route.steps)} Preflight" + title_suffix,
            message="Review this step's preflight report. Apply is enabled only when the step is safe.",
            items=[_step_context_item(step, index, len(route.steps), step_apkg_path)]
            + step.handler.preflight_items(preflight["json"]),
            report_text=preflight["text"],
            primary_button_label="Apply Step" if preflight["can_apply"] else None,
        )
        dialog.exec()
        if not dialog.accepted_for_apply:
            return

        try:
            source_problem = _validate_current_step_source(deck_root, step)
            if source_problem:
                raise ValueError(source_problem)
            if _apkg_digest(step_apkg_path) != package_digest:
                raise ValueError("The target APKG changed during preflight. Restart migration to review the new package.")
        except Exception as exc:
            showCritical(f"Migration step did not start:\n\n{exc}")
            return

        try:
            result = step.handler.apply(
                apkg_path=step_apkg_path,
                deck_root=deck_root,
                target_preset_name=preset_name,
            )
        except Exception as exc:
            showCritical(f"Migration crashed:\n\n{exc}")
            return

        result_dialog = ReportDialog(
            title=f"Anki Hanzi Migration Step {index}/{len(route.steps)} Result" + title_suffix,
            message="Migration step finished. Review the verification report before continuing.",
            items=[_step_context_item(step, index, len(route.steps), step_apkg_path)]
            + step.handler.result_items(result["json"]),
            report_text=result["text"],
        )
        result_dialog.exec()
        if not result["success"]:
            showWarning("Migration stopped because this step did not verify cleanly.")
            return

    showInfo("All planned Hanzi migration steps completed successfully.")


def show_about() -> None:
    build_info = _build_info()
    build_id = build_info.get("build_id") or "unknown"
    known_build_ids = build_info.get("known_build_ids")
    known_count = len(known_build_ids) if isinstance(known_build_ids, list) else 0
    latest_known = known_build_ids[-1] if known_count else "unknown"
    lines = [
        "Anki Hanzi Migrator",
        "",
        f"Build ID: {build_id}",
        f"Known migration builds: {known_count}",
        f"Latest known build: {latest_known}",
    ]
    QMessageBox.information(_top_level_window(), "About Anki Hanzi Migrator", "\n".join(lines))


def register_menu_action() -> None:
    menu = mw.form.menuTools.addMenu("Anki Hanzi Migrator")

    migrate_action = QAction("Migrate Deck...", mw)
    migrate_action.triggered.connect(run_migration)
    menu.addAction(migrate_action)

    about_action = QAction("About...", mw)
    about_action.triggered.connect(show_about)
    menu.addAction(about_action)
