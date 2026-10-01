"""Provider-neutral audio generation data structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class AudioVoice:
    slot: str
    provider_id: str
    label: str = ""


@dataclass(frozen=True)
class AudioJob:
    text: str
    output_path: Path
    voice: AudioVoice

    @property
    def filename(self) -> str:
        return self.output_path.name


@dataclass(frozen=True)
class AudioFailure:
    word: str
    slot: str
    voice: str
    error: str

    def report(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class AudioSkip:
    word: str
    slot: str
    voice: str
    reason: str

    def report(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class AudioGenerationResult:
    generated: list[str]
    failed: list[AudioFailure]
    removed_zero_length: list[str]
    skipped: list[AudioSkip]

    def report_failed(self) -> list[dict[str, str]]:
        return [failure.report() for failure in self.failed]

    def report_skipped(self) -> list[dict[str, str]]:
        return [skip.report() for skip in self.skipped]


class AudioBackend(Protocol):
    engine: str
    voices: tuple[AudioVoice, ...]

    def setup(self) -> None:
        """Initialize any provider state needed before job generation."""

    def synthesize(self, job: AudioJob) -> None:
        """Write one job's audio file to ``job.output_path``."""


def remove_failed_audio_output(path: Path) -> None:
    path.unlink(missing_ok=True)
