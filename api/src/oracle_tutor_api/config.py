from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CARDS_JSON = DATA_DIR / "cards.json"
CARD_METADATA_JSON = DATA_DIR / "card_metadata.json"

# Semantic Versioning for DB Schema (Major.Minor.Patch)
# Increment Major (1.0 -> 2.0) for breaking changes requiring full re-index
# Increment Minor (1.0 -> 1.1) for additive changes
DB_SCHEMA_VERSION = "0.0.1"
