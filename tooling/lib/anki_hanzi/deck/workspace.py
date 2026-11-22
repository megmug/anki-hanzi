"""Temporary workspace for generated deck-build artifacts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class BuildWorkspace:
    root: Path

    @property
    def hanzi_writer_bundle(self) -> Path:
        return self.root / "hanzi-writer-data.js"


@contextmanager
def temporary_build_workspace() -> Iterator[BuildWorkspace]:
    with tempfile.TemporaryDirectory(prefix="anki-hanzi-build-") as temporary_dir:
        yield BuildWorkspace(root=Path(temporary_dir))
