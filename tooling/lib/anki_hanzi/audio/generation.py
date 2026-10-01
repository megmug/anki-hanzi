"""Provider-neutral audio generation orchestration."""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Iterable

from anki_hanzi.audio.api import (
    AudioBackend,
    AudioFailure,
    AudioGenerationResult,
    AudioJob,
    AudioSkip,
    remove_failed_audio_output,
)


AUDIO_FILENAME_TEMPLATES = {
    "primary": "cmn-{text}_f.mp3",
    "secondary": "cmn-{text}_m.mp3",
}


class NullAudioBackend(AudioBackend):
    engine = "off"
    voices = ()

    def setup(self) -> None:
        return None

    def synthesize(self, job: AudioJob) -> None:
        raise RuntimeError("audio generation is disabled")


def load_audio_generation_exceptions(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    words = raw.get("words", [])
    if not isinstance(words, list):
        raise ValueError(f"{path} field 'words' must be a list")

    exceptions: dict[str, str] = {}
    for item in words:
        if isinstance(item, str):
            simplified = item.strip()
            reason = "listed in audio generation exceptions"
        elif isinstance(item, dict):
            simplified = str(item.get("simplified", "")).strip()
            reason = str(item.get("reason", "listed in audio generation exceptions"))
        else:
            continue
        if simplified:
            exceptions[simplified] = reason
    return exceptions


def _prepare_audio_dir(audio_dir: Path) -> list[str]:
    removed: list[str] = []
    if audio_dir.exists():
        for path in audio_dir.glob("*"):
            if path.is_file():
                path.unlink()
                removed.append(str(path))
    audio_dir.mkdir(parents=True, exist_ok=True)
    return removed


def create_audio_backend(engine: str) -> AudioBackend:
    normalized_engine = engine.lower().replace("-", "_")
    if normalized_engine == "off":
        return NullAudioBackend()
    if normalized_engine == "edge_tts":
        from anki_hanzi.audio.edge_tts import EdgeTtsBackend

        return EdgeTtsBackend()
    if normalized_engine == "kokoro":
        from anki_hanzi.audio.kokoro import KokoroBackend

        return KokoroBackend()
    raise ValueError(f"unknown audio engine: {engine}")


class AudioGenerator:
    def __init__(
        self,
        engine: str,
        audio_dir: Path,
        exceptions_path: Path | None = None,
    ) -> None:
        self.backend = create_audio_backend(engine)
        self.audio_dir = audio_dir
        self.exceptions_path = exceptions_path

    @property
    def engine(self) -> str:
        return self.backend.engine

    @property
    def enabled(self) -> bool:
        return self.engine != "off"

    def filenames_for_text(self, text: str) -> tuple[str, str]:
        if not self.enabled:
            return ("", "")
        filenames = [AUDIO_FILENAME_TEMPLATES[voice.slot].format(text=text) for voice in self.backend.voices]
        return tuple(filenames)  # type: ignore[return-value]

    def jobs_for_texts(self, texts: Iterable[str]) -> list[AudioJob]:
        jobs: list[AudioJob] = []
        if not self.enabled:
            return jobs

        seen: set[str] = set()
        for text in texts:
            clean_text = text.strip()
            if not clean_text or clean_text in seen:
                continue
            seen.add(clean_text)
            filenames = self.filenames_for_text(clean_text)
            for voice, filename in zip(self.backend.voices, filenames, strict=True):
                jobs.append(
                    AudioJob(
                        text=clean_text,
                        output_path=self.audio_dir / filename,
                        voice=voice,
                    )
                )
        return jobs

    def voice_report(self) -> dict[str, dict[str, str]]:
        return {
            voice.slot: {
                "provider_id": voice.provider_id,
                "label": voice.label,
            }
            for voice in self.backend.voices
        }

    def generate(self, jobs: list[AudioJob]) -> AudioGenerationResult:
        removed = _prepare_audio_dir(self.audio_dir)
        if not self.enabled:
            print("  Audio generation disabled (engine: off)")
            return AudioGenerationResult([], [], removed, [])

        exceptions = load_audio_generation_exceptions(self.exceptions_path) if self.exceptions_path is not None else {}

        try:
            self.backend.setup()
        except Exception:
            return AudioGenerationResult(
                generated=[],
                failed=[
                    AudioFailure(
                        word="",
                        slot="",
                        voice="",
                        error=f"Failed to load {self.backend.engine} audio backend:\n{traceback.format_exc()}",
                    )
                ],
                removed_zero_length=removed,
                skipped=[],
            )

        generated: list[str] = []
        failed: list[AudioFailure] = []
        skipped: list[AudioSkip] = []
        unique_words = {job.text for job in jobs if job.text}
        total_words = len(unique_words)
        progress_interval = max(1, total_words // 100) if total_words else 1
        completed_words: set[str] = set()

        def mark_word_seen(text: str) -> None:
            if not text or text in completed_words:
                return
            completed_words.add(text)
            if total_words and len(completed_words) % progress_interval == 0:
                pct = len(completed_words) * 100 // total_words
                print(
                    f"  Audio progress: {len(completed_words)}/{total_words} words ({pct}%)",
                    flush=True,
                )

        for job in jobs:
            exception_reason = exceptions.get(job.text)
            if exception_reason is not None:
                print(
                    "  Audio skipped by exception DB: "
                    f"word={job.text!r} slot={job.voice.slot} "
                    f"voice={job.voice.provider_id!r}: {exception_reason}",
                    flush=True,
                )
                skipped.append(
                    AudioSkip(
                        word=job.text,
                        slot=job.voice.slot,
                        voice=job.voice.provider_id,
                        reason=exception_reason,
                    )
                )
                mark_word_seen(job.text)
                continue

            try:
                self.backend.synthesize(job)
                if not job.output_path.is_file() or job.output_path.stat().st_size == 0:
                    raise RuntimeError(f"{self.backend.engine} produced no audio data")
                generated.append(str(job.output_path))
            except Exception as exc:
                remove_failed_audio_output(job.output_path)
                print(
                    f"  {self.backend.engine} audio failed: "
                    f"word={job.text!r} slot={job.voice.slot} "
                    f"voice={job.voice.provider_id!r}: {exc}",
                    flush=True,
                )
                failed.append(
                    AudioFailure(
                        word=job.text,
                        slot=job.voice.slot,
                        voice=job.voice.provider_id,
                        error=str(exc),
                    )
                )

            mark_word_seen(job.text)

        print(f"  Audio generation complete: {len(generated)} files, {len(failed)} failures")
        return AudioGenerationResult(generated, failed, removed, skipped)
