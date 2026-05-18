# TODO

This fork is moving toward a focused, reproducible custom xiehanzi deck generator.
The current repo still carries several upstream concerns at once: website, generated
artifacts, old templates, multiple data formats, and overlapping build paths. Keep
the work incremental.

## Build And Release

- Add a GitHub Action that builds the custom APKG on every relevant commit and on
  manual dispatch.
- Upload the generated deck and build report as workflow artifacts.
- Later: publish release artifacts on tags.
- Make sure the Action builds the deck with the default configuration.

## Product Focus

- Define the default target clearly: simplified Chinese, pinyin, audio, meanings,
  and writer/scoring cards.
- Do not optimize the default deck for traditional characters, zhuyin, Japanese,
  or other unrelated learning modes.
- Keep optional support separate from the default path.

## Website

- Remove the separate website if it is no longer useful.
- If a website remains, simplify it dramatically.
- Prefer a website that generates/edits generator configuration JSON instead of
  carrying a second deck-generation path.

## Data Model

- Simplify and unify the data basis.
- Reduce redundant prepared data files and unclear intermediate artifacts.
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
- Avoid mixing npm and Yarn long-term; prefer Nix plus one JavaScript package
  manager, probably Yarn.
- Keep lockfiles intentional and documented.

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
