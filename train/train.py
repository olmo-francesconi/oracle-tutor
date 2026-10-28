"""Fine-tune an embedding model on train/dataset.json.gz and export it in the layout app/encoder.py loads.

Run from repo root: uv run --project train python -m train.train [--push user/repo]

The output dir holds the PyTorch weights (to fine-tune further) plus onnx/model.onnx, tokenizer.json and
sentence_bert_config.json, so `MODEL_DIR=<out>` serves it directly and `python -m train.eval --model <out>` scores it.
"""

import argparse
import gzip
import json
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("train/dataset.json.gz"))
    parser.add_argument("--base", default="sentence-transformers/all-MiniLM-L6-v2", help="HF model id or local dir")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--out", type=Path, default=Path("train/runs") / time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--push", metavar="REPO", help="upload the result to this Hugging Face Hub model repo")
    args = parser.parse_args()

    import torch
    from datasets import Dataset, DatasetDict
    from sentence_transformers import (
        SentenceTransformer,
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
        losses,
    )
    from sentence_transformers.training_args import BatchSamplers

    data = json.loads(gzip.decompress(args.dataset.read_bytes()))
    print(f"dataset: {data['stats']}")
    # Two datasets because a column set is per dataset: (anchor, positive) relies on in-batch negatives only,
    # (anchor, positive, negative) also scores the mined hard negative. Each batch is drawn from one of them.
    train_dataset = DatasetDict({
        name: Dataset.from_dict(dict(zip(cols, map(list, zip(*data[name])))))
        for name, cols in (("pairs", ("anchor", "positive")), ("triplets", ("anchor", "positive", "negative")))
        if data[name]
    })

    model = SentenceTransformer(args.base)
    training_args = SentenceTransformerTrainingArguments(
        output_dir=str(args.out / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        learning_rate=args.lr,
        # Warmup is a share of optimizer steps. v2 once counted it in examples, which spent 53% of a run ramping up.
        warmup_ratio=0.1,
        fp16=torch.cuda.is_available(),
        # The same text often sits in several rows ("mana dork" anchors 600 of them, `Flying.` positives many tags).
        # Two such rows in one batch make each other's positive a false negative for MNRL.
        batch_sampler=BatchSamplers.NO_DUPLICATES,
        save_strategy="epoch",
        save_total_limit=1,
        logging_steps=100,
        report_to="none",
    )
    loss = losses.MultipleNegativesRankingLoss(model)
    SentenceTransformerTrainer(model=model, args=training_args, train_dataset=train_dataset, loss=loss).train()

    out = args.out / "model"
    model.save_pretrained(str(out))
    SentenceTransformer(str(out), backend="onnx").save_pretrained(str(out))
    print(f"saved {out}")

    if args.push:
        from huggingface_hub import HfApi

        api = HfApi()
        api.create_repo(args.push, exist_ok=True)
        commit = api.upload_folder(repo_id=args.push, folder_path=str(out), commit_message=f"train {args.out.name}")
        print(f"pushed {args.push}; pin MODEL_REV={commit.oid}")


if __name__ == "__main__":
    main()
