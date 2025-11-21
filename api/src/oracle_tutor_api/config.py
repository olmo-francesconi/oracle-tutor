from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CARDS_JSON = DATA_DIR / "cards.json"
CARD_METADATA_JSON = DATA_DIR / "card_metadata.json"
