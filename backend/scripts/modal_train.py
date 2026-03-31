"""Modal remote training script for Oracle Tutor.

Self-contained — no ot_backend import, no DB access.
All data comes from the pre-exported training-dataset.json.

Usage:
    # 1. Export dataset from local DB
    cd backend
    uv run python -m ot_backend.embed.pipeline --export-dataset data/training-dataset.json

    # 2. Run remote training (~15-20 min on T4)
    modal run --env oracle-tutor scripts/modal_train.py

    # 3. Unzip artifacts into SEMANTIC_MODEL_PATH
    unzip data/semantic/onnx-model.zip -d /path/to/SEMANTIC_MODEL_PATH

    # 4. Load pre-computed embeddings into DB (no local inference needed)
    uv run python -m ot_backend.embed.pipeline \\
        --load-embeddings /path/to/SEMANTIC_MODEL_PATH/embeddings.npz

Prerequisites:
    pip install modal && modal setup
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import modal

# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "sentence-transformers>=3.3.1",
        "optimum[onnxruntime]",
        "accelerate>=1.1.0",
        "datasets>=3.0.0",
        "numpy>=1.26.0",
    )
)

# Persist the HuggingFace model cache across runs (~90 MB base model)
hf_cache = modal.Volume.from_name("oracle-tutor-hf-cache", create_if_missing=True)

app = modal.App("oracle-tutor-train")

# ---------------------------------------------------------------------------
# Remote function
# ---------------------------------------------------------------------------

@app.function(
    gpu="T4",
    timeout=3600,
    image=image,
    volumes={"/root/.cache/huggingface": hf_cache},
)
def train(
    dataset_json: bytes,
    base_model: str,
    epochs: int,
    batch_size: int,
) -> bytes:
    import json
    import os
    import warnings

    import numpy as np

    os.environ["WANDB_MODE"] = "disabled"
    warnings.filterwarnings("ignore", category=FutureWarning, module="sentence_transformers")

    from sentence_transformers import InputExample, SentenceTransformer, losses
    from torch.utils.data import DataLoader

    # -- Load dataset from JSON bytes ------------------------------------------

    payload = json.loads(dataset_json)
    face_texts: dict[tuple[str, int], str] = {
        (r["oracle_id"], r["face_ix"]): r["text"] for r in payload["face_texts"]
    }
    pair_ids = [
        ((l[0], l[1]), (r[0], r[1])) for l, r in payload["pair_ids"]
    ]
    direct_text_pairs: list[tuple[str, str]] = [
        (a, b) for a, b in payload.get("direct_text_pairs", [])
    ]
    template_query_examples = int(payload.get("template_query_examples", 0))
    print(
        f"Dataset loaded. faces={len(face_texts):,} "
        f"pairs={len(pair_ids):,} "
        f"direct={len(direct_text_pairs):,} "
        f"template_queries={template_query_examples:,}"
    )

    # -- Training --------------------------------------------------------------

    class _Dataset:
        def __init__(self) -> None:
            self._pairs = pair_ids
            self._direct = direct_text_pairs
            self._n = len(pair_ids)

        def __len__(self) -> int:
            return self._n + len(self._direct)

        def __getitem__(self, i: int) -> InputExample:
            if i < self._n:
                l, r = self._pairs[i]
                return InputExample(texts=[face_texts[l], face_texts[r]])
            a, b = self._direct[i - self._n]
            return InputExample(texts=[a, b])

    print(f"Loading base model: {base_model}")
    model = SentenceTransformer(base_model)

    dataset = _Dataset()
    dataloader = DataLoader(dataset, shuffle=False, batch_size=batch_size)
    loss_fn = losses.MultipleNegativesRankingLoss(model)

    total = len(dataset)
    warmup_steps = max(100, total // 20)
    print(f"Training. examples={total:,} epochs={epochs} batch={batch_size} warmup={warmup_steps}")

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "run"
        run_dir.mkdir()

        model.fit(
            train_objectives=[(dataloader, loss_fn)],
            epochs=epochs,
            warmup_steps=warmup_steps,
            show_progress_bar=True,
            checkpoint_path=str(run_dir / "checkpoints"),
        )
        print("Training complete.")

        # -- Save PyTorch model ------------------------------------------------
        pytorch_path = run_dir / "pytorch"
        pytorch_path.mkdir()
        model.save(str(pytorch_path))
        print("PyTorch model saved.")

        # -- Export ONNX -------------------------------------------------------
        # Save to models/onnx/ — this becomes SEMANTIC_MODEL_PATH.
        # sentence-transformers writes tokenizer files at root + onnx/model.onnx inside.
        artifact_root = run_dir / "artifacts"
        models_onnx = artifact_root / "models" / "onnx"
        models_onnx.mkdir(parents=True)
        onnx_model = SentenceTransformer(
            str(pytorch_path),
            backend="onnx",
            model_kwargs={
                "provider": "CPUExecutionProvider",
                "export": True,
                "file_name": "onnx/model.onnx",
            },
            local_files_only=True,
        )
        onnx_model.save(str(models_onnx))
        print("ONNX model exported.")

        # -- Save PyTorch checkpoint into models/pytorch/ ----------------------
        shutil.copytree(str(pytorch_path), str(artifact_root / "models" / "pytorch"))

        # -- Compute embeddings ------------------------------------------------
        face_keys = sorted(face_texts.keys())
        texts = [face_texts[k] for k in face_keys]
        oracle_ids_arr = np.array([k[0] for k in face_keys])
        face_ixs_arr = np.array([k[1] for k in face_keys], dtype=np.int32)

        print(f"Computing embeddings for {len(texts):,} faces ...")
        embeddings = model.encode(
            texts,
            batch_size=256,
            normalize_embeddings=True,
            show_progress_bar=True,
        ).astype(np.float32)
        print(f"Embeddings done. shape={embeddings.shape}")

        embeddings_dir = artifact_root / "embeddings"
        embeddings_dir.mkdir()
        np.savez_compressed(
            str(embeddings_dir / "embeddings.npz"),
            oracle_ids=oracle_ids_arr,
            face_ixs=face_ixs_arr,
            embeddings=embeddings,
        )

        # -- Zip artifact_root -------------------------------------------------
        # Zip structure:
        #   models/onnx/   — set SEMANTIC_MODEL_PATH here
        #   models/pytorch/
        #   embeddings/embeddings.npz
        zip_base = Path(tmp) / "onnx-model"
        shutil.make_archive(str(zip_base), "zip", str(artifact_root))
        return zip_base.with_suffix(".zip").read_bytes()


# ---------------------------------------------------------------------------
# Local entrypoint
# ---------------------------------------------------------------------------

@app.local_entrypoint()
def main(
    dataset_path: str = "data/training-dataset.json",
    output: str = "",
    base_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    epochs: int = 2,
    batch_size: int = 64,
    no_unpack: bool = False,
) -> None:
    import os
    import zipfile
    from datetime import datetime, timezone

    run_ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = output or f"data/semantic/oracle-tutor-model-{run_ts}.zip"

    src = Path(dataset_path)
    if not src.exists():
        raise FileNotFoundError(
            f"Dataset not found: {src}\n"
            "Run first: uv run python -m ot_backend.embed.pipeline --export-dataset <path>"
        )

    print(f"Uploading dataset ({src.stat().st_size / 1e6:.1f} MB) ...")
    result: bytes = train.remote(
        src.read_bytes(),
        base_model,
        epochs,
        batch_size,
    )

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result)
    print(f"Saved {len(result) / 1e6:.1f} MB → {out}")

    if no_unpack:
        print()
        print("To unpack manually:")
        print(f"  unzip {out} -d data/semantic/runs/{run_ts}")
        print(f"  cd data/semantic/runs && ln -sfn {run_ts} latest")
        return

    runs_dir = out.parent / "runs"
    artifact_dir = runs_dir / run_ts
    artifact_dir.mkdir(parents=True, exist_ok=True)

    print(f"Unpacking to {artifact_dir} ...")
    with zipfile.ZipFile(out) as zf:
        zf.extractall(artifact_dir)

    latest = runs_dir / "latest"
    latest.unlink(missing_ok=True)
    os.symlink(run_ts, latest)

    print(f"Linked: {latest} → {run_ts}")
    print()
    print("Next steps:")
    print(f"  export SEMANTIC_MODEL_PATH={latest}/models/onnx")
    print(f"  uv run python -m ot_backend.embed.pipeline --load-embeddings")
