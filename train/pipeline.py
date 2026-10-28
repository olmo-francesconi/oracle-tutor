"""Train, evaluate and promote a model in one go: train.tags, train.dataset, train.train, train.eval, app.build --promote.

Run from repo root with the bucket credentials exported (and Modal auth, unless --local):
  uv run --project train python -m train.pipeline MODEL_ID [train.train options, e.g. --epochs 4 --local]

Stops at the first failing step, so nothing is promoted unless training, upload and eval all succeeded. The refresh
worker re-embeds every card with the promoted model on its next run (daily cron, or start it on Railway).
"""

import subprocess
import sys

from app import snapshot


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        raise SystemExit(__doc__)
    model_id, train_args = sys.argv[1], sys.argv[2:]
    if not snapshot.enabled():
        raise SystemExit("BUCKET is not set: the pipeline trains on the live snapshot and uploads to the bucket")
    if snapshot.has_model(model_id):
        raise SystemExit(f"models/{model_id}/ already exists in the bucket")
    steps = (["train.tags"], ["train.dataset"], ["train.train", "--model-id", model_id, *train_args],
             ["train.eval", "--model", model_id], ["app.build", "--promote", model_id])
    for step in steps:
        print(f"== {' '.join(step)}", flush=True)
        if subprocess.run([sys.executable, "-m", *step], check=False).returncode:
            raise SystemExit(f"{step[0]} failed; {model_id} not promoted")


if __name__ == "__main__":
    main()
