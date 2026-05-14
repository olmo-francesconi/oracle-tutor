"""Upgrade every registry manifest in S3 to the current schema version.

Idempotent: manifests that already declare the current version with the
required fields are skipped. Run once after deploying a new manifest schema,
or any time sync-from-S3 starts failing with "run the backfill" messages.

Usage (from backend/):
    uv run python -m scripts.backfill_manifests
    uv run python -m scripts.backfill_manifests --prod
"""

from __future__ import annotations

import argparse
import logging

from scripts._common import add_prod_flag, load_env, setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill semantic registry manifests in S3.")
    add_prod_flag(parser)
    args = parser.parse_args()

    load_env(prod=args.prod)
    setup_logging()

    from ot_backend.semantic.manifest_backfill import backfill_manifests

    log = logging.getLogger("ot_backend.scripts.backfill_manifests")
    log.info("Scanning S3 registry for manifests below the current schema version…")
    report = backfill_manifests()

    log.info(
        "Models: scanned=%d upgraded=%d skipped=%d failed=%d",
        report.models_scanned,
        report.models_upgraded,
        report.models_skipped,
        len(report.models_failed),
    )
    for model_id, err in report.models_failed:
        log.error("  model %s: %s", model_id, err)

    log.info(
        "Datasets: scanned=%d upgraded=%d skipped=%d failed=%d",
        report.datasets_scanned,
        report.datasets_upgraded,
        report.datasets_skipped,
        len(report.datasets_failed),
    )
    for dataset_id, err in report.datasets_failed:
        log.error("  dataset %s: %s", dataset_id, err)


if __name__ == "__main__":
    main()
