"""Simulate the Modal LLM augmentation flow locally via Ollama.

Uses the same prompt, parser, and gap-face selection rules as
`ot_backend.semantic.modal_train` so you can inspect candidate LLM pairs without
running a remote Modal training job.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Allow importing ot_backend when running from backend/
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ot_backend.semantic import modal_train
from ot_backend.semantic.text_prep import EMPTY_ORACLE_TOKEN


def _call_ollama(
    prompt: str,
    *,
    model: str,
    base_url: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Ollama request failed with HTTP {exc.code} at {base_url}/api/chat. "
            f"Response: {body or exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not connect to Ollama at {base_url}. Is `ollama serve` running?"
        ) from exc
    message = result.get("message")
    if not isinstance(message, dict):
        raise RuntimeError(f"Unexpected Ollama response shape: {result!r}")
    return str(message.get("content") or "")


def _load_gap_faces(
    dataset_path: Path,
    *,
    min_template_coverage: int,
    max_faces: int,
) -> list[dict[str, str]]:
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    face_rows = [
        {
            "oracle_id": str(row["oracle_id"]),
            "face_ix": int(row["face_ix"]),
            "oracle_text": "" if str(row.get("text") or "") == EMPTY_ORACLE_TOKEN else str(row.get("text") or ""),
            "text": str(row.get("text") or ""),
        }
        for row in (payload.get("ability_texts") or payload.get("face_texts") or [])
        if str(row.get("text") or "").strip()
    ]
    return modal_train._select_llm_gap_faces(
        face_rows,
        min_template_coverage=min_template_coverage,
        max_faces=max_faces,
    )


def _merge_pairs(dataset_path: Path, output_path: Path, pairs: list[tuple[str, str]]) -> None:
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    existing_pairs = {(str(a), str(b)) for a, b in payload.get("direct_text_pairs", [])}
    appended = 0
    payload.setdefault("direct_text_pairs", [])
    for query, text in pairs:
        pair = (query, text)
        if pair in existing_pairs:
            continue
        existing_pairs.add(pair)
        payload["direct_text_pairs"].append([query, text])
        appended += 1
    payload["llm_query_examples"] = int(payload.get("llm_query_examples", 0)) + appended
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="simulate_modal_llm_augmentation.py",
        description="Run the Modal LLM augmentation prompt/parser locally against Ollama.",
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--min-template-coverage", type=int, default=2)
    parser.add_argument("--max-faces", type=int, default=100)
    parser.add_argument("--max-per-face", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument("--max-tokens", type=int, default=500)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--merge-output", type=Path, default=None)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    gap_faces = _load_gap_faces(
        args.dataset,
        min_template_coverage=args.min_template_coverage,
        max_faces=args.max_faces,
    )
    print(
        f"Selected {len(gap_faces):,} gap faces "
        f"(min_template_coverage={args.min_template_coverage}, max_faces={args.max_faces})."
    )
    if not gap_faces:
        print("Nothing to do.")
        return 0

    results: list[tuple[str, str]] = []
    for index, face in enumerate(gap_faces, start=1):
        prompt = modal_train._build_llm_prompt(face, max_queries=args.max_per_face)
        raw = _call_ollama(
            prompt,
            model=args.model,
            base_url=args.ollama_url,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
        )
        queries = modal_train._parse_llm_queries(raw, max_queries=args.max_per_face)
        if args.debug:
            print(f"\n[{index}] oracle_id={face['oracle_id']} face_ix={face['face_ix']}")
            print(raw)
        for query in queries:
            results.append((query, face["text"]))
            print(json.dumps({"oracle_id": face["oracle_id"], "face_ix": face["face_ix"], "query": query}))

    print(f"\nGenerated {len(results):,} query/oracle pairs.")
    if args.merge_output is not None:
        _merge_pairs(args.dataset, args.merge_output, results)
        print(f"Merged output written to {args.merge_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
