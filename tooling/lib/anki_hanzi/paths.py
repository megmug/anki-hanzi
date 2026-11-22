"""Shared paths to committed project inputs."""

from pathlib import Path


DECK_INPUTS_DIR = Path("deck_inputs")
WORD_LIST_DATA_DIR = DECK_INPUTS_DIR / "hsk-3.0-words-list"

DEFAULT_DECK_CONFIG = DECK_INPUTS_DIR / "deck_config.json"
DEFAULT_SNAPSHOT_MANIFEST = DECK_INPUTS_DIR / "cc-cedict/snapshot.json"
DEFAULT_HSK_DATA_DIR = WORD_LIST_DATA_DIR / "New HSK (2025)/Anki xiehanzi"
DEFAULT_YCT_DATA_DIR = WORD_LIST_DATA_DIR / "YCT"
DEFAULT_BCT_DATA_DIR = WORD_LIST_DATA_DIR / "BCT"
DEFAULT_FREQUENCY_LIST = WORD_LIST_DATA_DIR / "Scripts and data/blog_lit_news_tech_weibo_freq.release_sorted.txt"
