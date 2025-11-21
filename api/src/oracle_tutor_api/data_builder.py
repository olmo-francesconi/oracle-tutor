import argparse
import json
import logging
from importlib import import_module
from pathlib import Path
from typing import Dict, Iterable, Optional

import requests

from .config import (
    CARD_METADATA_JSON,
    CARDS_JSON,
    DATA_DIR,
)
from .logging_config import setup_loggers

logger = logging.getLogger("oracle_tutor_api.data")

BULK_DATA_ID = "oracle_cards"
BULK_DATA_URL = f"https://api.scryfall.com/bulk-data/{BULK_DATA_ID}"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def fetch_bulk_metadata(url: str = BULK_DATA_URL) -> Dict[str, str]:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "download_uri" not in data:
        raise RuntimeError(f"No download URI found in bulk data response ({url})")
    return data


def download_bulk_file(download_url: str, destination: Path = CARDS_JSON) -> None:
    tqdm = import_module("tqdm").tqdm
    tmp_path = destination.with_suffix(destination.suffix + ".tmp")
    with requests.get(download_url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total_bytes = int(resp.headers.get("Content-Length", 0))
        progress = tqdm(
            total=total_bytes or None,
            unit="B",
            unit_scale=True,
            desc="Downloading cards",
        )
        with tmp_path.open("wb") as outfile:
            for chunk in resp.iter_content(chunk_size=1_048_576):
                if chunk:
                    outfile.write(chunk)
                    progress.update(len(chunk))
        progress.close()
    tmp_path.replace(destination)


def load_local_metadata(path: Path = CARD_METADATA_JSON) -> Optional[Dict[str, str]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_metadata(metadata: Dict[str, str], path: Path = CARD_METADATA_JSON) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
        f.write("\n")
    tmp_path.replace(path)


def data_files_exist() -> bool:
    return CARDS_JSON.exists()


def metadata_is_current(
    remote: Dict[str, str], local: Optional[Dict[str, str]]
) -> bool:
    if not local:
        return False
    return (
        remote.get("content_updated_at") == local.get("content_updated_at")
        and remote.get("download_uri") == local.get("download_uri")
    )


def update_scryfall_data(force: bool = False) -> bool:
    ensure_data_dir()
    metadata = fetch_bulk_metadata()
    local_metadata = load_local_metadata()
    needs_download = (
        force
        or not data_files_exist()
        or not metadata_is_current(metadata, local_metadata)
    )

    if needs_download:
        download_uri = metadata["download_uri"]
        size_mb = round(metadata.get("compressed_size", 0) / (1024 * 1024), 2)
        logger.info(f"Downloading oracle_cards bulk ({size_mb} MB) ...")
        download_bulk_file(download_uri)
        logger.info(f"Wrote bulk card data to {CARDS_JSON}")
        save_metadata(metadata)
    else:
        logger.info("Local Scryfall data already up to date.")

    return needs_download


def main() -> None:
    setup_loggers()
    parser = argparse.ArgumentParser(description="Update local Scryfall data files.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force download even if local metadata matches remote.",
    )
    args = parser.parse_args()
    update_scryfall_data(force=args.force)


if __name__ == "__main__":
    main()
