# Deck Inputs

This directory contains source inputs that are read to build the custom APKG.
Generated reports, generated master JSON files, package caches, and final APKGs
should stay outside this directory.

## Contents

- `hsk-3.0-words-list/`: upstream HSK/xiehanzi word-list submodule, including
  prepared xiehanzi TSV files and source audio.
- `HSK Wordlist/`: older upstream HSK word-list material kept as source input
  material, but not used by the current custom APKG build.
- `cc-cedict/`: pinned CC-CEDICT snapshot used to generate the compact master
  lexicon before enrichment.
- `extra_words.tsv`: custom extra entries that should be added to the generated
  deck.
- `deck_config.json`: first-pass deck selection config. It selects which
  enriched xiehanzi study targets become generated notes, such as all HSK
  levels plus specific extra Simplified words.
- `extra_audio/`: committed/generated custom audio files for extra entries.
- `card_templates/`: Anki card HTML/CSS templates and static media packaged
  into the APKG.
- `fonts/`: upstream font assets kept with the deck inputs. The current custom
  generator packages only the Material Icons files referenced from
  `card_templates/fonts/`; these font assets are kept here as template source
  material until the remaining template/font usage is simplified.
