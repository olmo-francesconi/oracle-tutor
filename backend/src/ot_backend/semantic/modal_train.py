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
from .dataset_service import (
    TrainingDatasetState,
    build_state_from_maps,
    load_training_dataset_bytes,
    serialize_training_dataset,
)
from .query_gen import generate_template_queries
from .text_prep import EMPTY_ORACLE_TOKEN
from .train_options import (
    DEFAULT_TRAIN_QUANTIZATION,
    TRAIN_AUGMENTATION_LLM_QUERIES,
    TRAIN_AUGMENTATION_TAG_DESCRIPTIONS,
    TRAIN_AUGMENTATION_TAG_PAIRS,
    TRAIN_AUGMENTATION_TEMPLATE_QUERIES,
    TRAIN_QUANTIZATION_INT8,
    parse_train_augmentation_mode,
    validate_train_quantization,
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
# Finished datasets and bundles are written here before the function returns.
# Return values travel in memory, so a client that dies mid-call — or right
# after, on its own DB write — would otherwise throw away the whole GPU run.
artifact_store: Any = modal.Volume.from_name("oracle-tutor-artifacts", create_if_missing=True)
_ARTIFACT_STORE_PATH = "/artifacts"
# 8 words of ordinary English; anything longer is a generation artifact.
_MAX_LLM_QUERY_CHARS = 80
# Share of total optimizer steps spent warming up the learning rate.
_WARMUP_FRACTION = 0.1
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


def _parse_ability_key_rows(rows: list[list[object]]) -> list[tuple[str, int, int]]:
    return [(str(row[0]), int(str(row[1])), int(str(row[2]))) for row in rows]


def _parse_llm_queries(raw_text: str, *, max_queries: int) -> list[str]:
    text = _THINK_BLOCK.sub("", raw_text).strip()
    deduped: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        compact = _LIST_PREFIX.sub("", line).strip().rstrip(".,;:").lower()
        if not compact:
            continue
        # Word count alone does not bound length: a degenerate repetition loop
        # ("...ationationation...") has no spaces, so 4,000 characters can count
        # as a single word and slip through. 329 such pairs reached the shipped
        # dataset, one of them 4,126 characters long.
        word_count = len(compact.split())
        if word_count < 2 or word_count > 8 or len(compact) > _MAX_LLM_QUERY_CHARS or compact in seen:
            continue
        seen.add(compact)
        deduped.append(compact)
        if len(deduped) >= max_queries:
            break
    return deduped


def _build_llm_messages(face: dict[str, str], *, max_queries: int) -> list[dict[str, str]]:
    oracle_text = face.get("oracle_text", "").strip() or face.get("text", "").strip()
    return [
        {"role": "system", "content": _LLM_SYSTEM_PROMPT_TEMPLATE.format(max_queries=max_queries)},
        {"role": "user", "content": f"Oracle text:\n{oracle_text}"},
    ]


def _build_llm_prompt(face: dict[str, str], *, max_queries: int, tokenizer: Any = None) -> str:
    """Render one instruction prompt.

    An instruct model must be given its own chat template. Handing vLLM a bare
    string makes it do raw *completion* instead of instruction-following, which
    is what produced 4,000-character repetition loops in the shipped dataset.
    The plain-string form is kept only as a fallback for a tokenizer that
    exposes no template.
    """
    messages = _build_llm_messages(face, max_queries=max_queries)
    if tokenizer is not None and getattr(tokenizer, "chat_template", None):
        return str(
            tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        )
    return f"{messages[0]['content']}\n\n{messages[1]['content']}"


def _select_llm_gap_faces(
    face_rows: list[dict[str, str]],
    *,
    min_template_coverage: int,
    max_faces: int,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    seen_text: set[str] = set()
    for row in face_rows:
        raw_oracle_text = row.get("oracle_text", "").strip()
        normalized_text = row.get("text", "").strip()
        if not raw_oracle_text or normalized_text == EMPTY_ORACLE_TOKEN:
            continue
        # Ability text repeats across cards — "Flying." alone is 3,235 rows —
        # and generating the same queries again would burn the GPU budget for
        # duplicate pairs.
        if normalized_text in seen_text:
            continue
        if len(generate_template_queries(row["text"])) >= min_template_coverage:
            continue
        seen_text.add(normalized_text)
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

    llm = LLM(
        model=str(llm_config.get("model_name", semantic_llm_model_name())),
        trust_remote_code=True,
        gpu_memory_utilization=float(os.getenv("SEMANTIC_LLM_GPU_MEMORY_UTILIZATION", "0.9")),
        max_model_len=int(os.getenv("SEMANTIC_LLM_MAX_MODEL_LEN", "4096")),
    )
    try:
        tokenizer = llm.get_tokenizer()
    except Exception as exc:  # noqa: BLE001 — fall back to the plain prompt
        print(f"WARNING: no tokenizer for chat templating ({exc}); using raw prompts.")
        tokenizer = None
    print(f"Chat template applied: {bool(tokenizer is not None and getattr(tokenizer, 'chat_template', None))}")
    prompts = [
        _build_llm_prompt(row, max_queries=queries_per_face, tokenizer=tokenizer)
        for row in selected_rows
    ]
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


# v3 changed the unit from faces to abilities. A build payload is constructed
# and shipped within a single run rather than archived, so older ones cannot be
# in flight and there is nothing to stay compatible with — unlike the *dataset*
# format, where v2-v7 remain loadable.
_SUPPORTED_BUILD_PAYLOAD_VERSIONS = frozenset({3})

# Which payload feature flag gates which augmentation key.
_FEATURE_FLAG_BY_AUGMENTATION = {
    TRAIN_AUGMENTATION_TAG_PAIRS: "tag_pairs",
    TRAIN_AUGMENTATION_TAG_DESCRIPTIONS: "tag_descriptions",
    TRAIN_AUGMENTATION_TEMPLATE_QUERIES: "template_queries",
    TRAIN_AUGMENTATION_LLM_QUERIES: "llm_queries",
}


def _build_dataset_state(
    build_payload: dict[str, Any],
    *,
    augmentation_mode: str,
    llm_config: dict[str, Any] | None = None,
) -> tuple[TrainingDatasetState, dict[str, object]]:
    if int(build_payload.get("version", 0)) not in _SUPPORTED_BUILD_PAYLOAD_VERSIONS:
        raise ValueError(
            f"Unsupported training build payload version: {build_payload.get('version')!r}. "
            f"Supported: {sorted(_SUPPORTED_BUILD_PAYLOAD_VERSIONS)}."
        )

    selected_augmentations = set(parse_train_augmentation_mode(augmentation_mode))
    raw_features = build_payload.get("features")
    feature_flags: dict[str, Any] = raw_features if isinstance(raw_features, dict) else {}
    raw_options = build_payload.get("options")
    options: dict[str, Any] = raw_options if isinstance(raw_options, dict) else {}
    ability_rows = list(build_payload.get("abilities") or [])

    ability_texts: dict[tuple[str, int, int], str] = {}
    normalized_abilities: list[dict[str, str]] = []
    for row in ability_rows:
        ability_key = (str(row["oracle_id"]), int(row["face_ix"]), int(row["ability_ix"]))
        normalized_text = str(row["text"])
        ability_texts[ability_key] = normalized_text
        normalized_abilities.append(
            {
                "oracle_id": ability_key[0],
                "face_ix": str(ability_key[1]),
                # The LLM is prompted with the printed wording and taught the
                # normalized form as the positive, as it was for faces.
                "oracle_text": str(row.get("raw") or ""),
                "text": normalized_text,
            }
        )
    card_names = {
        (str(row["oracle_id"]), int(row["face_ix"])): str(row.get("name") or "")
        for row in build_payload.get("card_names") or []
    }

    # A feature disabled when the payload was built cannot be turned back on
    # here — the payload simply lacks the rows — so the effective set is the
    # intersection of what was shipped and what this run asked for.
    effective_augmentations = {
        key
        for key in selected_augmentations
        if feature_flags.get(_FEATURE_FLAG_BY_AUGMENTATION.get(key, ""), False)
    }

    raw_tag_to_ability_ids = build_payload.get("tag_to_ability_ids")
    tag_to_ability_ids = {
        tag_name: _parse_ability_key_rows(list(raw_ids))
        for tag_name, raw_ids in (
            raw_tag_to_ability_ids if isinstance(raw_tag_to_ability_ids, dict) else {}
        ).items()
    }
    raw_tag_to_desc = build_payload.get("tag_to_desc")
    # A tag carries a list of anchors: the bare name plus name.description.
    tag_to_anchors: dict[str, list[str]] = {}
    for tag_name, raw_anchors in (raw_tag_to_desc if isinstance(raw_tag_to_desc, dict) else {}).items():
        candidates = [raw_anchors] if isinstance(raw_anchors, str) else list(raw_anchors or [])
        tag_to_anchors[tag_name] = [a for a in (str(c).strip() for c in candidates) if a]

    llm_pairs: list[tuple[str, str]] = []
    if TRAIN_AUGMENTATION_LLM_QUERIES in effective_augmentations:
        llm_pairs = _generate_llm_query_pairs(normalized_abilities, llm_config=llm_config)

    state = build_state_from_maps(
        ability_texts=ability_texts,
        card_names=card_names,
        tag_to_ability_ids=tag_to_ability_ids,
        tag_to_anchors=tag_to_anchors,
        selected_augmentations=effective_augmentations,
        max_tag_pairs_per_tag=int(options.get("max_tag_pairs_per_tag", 50)),
        max_tag_pair_group_size=int(options.get("max_tag_pair_group_size", 5)),
        max_tag_desc_pairs_per_tag=int(options.get("max_tag_desc_pairs_per_tag", 600)),
        rng=random.Random(0),
        llm_pairs=llm_pairs,
    )

    metadata = dict(build_payload.get("metadata") or {})
    metadata["augmentation"] = {
        "mode": augmentation_mode,
        "template_query_examples": state.template_query_examples,
        "llm_query_examples": len(llm_pairs),
        **({"llm_model": str((llm_config or {}).get("model_name", semantic_llm_model_name()))} if llm_pairs else {}),
    }
    return state, metadata


@app.function(
    gpu="L4",
    timeout=28800,
    image=image,
    volumes={"/root/.cache/huggingface": hf_cache, _ARTIFACT_STORE_PATH: artifact_store},
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
        f"Dataset built. abilities={len(dataset_state.ability_texts):,} "
        f"pairs={len(dataset_state.pair_ids):,} "
        f"direct={len(dataset_state.direct_text_pairs):,} "
        f"template_queries={dataset_state.template_query_examples:,} "
        f"llm_queries={dataset_state.llm_query_examples:,}"
    )
    _persist_artifact(
        dataset_json,
        kind="datasets",
        suffix=".json",
        meta={"slug": "dataset", "augmentation_mode": augmentation_mode},
    )
    return dataset_json


def _persist_artifact(data: bytes, *, kind: str, suffix: str, meta: dict[str, Any]) -> str:
    """Write a finished artifact to the artifacts volume and return its path.

    `kind` is the subdirectory ("bundles" or "datasets"). Best-effort: a failure
    here must not lose a run that otherwise succeeded, so it is logged and
    swallowed rather than raised.
    """
    import time as _time

    try:
        store = Path(_ARTIFACT_STORE_PATH) / kind
        store.mkdir(parents=True, exist_ok=True)
        stamp = _time.strftime("%Y%m%dT%H%M%SZ", _time.gmtime())
        safe_label = str(meta.get("base_model") or meta.get("slug") or kind).replace("/", "_")
        path = store / f"{stamp}-{safe_label}{suffix}"
        path.write_bytes(data)
        path.with_suffix(".json").write_text(
            json.dumps({**meta, "size_bytes": len(data), "written_at": stamp}, indent=2),
            encoding="utf-8",
        )
        artifact_store.commit()
        print(f"{kind} artifact persisted to volume: {path} ({len(data):,} bytes)")
        return str(path)
    except Exception as exc:  # noqa: BLE001 — never fail a good run over the backup
        print(f"WARNING: could not persist {kind} artifact to volume: {exc}")
        return ""


@app.function(
    gpu="L4",
    timeout=28800,
    image=image,
    volumes={"/root/.cache/huggingface": hf_cache, _ARTIFACT_STORE_PATH: artifact_store},
)
def train(
    dataset_json: bytes,
    eval_queries_json: bytes,
    base_model: str,
    epochs: int,
    batch_size: int,
    augmentation_mode: str,
    skip_fine_tune: bool = False,
    quantization: str = DEFAULT_TRAIN_QUANTIZATION,
) -> bytes:
    import numpy as np
    from sentence_transformers import InputExample, SentenceTransformer, losses
    from torch.utils.data import DataLoader, Dataset

    os.environ["WANDB_MODE"] = "disabled"
    warnings.filterwarnings("ignore", category=FutureWarning, module="sentence_transformers")

    dataset_payload = json.loads(dataset_json)
    dataset_state = load_training_dataset_bytes(dataset_json)
    dataset_metadata = dataset_payload.get("metadata") if isinstance(dataset_payload.get("metadata"), dict) else {}
    ability_texts = dataset_state.ability_texts
    card_names = dataset_state.card_names
    pair_ids = dataset_state.pair_ids
    direct_text_pairs = dataset_state.direct_text_pairs
    print(f"Dataset loaded. abilities={len(ability_texts):,} pairs={len(pair_ids):,} direct={len(direct_text_pairs):,}")

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
                return InputExample(texts=[ability_texts[left_key], ability_texts[right_key]])
            # 2 texts = (anchor, positive) with in-batch negatives only.
            # 3 texts = MNRL also scores the explicit hard negative.
            return InputExample(texts=list(self._direct[i - self._n]))

    print(f"Loading base model: {base_model}")
    model = SentenceTransformer(base_model)

    dataset = _Dataset()
    dataloader = DataLoader(dataset, shuffle=False, batch_size=batch_size)
    loss_fn = losses.MultipleNegativesRankingLoss(model)

    total = len(dataset)
    # warmup is counted in OPTIMIZER STEPS, not examples. Dividing the example
    # count by 20 gave 22,774 warmup steps against 42,702 total — 53% of every
    # run was spent ramping the learning rate.
    steps_per_epoch = -(-total // max(1, batch_size))
    total_steps = steps_per_epoch * max(1, epochs)
    warmup_steps = max(100, int(total_steps * _WARMUP_FRACTION))
    print(
        f"Training. examples={total:,} epochs={epochs} batch={batch_size} "
        f"steps={total_steps:,} warmup={warmup_steps:,} ({100 * warmup_steps / max(1, total_steps):.0f}%)"
    )

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

        quantization_mode = validate_train_quantization(quantization)
        if quantization_mode == TRAIN_QUANTIZATION_INT8:
            from onnxruntime.quantization import QuantType, quantize_dynamic

            onnx_path = models_onnx / "onnx" / "model.onnx"
            quantized_path = onnx_path.with_suffix(".quant.onnx")
            print(f"Applying int8 dynamic quantization → {onnx_path} (in place after rewrite).")
            quantize_dynamic(
                model_input=str(onnx_path),
                model_output=str(quantized_path),
                weight_type=QuantType.QInt8,
            )
            original_size = onnx_path.stat().st_size
            quantized_size = quantized_path.stat().st_size
            shutil.move(str(quantized_path), str(onnx_path))
            print(
                f"ONNX quantization done. {original_size / 1024 / 1024:.1f} MB → "
                f"{quantized_size / 1024 / 1024:.1f} MB ({100 * quantized_size / original_size:.0f}%)."
            )

        shutil.copytree(str(pytorch_path), str(artifact_root / "models" / "pytorch"))

        ordered_ability_rows = sorted(ability_texts.items())
        embed_batch_size = max(256, batch_size)
        embeddings = np.asarray(
            model.encode(
                [text for (_ability_key, text) in ordered_ability_rows],
                batch_size=embed_batch_size,
                normalize_embeddings=True,
                show_progress_bar=True,
            ),
            dtype=np.float32,
        )
        embeddings_dir = artifact_root / "embeddings"
        embeddings_dir.mkdir(parents=True, exist_ok=True)
        ability_keys = [key for (key, _text) in ordered_ability_rows]
        np.savez_compressed(
            embeddings_dir / "embeddings.npz",
            oracle_ids=np.asarray([key[0] for key in ability_keys]),
            face_ixs=np.asarray([key[1] for key in ability_keys], dtype=np.int32),
            ability_ixs=np.asarray([key[2] for key in ability_keys], dtype=np.int32),
            embeddings=embeddings,
        )
        print("Embedding archive saved.")
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
                ability_key = ability_keys[idx]
                name = card_names.get((ability_key[0], ability_key[1]), "")
                if best_expected_rank is None and name.casefold() in expected_lookup:
                    best_expected_rank = rank
                results.append(
                    {
                        "rank": rank,
                        "oracle_id": ability_key[0],
                        "face_ix": ability_key[1],
                        "ability_ix": ability_key[2],
                        "name": name,
                        "score": round(float(scores[idx]), 6),
                        "text_preview": ability_texts.get(ability_key, "")[:120].replace("\n", " "),
                    }
                )
            if best_expected_rank is None and expected_lookup:
                for rank, idx in enumerate(ranked_indices, start=1):
                    key = ability_keys[idx]
                    if card_names.get((key[0], key[1]), "").casefold() in expected_lookup:
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
                    "ability_count": len(ability_texts),
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
        bundle_bytes = zip_base.with_suffix(".zip").read_bytes()
        _persist_artifact(
            bundle_bytes,
            kind="bundles",
            suffix=".zip",
            meta={"base_model": base_model, "augmentation_mode": augmentation_mode},
        )
        return bundle_bytes
