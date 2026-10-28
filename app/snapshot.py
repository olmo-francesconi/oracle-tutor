"""Bucket layout shared by the refresh worker (writes) and the web service (reads).

    models/<model_id>/{onnx/model.onnx, tokenizer.json, sentence_bert_config.json, meta.json}
    snapshots/<snapshot_id>/{cards.json.gz, vectors.npz}
    current.json  {"snapshot", "model", "scryfall"}   what web serves
    model.json    {"model", "promoted_at"}            what the refresh worker should embed with next
    training/llm_queries.jsonl.gz                     LLM query cache (train/llm.py)

`current.json` names the model and the data together, so a swap can never pair vectors with the wrong encoder.
It is written last: a failed refresh leaves the live pointer untouched. `model.json` is written only by a promote;
the worker re-embeds everything when it differs from `current.json`'s model.
Credentials use Railway's bucket variable names: BUCKET, ENDPOINT, ACCESS_KEY_ID, SECRET_ACCESS_KEY, REGION.
"""

import json
import os
from pathlib import Path

import boto3
from botocore.config import Config

MODEL_FILES = ("onnx/model.onnx", "tokenizer.json", "sentence_bert_config.json")
DATA_FILES = ("cards.json.gz", "vectors.npz")
POINTER = "current.json"
PROMOTED = "model.json"


def enabled() -> bool:
    return bool(os.environ.get("BUCKET"))


def _client():
    # New Railway buckets are virtual-hosted; older ones and local MinIO need path style.
    style = "path" if os.environ.get("BUCKET_PATH_STYLE") else "virtual"
    return boto3.client(
        "s3",
        endpoint_url=os.environ["ENDPOINT"],
        aws_access_key_id=os.environ["ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["SECRET_ACCESS_KEY"],
        region_name=os.environ.get("REGION", "auto"),
        config=Config(s3={"addressing_style": style}),
    )


def get(key: str) -> bytes | None:
    client = _client()
    try:
        return client.get_object(Bucket=os.environ["BUCKET"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return None


def put(key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
    _client().put_object(Bucket=os.environ["BUCKET"], Key=key, Body=body, ContentType=content_type)


def read_json(key: str) -> dict | None:
    body = get(key)
    return None if body is None else json.loads(body)


def write_json(key: str, value: dict) -> None:
    put(key, json.dumps(value, indent=1).encode(), "application/json")


def read_pointer() -> dict | None:
    return read_json(POINTER)


def write_pointer(pointer: dict) -> None:
    write_json(POINTER, pointer)


def read_promoted() -> dict | None:
    return read_json(PROMOTED)


def write_promoted(promoted: dict) -> None:
    write_json(PROMOTED, promoted)


def _download(prefix: str, names: tuple[str, ...], dest: Path) -> Path:
    if all((dest / n).exists() for n in names):
        return dest
    client, bucket = _client(), os.environ["BUCKET"]
    for name in names:
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(bucket, f"{prefix}/{name}", str(target) + ".part")
        os.replace(str(target) + ".part", target)
    return dest


def _upload(src: Path, prefix: str, names: tuple[str, ...]) -> None:
    client, bucket = _client(), os.environ["BUCKET"]
    for name in names:
        client.upload_file(str(src / name), bucket, f"{prefix}/{name}")


def has_model(model_id: str) -> bool:
    resp = _client().list_objects_v2(Bucket=os.environ["BUCKET"], Prefix=f"models/{model_id}/{MODEL_FILES[0]}")
    return resp.get("KeyCount", 0) > 0


def download_model(model_id: str, cache: Path) -> Path:
    return _download(f"models/{model_id}", MODEL_FILES, cache / "models" / model_id)


def upload_model(model_dir: Path, model_id: str) -> None:
    _upload(model_dir, f"models/{model_id}", MODEL_FILES)


def download_data(snapshot_id: str, cache: Path) -> Path:
    return _download(f"snapshots/{snapshot_id}", DATA_FILES, cache / "snapshots" / snapshot_id)


def upload_data(data_dir: Path, snapshot_id: str) -> None:
    _upload(data_dir, f"snapshots/{snapshot_id}", DATA_FILES)


def prune_snapshots(keep: int) -> None:
    """Delete all but the newest `keep` snapshots (ids are UTC timestamps, so they sort by age)."""
    client, bucket = _client(), os.environ["BUCKET"]
    pages = client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="snapshots/")
    keys = [o["Key"] for page in pages for o in page.get("Contents", [])]
    ids = sorted({k.split("/")[1] for k in keys})
    stale = set(ids[:-keep])
    for key in keys:
        if key.split("/")[1] in stale:
            client.delete_object(Bucket=bucket, Key=key)
