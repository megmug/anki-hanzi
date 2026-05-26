## Deck Structure

- Move toward a single deck with tags instead of many HSK subdecks.
- Remove HSK duplicates by creating one entry per canonical word key and attaching
  all matching HSK tags.
- Preserve enough metadata to filter by HSK level, source, frequency, and custom
  additions.

## Configuration

- Introduce one default configuration file for the generator.
- Put deck settings, card types, defaults, data sources, tags, and extras in one
  structured JSON file where possible.
- Keep `extra_words` support, but make it cleaner and part of the config-driven
  pipeline.
- If a website exists later, make it generate or edit this JSON config rather than
  owning separate generation logic.
