"""Train, evaluate and promote a model in one go: train.tags, train.dataset, train.train, train.eval, app.build --promote.

Run from repo root with the bucket credentials exported (and Modal auth, unless --local):
  uv run --project train python -m train.pipeline MODEL_ID [train.train options, e.g. --epochs 4 --local]

Stops at the first failing step, so nothing is promoted unless training, upload and eval all succeeded. Every line is
timestamped and teed to train/runs/<model_id>/pipeline.log, which is uploaded next to the model. The refresh worker
re-embeds every card with the promoted model on its next run (daily cron, or start it on Railway).
"""

import os
import subprocess
import sys
import time
from pathlib import Path

from app import snapshot


def duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02}m{s:02}s" if h else f"{m}m{s:02}s" if m else f"{s}s"


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        raise SystemExit(__doc__)
    model_id, train_args = sys.argv[1], sys.argv[2:]
    if not snapshot.enabled():
        raise SystemExit("BUCKET is not set: the pipeline trains on the live snapshot and uploads to the bucket")
    if snapshot.has_model(model_id):
        raise SystemExit(f"models/{model_id}/ already exists in the bucket")
    steps = (("tags", ["train.tags"]), ("dataset", ["train.dataset"]),
             ("train", ["train.train", "--model-id", model_id, *train_args]),
             ("eval", ["train.eval", "--model", model_id]), ("promote", ["app.build", "--promote", model_id]))
    log_path = Path("train/runs") / model_id / "pipeline.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "TRAIN_PIPELINE": "1"}
    live = snapshot.read_pointer() or {}
    start = time.monotonic()

    with log_path.open("w") as log:
        def emit(line: str, stamp: bool = True) -> None:
            line = f"{time.strftime('%H:%M:%S')} {line}" if stamp else line
            print(line, flush=True)
            log.write(line + "\n")

        emit(f"oracle-tutor pipeline · model {model_id} · log → {log_path}", stamp=False)
        emit(f"bucket {os.environ['BUCKET']} · live snapshot {live.get('snapshot')} (model {live.get('model')})",
             stamp=False)
        failed = None
        for n, (name, step) in enumerate(steps, 1):
            emit("", stamp=False)
            emit(f"[{n}/{len(steps)}] {name} " + "─" * (70 - len(name)))
            t0 = time.monotonic()
            proc = subprocess.Popen([sys.executable, "-m", *step], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, env=env)
            assert proc.stdout is not None
            for line in proc.stdout:
                # Progress bars redraw with \r; keep only their final state.
                line = line.rstrip().rsplit("\r", 1)[-1]
                if line.strip():
                    emit("  " + line)
            took = duration(time.monotonic() - t0)
            if proc.wait():
                emit(f"[{n}/{len(steps)}] {name} FAILED after {took} (exit {proc.returncode}); {model_id} not promoted")
                failed = name
                break
            emit(f"[{n}/{len(steps)}] {name} done in {took}")

        emit("", stamp=False)
        if not failed:
            emit(f"done in {duration(time.monotonic() - start)} · {model_id} promoted", stamp=False)
            emit("next refresh run re-embeds every card with it (cron 06:00 UTC, or start `refresh` on Railway)",
                 stamp=False)
        uploaded = snapshot.has_model(model_id)
        emit(f"log: {log_path}" + (f" (also uploaded to models/{model_id}/pipeline.log)" if uploaded else ""),
             stamp=False)
    if uploaded:
        snapshot.put(f"models/{model_id}/pipeline.log", log_path.read_bytes(), "text/plain")
    if failed:
        raise SystemExit(f"{failed} failed; {model_id} not promoted")


if __name__ == "__main__":
    main()
