#!/usr/bin/env -S uv run python
"""
Profile the API's memory footprint.

Run from the backend directory:
    uv run python scripts/profile_api_memory.py

Uses an in-memory SQLite database with test card data to simulate
the TF-IDF index build and report memory usage. Does not require
PostgreSQL or the full dataset.
"""
from __future__ import annotations

import gc
from importlib import import_module
import os
import resource
import sys
from typing import Protocol, cast

# Use sqlite for profiling (no external DB needed)
_ = os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
# Avoid importing before env is set
_ = os.environ.setdefault("ORACLE_TUTOR_API_ENV", "development")

# Add backend src to path when run as script
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


class _MemoryInfo(Protocol):
    rss: int


class _Process(Protocol):
    def memory_info(self) -> _MemoryInfo: ...


def _rss_mb() -> float:
    """
    Return current process RSS in MiB.

    Prefer psutil for accurate current RSS; fall back to Linux /proc; lastly to ru_maxrss
    (peak RSS; monotonic, not suitable for "freed" deltas).
    """
    try:
        # Use dynamic import so the script can still run without psutil installed.
        # A small Protocol + cast avoids type-checker treating `process` as Any.
        psutil = import_module("psutil")
        process = cast(_Process, getattr(psutil, "Process")())
        memory_info = process.memory_info()
        return float(memory_info.rss) / (1024 * 1024)
    except Exception:
        pass

    try:
        with open("/proc/self/statm", "r") as f:
            parts = f.read().strip().split()
        if len(parts) >= 2:
            rss_pages = int(parts[1])
            page_size = os.sysconf("SC_PAGE_SIZE")  # bytes
            return float(rss_pages * page_size) / (1024 * 1024)
    except Exception:
        pass

    try:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux: KB, macOS: bytes
        if rss > 2**20:  # > 1M, likely bytes
            return float(rss) / (1024 * 1024)
        return float(rss) / 1024
    except Exception:
        return 0.0


def main() -> None:
    from ot_backend.core.database import SessionLocal
    from ot_backend.core.db_init import init_db
    from ot_backend.core.models import Card, CardFace
    from ot_backend.api.tfidf_index import build_tfidf_index

    print("Memory profiling: oracle-tutor-api")
    print("-" * 50)

    # Baseline after imports
    _ = gc.collect()
    baseline_mb = _rss_mb()
    print(f"After imports: {baseline_mb:.1f} MiB")

    # Init DB and seed minimal data (same pattern as conftest)
    init_db(mode="api")
    with SessionLocal() as db:
        _ = db.query(CardFace).delete()
        _ = db.query(Card).delete()
        db.commit()
        db.add_all([
            Card(id="c1", name="Lightning Bolt", layout="normal", cmc=1.0, rarity="common", legalities={}, color_identity=["R"]),
            Card(id="c2", name="Counterspell", layout="normal", cmc=2.0, rarity="common", legalities={}, color_identity=["U"]),
            Card(id="c3", name="Dark Ritual", layout="normal", cmc=1.0, rarity="common", legalities={}, color_identity=["B"]),
        ])
        db.flush()
        db.add_all([
            CardFace(card_id="c1", name="Lightning Bolt", type_line="Instant", oracle_text="Deal 3 damage to any target.", colors=["R"]),
            CardFace(card_id="c2", name="Counterspell", type_line="Instant", oracle_text="Counter target spell.", colors=["U"]),
            CardFace(card_id="c3", name="Dark Ritual", type_line="Instant", oracle_text="Add {B}{B}{B}.", colors=["B"]),
        ])
        db.commit()

    _ = gc.collect()
    after_db_mb = _rss_mb()
    print(f"After DB init + seed: {after_db_mb:.1f} MiB (+{after_db_mb - baseline_mb:.1f})")

    # Build TF-IDF index (main memory consumer)
    db = SessionLocal()
    try:
        index = build_tfidf_index(db)
        _ = gc.collect()
        after_tfidf_mb = _rss_mb()
        print(f"After TF-IDF build: {after_tfidf_mb:.1f} MiB (+{after_tfidf_mb - after_db_mb:.1f})")

        # Rough breakdown
        m_raw = index.matrix_raw
        m_l2 = index.matrix_l2
        n_faces = len(index.face_ids)
        n_features = len(index.vectorizer.vocabulary_)
        raw_nnz = m_raw.nnz if hasattr(m_raw, "nnz") else 0
        l2_nnz = m_l2.nnz if hasattr(m_l2, "nnz") else 0
        print(f"  TF-IDF: {n_faces} faces, {n_features} features")
        print(f"  Matrices: raw nnz={raw_nnz}, l2 nnz={l2_nnz}")

        del index
    finally:
        db.close()

    _ = gc.collect()
    after_del_mb = _rss_mb()
    print(f"After index release + gc: {after_del_mb:.1f} MiB")

    print("-" * 50)
    print(f"Peak (approximate): {_rss_mb():.1f} MiB")
    print("\nNote: Use a real PostgreSQL DB with full Scryfall data for production-like numbers.")


if __name__ == "__main__":
    main()
