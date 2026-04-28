from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

import numpy as np

DEFAULT_EVAL_TOP_K = 5
_EVAL_TEXT_PREVIEW = 120


def default_eval_queries_bytes() -> bytes:
    return files("ot_backend.semantic").joinpath("eval_queries.json").read_bytes()


def load_eval_queries_payload(eval_queries_bytes: bytes | None = None) -> dict[str, Any]:
    raw = eval_queries_bytes if eval_queries_bytes is not None else default_eval_queries_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Eval queries payload must be a JSON object.")
    return payload


def summarize_eval_payload(eval_payload: dict[str, Any]) -> dict[str, object]:
    summary = eval_payload.get("summary")
    if not isinstance(summary, dict):
        return {}
    return {str(key): value for key, value in summary.items()}


def build_eval_payload(
    model: Any,
    *,
    face_texts: dict[tuple[str, int], str],
    face_names: dict[tuple[str, int], str],
    oracle_ids: list[str],
    face_ixs: list[int],
    embeddings: np.ndarray,
    eval_queries_bytes: bytes | None = None,
    top_k: int = DEFAULT_EVAL_TOP_K,
) -> dict[str, Any]:
    queries_payload = load_eval_queries_payload(eval_queries_bytes)
    raw_queries = queries_payload.get("queries")
    if not isinstance(raw_queries, list):
        raise ValueError("Eval queries payload must contain a 'queries' list.")

    effective_top_k = max(1, top_k)
    query_results: list[dict[str, Any]] = []
    top1_hits = 0
    top3_hits = 0
    top5_hits = 0
    reciprocal_rank_sum = 0.0

    if len(oracle_ids) != len(face_ixs) or len(oracle_ids) != len(embeddings):
        raise ValueError("Embeddings snapshot lengths are inconsistent for eval.")

    for item in raw_queries:
        if not isinstance(item, dict):
            raise ValueError("Each eval query must be a JSON object.")
        query = str(item.get("query") or "").strip()
        if not query:
            raise ValueError("Eval query entries must include a non-empty 'query'.")
        expected_cards = [str(name) for name in item.get("expected_cards", []) if str(name).strip()]
        expected_lookup = {name.casefold() for name in expected_cards}
        notes = str(item.get("notes") or "")

        query_embedding = np.asarray(
            model.encode(
                [query],
                normalize_embeddings=True,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )[0]
        scores = np.asarray(embeddings @ query_embedding, dtype=np.float32)
        ranked_indices = scores.argsort()[::-1]
        top_indices = ranked_indices[:effective_top_k]

        best_expected_rank: int | None = None
        results: list[dict[str, Any]] = []
        for rank, idx in enumerate(top_indices, start=1):
            oracle_id = str(oracle_ids[idx])
            face_ix = int(face_ixs[idx])
            face_key = (oracle_id, face_ix)
            name = face_names.get(face_key, "")
            if best_expected_rank is None and name.casefold() in expected_lookup:
                best_expected_rank = rank
            results.append(
                {
                    "rank": rank,
                    "oracle_id": oracle_id,
                    "face_ix": face_ix,
                    "name": name,
                    "score": round(float(scores[idx]), 6),
                    "text_preview": face_texts.get(face_key, "")[:_EVAL_TEXT_PREVIEW].replace("\n", " "),
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
                "notes": notes,
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
    summary = {
        "query_count": query_count,
        "top1_hits": top1_hits,
        "top3_hits": top3_hits,
        "top5_hits": top5_hits,
        "top1_rate": round(top1_hits / query_count, 6) if query_count else 0.0,
        "top3_rate": round(top3_hits / query_count, 6) if query_count else 0.0,
        "top5_rate": round(top5_hits / query_count, 6) if query_count else 0.0,
        "mrr": round(reciprocal_rank_sum / query_count, 6) if query_count else 0.0,
    }
    return {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "top_k": effective_top_k,
        "summary": summary,
        "queries": query_results,
    }


def build_eval_json_bytes(
    model: Any,
    *,
    face_texts: dict[tuple[str, int], str],
    face_names: dict[tuple[str, int], str],
    oracle_ids: list[str],
    face_ixs: list[int],
    embeddings: np.ndarray,
    eval_queries_bytes: bytes | None = None,
    top_k: int = DEFAULT_EVAL_TOP_K,
) -> tuple[bytes, dict[str, object]]:
    payload = build_eval_payload(
        model,
        face_texts=face_texts,
        face_names=face_names,
        oracle_ids=oracle_ids,
        face_ixs=face_ixs,
        embeddings=embeddings,
        eval_queries_bytes=eval_queries_bytes,
        top_k=top_k,
    )
    return json.dumps(payload, indent=2).encode("utf-8"), summarize_eval_payload(payload)
