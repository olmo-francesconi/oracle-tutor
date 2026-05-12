"""Modal remote training module for Oracle Tutor.

`backend/scripts/train_model.py` imports this module and dispatches
`train.remote(...)` (or `.local(...)` when fine-tuning is skipped). All
training inputs are passed as bytes so the Modal side stays DB-independent.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import tempfile
import warnings
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, override

try:
    import modal
except ModuleNotFoundError:  # pragma: no cover - exercised in local test envs without modal installed
    class _DummyImage:
        @staticmethod
        def debian_slim(*, python_version: str) -> "_DummyImage":
            del python_version
            return _DummyImage()

        def pip_install(self, *packages: str) -> "_DummyImage":
            del packages
            return self

    class _DummyVolume:
        @staticmethod
        def from_name(name: str, *, create_if_missing: bool) -> "_DummyVolume":
            del name, create_if_missing
            return _DummyVolume()

    class _DummyApp:
        def __init__(self, _name: str) -> None:
            pass

        def function(self, **_kwargs: object) -> Any:
            def decorator(fn: Any) -> Any:
                fn.remote = fn
                return fn

            return decorator

        @contextmanager
        def run(self, **_kwargs: object) -> Any:
            yield

    class _DummyModal:
        Image = _DummyImage
        Volume = _DummyVolume
        App = _DummyApp

    modal = _DummyModal()

from ..core.config import (
    semantic_llm_max_faces,
    semantic_llm_max_queries_per_face,
    semantic_llm_max_tokens,
    semantic_llm_model_name,
    semantic_llm_temperature,
)
from .dataset_service import TrainingDatasetState, load_training_dataset_bytes, serialize_training_dataset
from .query_gen import generate_template_queries
from .text_prep import EMPTY_ORACLE_TOKEN
from .train_options import (
    TRAIN_AUGMENTATION_LLM_QUERIES,
    TRAIN_AUGMENTATION_TAG_DESCRIPTIONS,
    TRAIN_AUGMENTATION_TAG_PAIRS,
    TRAIN_AUGMENTATION_TEMPLATE_QUERIES,
    parse_train_augmentation_mode,
)

image: Any = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "sentence-transformers>=3.3.1",
        "optimum[onnxruntime]",
        "accelerate>=1.1.0",
        "datasets>=3.0.0",
        "numpy>=1.26.0",
        "vllm>=0.8.5",
    )
)

hf_cache: Any = modal.Volume.from_name("oracle-tutor-hf-cache", create_if_missing=True)
app: Any = modal.App("oracle-tutor-train")

_LLM_SYSTEM_PROMPT_TEMPLATE = """\
You are a search query generator for a Magic: The Gathering card database.
When given card oracle text, output exactly {max_queries} short search queries that a player might type to find cards with this effect.

