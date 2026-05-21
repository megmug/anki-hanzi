# TODO

This fork is moving toward a focused, reproducible custom xiehanzi deck generator.
The current repo still carries several upstream concerns at once: website, generated
artifacts, old templates, multiple data formats, and overlapping build paths. Keep
the work incremental.

## Build And Release

- Keep the GitHub Action building the custom APKG on push, pull request, and
  manual dispatch.
- Keep generated decks and build reports available as workflow artifacts.
- Later: publish release artifacts on tags.
- Make sure the Action builds the deck with the default configuration.

## Product Focus

- Define the default target clearly: simplified Chinese, pinyin, audio, meanings,
  and writer/scoring cards.
- Do not optimize the default deck for traditional characters, zhuyin, Japanese,
  or other unrelated learning modes.
- Keep optional support separate from the default path.

## Website

- Keep the old Docusaurus/React website out of the active build path.
- If a website returns later, make it a small configuration editor that emits
  generator JSON instead of carrying a second deck-generation path.

## Data Model

- Simplify and unify the data basis.
- Reduce redundant prepared data files and unclear intermediate artifacts.
- Prototype a pinned CC-CEDICT importer that generates a reproducible master JSON
  lexicon before applying HSK/xiehanzi/custom overlays.
- Evaluate `drkameleon/complete-hsk-vocabulary` as a cleaner primary HSK source.
- As a first experiment, add `complete-hsk-vocabulary` as a submodule and try to
  reproduce the current custom deck from its `complete.json` data.
- Consider a larger lexical basis, such as CC-CEDICT plus character metadata, but
  keep it clean and filtered.
- Treat HSK as tags/metadata, not as the primary deck structure.
- Keep extra/custom words as first-class input data.

## Deck Structure

- Move toward a single deck with tags instead of many HSK subdecks.
- Remove HSK duplicates by creating one entry per canonical word key and attaching
  all matching HSK tags.
- Preserve enough metadata to filter by HSK level, source, frequency, and custom
  additions.

## Templates

- Remove old and unused templates.
- Simplify and unify the remaining template code.
- Keep the Write card focused on recall writing with HanziWriter and score feedback.
- Keep default display settings aligned with the custom focus: simplified and
  pinyin on, traditional and zhuyin off.

## Dependencies

- Use as few dependencies as practical.
- Make dependencies deterministic.
- Keep JavaScript dependency management Yarn-only.
- Keep `package.json` minimal and `yarn.lock` intentional.
- Let Nix materialize Yarn dependencies via `fetchYarnDeps` for reproducible
  builds.
- Document why Python dependencies live in Nix while JavaScript dependencies use
  `package.json` plus `yarn.lock`.

## Audio

- Evaluate Qwen3-TTS as a possible replacement or optional backend for generated
  Mandarin audio.
- Compare generated audio quality, latency, licensing, reproducibility, and CI
  feasibility against the current `edge-tts` path.

## Reproducibility

- Make APKG builds as reproducible as possible from the same inputs.
- Avoid unnecessary timestamps and nondeterministic IDs where feasible.
- Use pinned Nix inputs and lockfiles as the foundation.
- Track which remaining APKG fields prevent identical output hashes.

## Configuration

- Introduce one default configuration file for the generator.
- Put deck settings, card types, defaults, data sources, tags, and extras in one
  structured JSON file where possible.
- Keep `extra_words` support, but make it cleaner and part of the config-driven
  pipeline.
- If a website exists later, make it generate or edit this JSON config rather than
  owning separate generation logic.

## Repository Cleanup

- Remove generated build artifacts from version control where they do not belong.
- Clean up redundant folders, stale outputs, old data formats, and duplicate build
  systems.
- Document which files are source inputs, generated outputs, cache files, and
  release artifacts.
