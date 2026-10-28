"""The two GPU jobs, run on Modal (L4) or in-process with `.local()`.

Imports nothing else from this repo, so the containers need no project dependencies (Modal ships the `train` package's
.py files). Inputs and outputs are plain bytes and
strings, so bucket credentials never leave the dev machine (train/llm.py and train/train.py do all bucket I/O).
Modal auth: ~/.modal.toml or MODAL_TOKEN_ID / MODAL_TOKEN_SECRET.
"""

import io
import tarfile
import tempfile
from pathlib import Path

import modal

ENVIRONMENT = "oracle-tutor"
# Exactly what app/encoder.py loads (app.snapshot.MODEL_FILES); this file cannot import it.
MODEL_FILES = ("onnx/model.onnx", "tokenizer.json", "sentence_bert_config.json")

# L4 as in v2; A10G (also 24 GB) when Modal has no L4 free, which happened for 15+ minutes during development.
GPU = ["L4", "A10G"]

app = modal.App("oracle-tutor-train")
# Base models and the LLM's ~10 GB of weights are downloaded once per volume, not per run.
hf_cache = modal.Volume.from_name("oracle-tutor-hf-cache", create_if_missing=True)
_volumes = {"/root/.cache/huggingface": hf_cache}
llm_image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("vllm==0.32.0")
    # FlashInfer's sampler JIT-compiles with nvcc, which debian_slim lacks; the PyTorch sampler is fine for this load.
    # Still required on vLLM 0.32 (checked 2026-10-28).
    .env({"VLLM_USE_FLASHINFER_SAMPLER": "0"})
)
train_image = (
    modal.Image.debian_slim(python_version="3.12")
    # Same versions as train/uv.lock, so a Modal run and a --local run train identically.
    .uv_pip_install("sentence-transformers==6.2.0", "transformers==5.21.0", "torch==2.15.0", "accelerate==1.15.0",
                    "datasets==5.1.0", "onnx==1.23.2", "onnxscript==0.7.2", "onnxruntime==1.31.1")
)


@app.function(gpu=GPU, image=llm_image, volumes=_volumes, timeout=8 * 3600)
def generate(conversations: list[list[dict]], model: str, temperature: float, max_tokens: int) -> list[str]:
    """One completion per chat conversation, in order."""
    from vllm import LLM, SamplingParams

    llm = LLM(model=model, trust_remote_code=True, gpu_memory_utilization=0.9, max_model_len=4096)
    # chat() applies the model's own template. v2 once handed vLLM bare strings, which made an instruct model do raw
    # completion and produced 4,000-character repetition loops.
    outputs = llm.chat(conversations, SamplingParams(temperature=temperature, max_tokens=max_tokens))
    return [o.outputs[0].text if o.outputs else "" for o in outputs]


def export_onnx(model, path: Path) -> None:
    """Export the transformer alone: app/encoder.py reads token embeddings (output 0) and pools/normalizes itself.

    Done with torch directly rather than sentence-transformers' `backend="onnx"`, whose optimum-onnx dependency caps
    transformers below 5 and with it the whole training stack.
    """
    import torch

    transformer = model[0].auto_model.cpu().eval()
    names = ["input_ids", "attention_mask", "token_type_ids"]
    sample = model.tokenizer(["export sample text"], return_tensors="pt")
    batch, seq = torch.export.Dim("batch"), torch.export.Dim("sequence")
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        transformer,
        kwargs={n: sample[n] for n in names},
        f=str(path),
        input_names=names,
        output_names=["token_embeddings"],
        dynamic_shapes={n: {0: batch, 1: seq} for n in names},
        dynamo=True,
        external_data=False,
    )


@app.function(gpu=GPU, image=train_image, volumes=_volumes, timeout=8 * 3600)
def fit(dataset: bytes | None, base: str, epochs: int, batch_size: int, lr: float, warmup: float,
        quantize: bool) -> bytes:
    """Fine-tune `base` on train/dataset.json.gz bytes (None = export the base model as-is) and return a .tar.gz of
    MODEL_FILES."""
    import gzip
    import json

    import torch
    from datasets import Dataset, DatasetDict
    from sentence_transformers import (
        SentenceTransformer,
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
        losses,
    )
    from sentence_transformers.training_args import BatchSamplers

    model = SentenceTransformer(base)
    with tempfile.TemporaryDirectory() as tmp:
        if dataset is not None:
            data = json.loads(gzip.decompress(dataset))
            # Two datasets because a column set is per dataset: (anchor, positive) relies on in-batch negatives only,
            # (anchor, positive, negative) also scores the mined hard negative. Each batch is drawn from one of them.
            train_dataset = DatasetDict({
                name: Dataset.from_dict(dict(zip(cols, map(list, zip(*data[name])))))
                for name, cols in (("pairs", ("anchor", "positive")), ("triplets", ("anchor", "positive", "negative")))
                if data[name]
            })
            args = SentenceTransformerTrainingArguments(
                output_dir=f"{tmp}/checkpoints",
                num_train_epochs=epochs,
                per_device_train_batch_size=batch_size,
                learning_rate=lr,
                # A share of optimizer steps. v2 once counted it in examples, which spent 53% of a run ramping up.
                warmup_ratio=warmup,
                fp16=torch.cuda.is_available(),
                # The same text often sits in several rows ("mana dork" anchors 600, `Flying.` positives many tags);
                # two such rows in one batch make each other's positive a false negative for MNRL.
                batch_sampler=BatchSamplers.NO_DUPLICATES,
                save_strategy="no",
                logging_steps=100,
                report_to="none",
            )
            loss = losses.MultipleNegativesRankingLoss(model)
            SentenceTransformerTrainer(model=model, args=args, train_dataset=train_dataset, loss=loss).train()

        out = Path(tmp) / "model"
        model.save_pretrained(str(out))
        export_onnx(model, out / "onnx" / "model.onnx")
        if quantize:
            from onnxruntime.quantization import QuantType, quantize_dynamic

            onnx = out / "onnx" / "model.onnx"
            quantize_dynamic(str(onnx), str(onnx.with_suffix(".int8.onnx")), weight_type=QuantType.QInt8)
            onnx.with_suffix(".int8.onnx").replace(onnx)

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name in MODEL_FILES:
                tar.add(out / name, arcname=name)
        return buf.getvalue()
