## Deck Structure

- Revisit card identity levels: keep Meaning cards on form level
  (`simplified + pinyin`), but move Pinyin and Write cards to word level
  (`simplified`) because their prompts are not inherently tied to one specific
  reading. This should be a separate model/migration change because it affects
  generated card counts and NoteID rules.