Rules:
- Each query must be 2-8 words, all lowercase
- Use Magic: The Gathering terminology where appropriate (e.g. "draw a card", "counter a spell", "enters the battlefield", "tap for mana")
- Describe what the card DOES — its mechanic or effect — not its name
- Output one query per line, nothing else: no numbering, no bullets, no explanation
- Focus on the most distinctive or searchable thing the card does"""
_NO_THINK_SUFFIX = " /no_think"
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_LIST_PREFIX = re.compile(r"^[\s\-\*•\d\.\)]+")


def _parse_face_key_rows(rows: list[list[object]] | list[tuple[object, object]]) -> list[tuple[str, int]]:
    return [(str(oracle_id), int(str(face_ix))) for oracle_id, face_ix in rows]


def _parse_llm_queries(raw_text: str, *, max_queries: int) -> list[str]:
    text = _THINK_BLOCK.sub("", raw_text).strip()
    deduped: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        compact = _LIST_PREFIX.sub("", line).strip().rstrip(".,;:").lower()
        if not compact:
            continue
        word_count = len(compact.split())
        if word_count < 2 or word_count > 8 or compact in seen:
            continue
        seen.add(compact)
        deduped.append(compact)
        if len(deduped) >= max_queries:
            break
    return deduped


def _build_llm_prompt(face: dict[str, str], *, max_queries: int) -> str:
    oracle_text = face.get("oracle_text", "").strip() or face.get("text", "").strip()
    return (
        f"{_LLM_SYSTEM_PROMPT_TEMPLATE.format(max_queries=max_queries)}"
        f"\n\nOracle text:\n{oracle_text}{_NO_THINK_SUFFIX}"
    )


def _select_llm_gap_faces(
    face_rows: list[dict[str, str]],
    *,
    min_template_coverage: int,
    max_faces: int,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in face_rows:
        raw_oracle_text = row.get("oracle_text", "").strip()
        normalized_text = row.get("text", "").strip()
        if not raw_oracle_text or normalized_text == EMPTY_ORACLE_TOKEN:
            continue
        if len(generate_template_queries(row["text"])) >= min_template_coverage:
            continue
        selected.append(row)
        if len(selected) >= max_faces:
            break
    return selected


def _generate_llm_query_pairs(face_rows: list[dict[str, str]], *, llm_config: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    if not face_rows:
        return []

    try:
        from vllm import LLM, SamplingParams  # pyright: ignore[reportMissingImports]
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("vLLM is required for llm_queries augmentation inside Modal.") from exc

    llm_config = llm_config or {}
    max_faces = int(llm_config.get("max_faces", semantic_llm_max_faces()))
    min_template_coverage = int(llm_config.get("min_template_coverage", 2))
    queries_per_face = int(llm_config.get("max_queries_per_face", semantic_llm_max_queries_per_face()))
    selected_rows = _select_llm_gap_faces(
        face_rows,
        min_template_coverage=min_template_coverage,
        max_faces=max_faces,
    )
    print(
        f"LLM augmentation selected {len(selected_rows):,} gap faces "
        f"from {len(face_rows):,} total (min_template_coverage={min_template_coverage})."
    )
    if not selected_rows:
        return []

    prompts = [_build_llm_prompt(row, max_queries=queries_per_face) for row in selected_rows]
    llm = LLM(
        model=str(llm_config.get("model_name", semantic_llm_model_name())),
        trust_remote_code=True,
        gpu_memory_utilization=float(os.getenv("SEMANTIC_LLM_GPU_MEMORY_UTILIZATION", "0.9")),
        max_model_len=int(os.getenv("SEMANTIC_LLM_MAX_MODEL_LEN", "4096")),
    )
    sampling_params = SamplingParams(
        temperature=float(llm_config.get("temperature", semantic_llm_temperature())),
        max_tokens=int(llm_config.get("max_tokens", semantic_llm_max_tokens())),
    )
    outputs = llm.generate(prompts, sampling_params)

    direct_text_pairs: list[tuple[str, str]] = []
    for face, output in zip(selected_rows, outputs, strict=False):
        text = ""
        if output.outputs:
            text = output.outputs[0].text
        queries = _parse_llm_queries(text, max_queries=queries_per_face)
        for query in queries:
            direct_text_pairs.append((query, face["text"]))
    print(f"LLM query pairs built. count={len(direct_text_pairs):,}")
    return direct_text_pairs


def _build_dataset_state(
    build_payload: dict[str, Any],
    *,
    augmentation_mode: str,
    llm_config: dict[str, Any] | None = None,
) -> tuple[TrainingDatasetState, dict[str, object]]:
    if int(build_payload.get("version", 0)) != 1:
        raise ValueError(f"Unsupported training build payload version: {build_payload.get('version')!r}.")

    selected_augmentations = set(parse_train_augmentation_mode(augmentation_mode))
    raw_features = build_payload.get("features")
    feature_flags: dict[str, Any] = raw_features if isinstance(raw_features, dict) else {}
    raw_options = build_payload.get("options")
    options: dict[str, Any] = raw_options if isinstance(raw_options, dict) else {}
    face_rows = list(build_payload.get("faces") or [])

    face_texts: dict[tuple[str, int], str] = {}
    face_names: dict[tuple[str, int], str] = {}
    normalized_faces: list[dict[str, str]] = []
    for row in face_rows:
        face_key = (str(row["oracle_id"]), int(row["face_ix"]))
        normalized_text = str(row["text"])
        face_texts[face_key] = normalized_text
        face_names[face_key] = str(row.get("name") or "")
        normalized_faces.append(
            {
                "oracle_id": face_key[0],
                "face_ix": str(face_key[1]),
                "oracle_text": str(row.get("oracle_text") or ""),
                "text": normalized_text,
            }
        )

    self_pair_ids = [(face_key, face_key) for face_key, text in face_texts.items() if text.strip()]

    rng = random.Random(0)
    tag_pair_ids: list[tuple[tuple[str, int], tuple[str, int]]] = []
    if feature_flags.get("tag_pairs") and TRAIN_AUGMENTATION_TAG_PAIRS in selected_augmentations:
        max_pairs_per_tag = int(options.get("max_tag_pairs_per_tag", 50))
        min_group_size = int(options.get("max_tag_pair_group_size", 5))
        raw_tag_to_face_ids = build_payload.get("tag_to_face_ids")
        tag_to_face_ids: dict[str, Any] = raw_tag_to_face_ids if isinstance(raw_tag_to_face_ids, dict) else {}
        for raw_face_ids in tag_to_face_ids.values():
            face_ids = _parse_face_key_rows(list(raw_face_ids))
            if len(face_ids) < min_group_size:
                continue
            shuffled = list(face_ids)
            rng.shuffle(shuffled)
            for left, right in list(zip(shuffled[::2], shuffled[1::2]))[:max_pairs_per_tag]:
                if left[0] != right[0] and face_texts.get(left) and face_texts.get(right):
                    tag_pair_ids.append((left, right))

    direct_text_pairs: list[tuple[str, str]] = []
    if feature_flags.get("tag_descriptions") and TRAIN_AUGMENTATION_TAG_DESCRIPTIONS in selected_augmentations:
        max_desc_pairs_per_tag = int(options.get("max_tag_desc_pairs_per_tag", 50))
        raw_tag_to_desc = build_payload.get("tag_to_desc")
        tag_to_desc: dict[str, Any] = raw_tag_to_desc if isinstance(raw_tag_to_desc, dict) else {}
        raw_tag_to_desc_faces = build_payload.get("tag_to_desc_faces")
        tag_to_desc_faces: dict[str, Any] = raw_tag_to_desc_faces if isinstance(raw_tag_to_desc_faces, dict) else {}
        for tag_name, raw_face_ids in tag_to_desc_faces.items():
            anchor = str(tag_to_desc.get(tag_name) or "").strip()
            if not anchor:
                continue
            face_ids = _parse_face_key_rows(list(raw_face_ids))
            if not face_ids:
                continue
            sampled = list(face_ids)
            rng.shuffle(sampled)
            for face_key in sampled[:max_desc_pairs_per_tag]:
                direct_text_pairs.append((anchor, face_texts[face_key]))

    template_query_examples = 0
    if feature_flags.get("template_queries") and TRAIN_AUGMENTATION_TEMPLATE_QUERIES in selected_augmentations:
        for face_key, oracle_text in face_texts.items():
            for query in generate_template_queries(oracle_text):
                direct_text_pairs.append((query, oracle_text))
                template_query_examples += 1

    llm_pairs: list[tuple[str, str]] = []
    if feature_flags.get("llm_queries") and TRAIN_AUGMENTATION_LLM_QUERIES in selected_augmentations:
        llm_pairs = _generate_llm_query_pairs(normalized_faces, llm_config=llm_config)
        direct_text_pairs.extend(llm_pairs)

    rng.shuffle(tag_pair_ids)
    rng.shuffle(direct_text_pairs)
    metadata = dict(build_payload.get("metadata") or {})
    metadata["augmentation"] = {
        "mode": augmentation_mode,
        "template_query_examples": template_query_examples,
        "llm_query_examples": len(llm_pairs),
        **({"llm_model": str((llm_config or {}).get("model_name", semantic_llm_model_name()))} if llm_pairs else {}),
    }
    return (
        TrainingDatasetState(
            face_texts=face_texts,
            face_names=face_names,
            pair_ids=self_pair_ids + tag_pair_ids,
            direct_text_pairs=direct_text_pairs,
            simcse_examples=len(self_pair_ids),
            tag_pair_examples=len(tag_pair_ids),
            tag_desc_pair_examples=max(len(direct_text_pairs) - template_query_examples - len(llm_pairs), 0),
            template_query_examples=template_query_examples,
            llm_query_examples=len(llm_pairs),
        ),
        metadata,
    )


@app.function(
    gpu="L4",
    timeout=3600,
    image=image,
    volumes={"/root/.cache/huggingface": hf_cache},
)
def build_dataset(
    training_payload_json: bytes,
    augmentation_mode: str,
    llm_config: dict[str, Any] | None = None,
) -> bytes:
    build_payload = json.loads(training_payload_json)
    dataset_state, dataset_metadata = _build_dataset_state(
        build_payload,
        augmentation_mode=augmentation_mode,
        llm_config=llm_config,
    )
    dataset_json = serialize_training_dataset(dataset_state, metadata=dataset_metadata)
    print(
        f"Dataset built. faces={len(dataset_state.face_texts):,} "
        f"pairs={len(dataset_state.pair_ids):,} "
        f"direct={len(dataset_state.direct_text_pairs):,} "
        f"template_queries={dataset_state.template_query_examples:,} "
        f"llm_queries={dataset_state.llm_query_examples:,}"
    )
    return dataset_json


@app.function(
    gpu="L4",
    timeout=3600,
    image=image,
    volumes={"/root/.cache/huggingface": hf_cache},
)
def train(
    dataset_json: bytes,
    eval_queries_json: bytes,
    base_model: str,
    epochs: int,
    batch_size: int,
    augmentation_mode: str,
    skip_fine_tune: bool = False,
) -> bytes:
    import numpy as np
    from sentence_transformers import InputExample, SentenceTransformer, losses
    from torch.utils.data import DataLoader, Dataset

    os.environ["WANDB_MODE"] = "disabled"
    warnings.filterwarnings("ignore", category=FutureWarning, module="sentence_transformers")

    dataset_payload = json.loads(dataset_json)
    dataset_state = load_training_dataset_bytes(dataset_json)
    dataset_metadata = dataset_payload.get("metadata") if isinstance(dataset_payload.get("metadata"), dict) else {}
    face_texts = dataset_state.face_texts
    face_names = dataset_state.face_names
    pair_ids = dataset_state.pair_ids
    direct_text_pairs = dataset_state.direct_text_pairs
    print(f"Dataset loaded. faces={len(face_texts):,} pairs={len(pair_ids):,} direct={len(direct_text_pairs):,}")

    eval_queries_payload = json.loads(eval_queries_json)
    if not isinstance(eval_queries_payload, dict) or not isinstance(eval_queries_payload.get("queries"), list):
        raise ValueError("Eval queries payload must be a JSON object with a 'queries' list.")

    class _Dataset(Dataset[InputExample]):
        def __init__(self) -> None:
            self._pairs = pair_ids
            self._direct = direct_text_pairs
            self._n = len(pair_ids)

        def __len__(self) -> int:
            return self._n + len(self._direct)

        @override
        def __getitem__(self, i: int) -> InputExample:
            if i < self._n:
                left_key, right_key = self._pairs[i]
                return InputExample(texts=[face_texts[left_key], face_texts[right_key]])
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

        if skip_fine_tune:
            print("Skipping fine-tune inside Modal; packaging base model only.")
        else:
            model.fit(
                train_objectives=[(dataloader, loss_fn)],
                epochs=epochs,
                warmup_steps=warmup_steps,
                show_progress_bar=True,
                checkpoint_path=str(run_dir / "checkpoints"),
            )
            print("Training complete.")

        pytorch_path = run_dir / "pytorch"
        pytorch_path.mkdir()
        model.save(str(pytorch_path))
        print("PyTorch model saved.")

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

        shutil.copytree(str(pytorch_path), str(artifact_root / "models" / "pytorch"))

        ordered_face_rows = sorted(face_texts.items())
        embed_batch_size = max(256, batch_size)
        embeddings = np.asarray(
            model.encode(
                [text for (_face_key, text) in ordered_face_rows],
                batch_size=embed_batch_size,
                normalize_embeddings=True,
                show_progress_bar=True,
            ),
            dtype=np.float32,
        )
        embeddings_dir = artifact_root / "embeddings"
        embeddings_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            embeddings_dir / "embeddings.npz",
            oracle_ids=np.asarray([oracle_id for (oracle_id, _face_ix), _text in ordered_face_rows]),
            face_ixs=np.asarray([face_ix for (_oracle_id, face_ix), _text in ordered_face_rows], dtype=np.int32),
            embeddings=embeddings,
        )
        print("Embedding archive saved.")

        oracle_ids = [oracle_id for (oracle_id, _face_ix), _text in ordered_face_rows]
        face_ixs = [face_ix for (_oracle_id, face_ix), _text in ordered_face_rows]
        top_k = 5
        query_results: list[dict[str, object]] = []
        top1_hits = 0
        top3_hits = 0
        top5_hits = 0
        reciprocal_rank_sum = 0.0
        for item in eval_queries_payload["queries"]:
            query = str(item.get("query") or "").strip()
            expected_cards = [str(name) for name in item.get("expected_cards", []) if str(name).strip()]
            expected_lookup = {name.casefold() for name in expected_cards}
            query_embedding = np.asarray(
                model.encode([query], normalize_embeddings=True, show_progress_bar=False),
                dtype=np.float32,
            )[0]
            scores = np.asarray(embeddings @ query_embedding, dtype=np.float32)
            ranked_indices = scores.argsort()[::-1]
            top_indices = ranked_indices[:top_k]
            best_expected_rank: int | None = None
            results: list[dict[str, object]] = []
            for rank, idx in enumerate(top_indices, start=1):
                face_key = (str(oracle_ids[idx]), int(face_ixs[idx]))
                name = face_names.get(face_key, "")
                if best_expected_rank is None and name.casefold() in expected_lookup:
                    best_expected_rank = rank
                results.append(
                    {
                        "rank": rank,
                        "oracle_id": face_key[0],
                        "face_ix": face_key[1],
                        "name": name,
                        "score": round(float(scores[idx]), 6),
                        "text_preview": face_texts.get(face_key, "")[:120].replace("\n", " "),
                    }
                )
            if best_expected_rank is None and expected_lookup:
                for rank, idx in enumerate(ranked_indices, start=1):
                    face_key = (str(oracle_ids[idx]), int(face_ixs[idx]))
                    if face_names.get(face_key, "").casefold() in expected_lookup:
                        best_expected_rank = rank
                        break

            top1_hit = best_expected_rank == 1
            top3_hit = best_expected_rank is not None and best_expected_rank <= 3
            top5_hit = best_expected_rank is not None and best_expected_rank <= 5
            reciprocal_rank = 0.0 if best_expected_rank is None else round(1.0 / best_expected_rank, 6)
            top1_hits += int(top1_hit)
            top3_hits += int(top3_hit)
            top5_hits += int(top5_hit)
            reciprocal_rank_sum += reciprocal_rank
            query_results.append(
                {
                    "query": query,
                    "notes": str(item.get("notes") or ""),
                    "expected_cards": expected_cards,
                    "best_expected_rank": best_expected_rank,
                    "top1_hit": top1_hit,
                    "top3_hit": top3_hit,
                    "top5_hit": top5_hit,
                    "reciprocal_rank": reciprocal_rank,
                    "results": results,
                }
            )

        query_count = len(query_results)
        eval_summary = {
            "query_count": query_count,
            "top1_hits": top1_hits,
            "top3_hits": top3_hits,
            "top5_hits": top5_hits,
            "top1_rate": round(top1_hits / query_count, 6) if query_count else 0.0,
            "top3_rate": round(top3_hits / query_count, 6) if query_count else 0.0,
            "top5_rate": round(top5_hits / query_count, 6) if query_count else 0.0,
            "mrr": round(reciprocal_rank_sum / query_count, 6) if query_count else 0.0,
        }
        eval_dir = artifact_root / "eval"
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "eval.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "top_k": top_k,
                    "summary": eval_summary,
                    "queries": query_results,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("Eval artifact saved.")

        training_dir = artifact_root / "training"
        training_dir.mkdir(parents=True, exist_ok=True)
        (training_dir / "training-dataset.json").write_bytes(dataset_json)

        llm_model = dataset_metadata.get("augmentation", {}).get("llm_model") if isinstance(dataset_metadata.get("augmentation"), dict) else None
        (artifact_root / "config.json").write_text(
            json.dumps(
                {
                    "base_model": base_model,
                    "epochs": epochs,
                    "batch_size": batch_size,
                    "skip_fine_tune": skip_fine_tune,
                    "augmentation_mode": augmentation_mode,
                    "dataset_metadata": dataset_metadata,
                    **({"llm_model": llm_model} if llm_model else {}),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (artifact_root / "metrics.json").write_text(
            json.dumps(
                {
                    "face_count": len(face_texts),
                    "pair_count": len(pair_ids),
                    "direct_text_pair_count": len(direct_text_pairs),
                    "template_query_examples": dataset_state.template_query_examples,
                    "llm_query_examples": dataset_state.llm_query_examples,
                    "skip_fine_tune": skip_fine_tune,
                    "eval_summary": eval_summary,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (artifact_root / "manifest.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "bundle": {
                        "has_onnx_model": True,
                        "has_pytorch_model": True,
                        "has_precomputed_embeddings": True,
                        "has_training_dataset": True,
                        "has_eval_json": True,
                    },
                    "source_semantic_data_version": dataset_metadata.get("semantic_data_version"),
                    "dataset_metadata": dataset_metadata,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        zip_base = Path(tmp) / "onnx-model"
        shutil.make_archive(str(zip_base), "zip", str(artifact_root))
        return zip_base.with_suffix(".zip").read_bytes()
