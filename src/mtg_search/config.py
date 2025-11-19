from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CARDS_JSON = DATA_DIR / "cards.json"  # You’ll put Scryfall bulk here (or a subset)
CARD_NAMES_JSON = DATA_DIR / "card_names.json"
CARD_METADATA_JSON = DATA_DIR / "card_metadata.json"
