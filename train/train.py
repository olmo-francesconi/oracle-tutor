"""Fine-tune an embedding model on train/dataset.json.gz and upload it to the bucket as models/<model_id>/.

Run from repo root: uv run --project train python -m train.train [--base HF_ID] [--local] [--skip-fine-tune] ...

Trains on Modal (L4) by default; `--local` trains in-process on CUDA, MPS or CPU. `--skip-fine-tune` exports the base
model as-is (locally, no GPU needed). The result is MODEL_FILES (the layout app/encoder.py loads) plus meta.json,
kept under train/runs/<model_id>/ and uploaded to models/<model_id>/ when a bucket is configured. Nothing is served
until `python -m app.build --promote <model_id>`.
"""

import argparse
import gzip
import io
import json
import random
import tarfile
import time
from pathlib import Path

from app import snapshot
from train import remote


def subsample(data: dict, limit: int, rng: random.Random) -> dict:
    """At most `limit` examples, pairs and triplets in their original proportion (for smoke runs)."""
    total = len(data["pairs"]) + len(data["triplets"])
    if total <= limit:
        return data
    n_pairs = round(limit * len(data["pairs"]) / total)
    return {**data, "pairs": rng.sample(data["pairs"], n_pairs), "triplets": rng.sample(data["triplets"], limit - n_pairs)}


def model_id_for(base: str, name: str | None, now: time.struct_time) -> str:
    return f"{name or base.rstrip('/').rsplit('/', 1)[-1].lower()}-{time.strftime('%Y%m%d-%H%M', now)}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=Path("train/dataset.json.gz"))
    parser.add_argument("--base", default="sentence-transformers/all-MiniLM-L6-v2", help="any HF model id or local dir")
    parser.add_argument("--name", help="model id prefix (default: the base model's name); a UTC timestamp is appended")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--warmup", type=float, default=0.1, help="share of optimizer steps spent warming up")
    parser.add_argument("--quantize", action="store_true", help="int8 dynamic quantization of the ONNX export")
    parser.add_argument("--skip-fine-tune", action="store_true", help="export the base model as-is")
    parser.add_argument("--local", action="store_true", help="train on this machine instead of Modal")
    parser.add_argument("--limit", type=int, help="train on a random sample of N examples (smoke runs)")
    args = parser.parse_args()

    now = time.gmtime()
    model_id = model_id_for(args.base, args.name, now)
    dataset, stats = None, None
    if not args.skip_fine_tune:
        data = json.loads(gzip.decompress(args.dataset.read_bytes()))
        if args.limit:
            data = subsample(data, args.limit, random.Random(0))
        stats = {**data["stats"], "trained_pairs": len(data["pairs"]), "trained_triplets": len(data["triplets"])}
        print(f"dataset: {stats}", flush=True)
        dataset = gzip.compress(json.dumps(data, ensure_ascii=False).encode(), mtime=0)

    fit_args = (dataset, args.base, args.epochs, args.batch_size, args.lr, args.warmup, args.quantize)
    if args.local or args.skip_fine_tune:
        tar = remote.fit.local(*fit_args)
    else:
        import modal

        with modal.enable_output(), remote.app.run(environment_name=remote.ENVIRONMENT):
            tar = remote.fit.remote(*fit_args)

    out = Path("train/runs") / model_id
    with tarfile.open(fileobj=io.BytesIO(tar), mode="r:gz") as t:
        t.extractall(out, filter="data")
    meta = {
        "model_id": model_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", now),
        "base_model": args.base,
        "options": {k: getattr(args, k) for k in ("epochs", "batch_size", "lr", "warmup", "quantize",
                                                  "skip_fine_tune", "limit")},
        "trained_on": "local" if args.local or args.skip_fine_tune else "modal L4",
        "dataset": stats,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    if not snapshot.enabled():
        print(f"saved {out} (no bucket configured, not uploaded)")
        return
    snapshot.upload_model(out, model_id)
    snapshot.write_json(f"models/{model_id}/meta.json", meta)
    print(f"uploaded models/{model_id}/\nnext: python -m train.eval --model {model_id}\n"
          f"ship: python -m app.build --promote {model_id}")


if __name__ == "__main__":
    main()
