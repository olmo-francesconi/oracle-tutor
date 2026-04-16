"""Generate LLM-based synthetic queries via local Ollama for MTG card faces
with low template query coverage.

Reads an exported training dataset JSON, identifies faces with fewer than
--min-coverage template queries, and generates additional natural-language
queries via Ollama. Results are written to a resumable JSONL checkpoint file.

When done (or at any point), run with --merge-output to produce a merged
training dataset ready for modal_train.py.

Usage
-----
# Step 1 — generate (resumable, safe to Ctrl+C and restart):
uv run python scripts/generate_queries_ollama.py \\
    --dataset data/training-dataset.json \\
    --checkpoint data/llm-queries.jsonl \\
    [--model qwen3.5:9b] \\
    [--limit 50]              # smoke-test with 50 faces first

# Step 2 — merge into a training-ready dataset:
uv run python scripts/generate_queries_ollama.py \\
    --dataset data/training-dataset.json \\
    --checkpoint data/llm-queries.jsonl \\
    --merge-output data/training-dataset-llm.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

# Allow importing ot_backend when running from backend/
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ot_backend.semantic.query_gen import generate_template_queries

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a search query generator for a Magic: The Gathering card database.
When given card oracle text, output exactly 3 short search queries that a \
player might type to find cards with this effect.

Rules:
- Each query must be 2-8 words, all lowercase
- Use Magic: The Gathering terminology where appropriate \
(e.g. "draw a card", "counter a spell", "enters the battlefield", "tap for mana")
- Describe what the card DOES — its mechanic or effect — not its name
- Output one query per line, nothing else: no numbering, no bullets, no explanation
- Focus on the most distinctive or searchable thing the card does"""

# Qwen3 thinking-mode disable directive
_NO_THINK_SUFFIX = " /no_think"

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_LIST_PREFIX = re.compile(r"^[\s\-\*•\d\.\)]+")


def _parse_queries(raw: str, max_per_face: int) -> list[str]:
    text = _THINK_BLOCK.sub("", raw).strip()
    results: list[str] = []
    for line in text.splitlines():
        line = _LIST_PREFIX.sub("", line).strip().rstrip(".,;:")
        if not line:
            continue
        line = line.lower()
        words = line.split()
        if 2 <= len(words) <= 8:
            results.append(line)
        if len(results) >= max_per_face:
            break
    return results


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

def _call_ollama(
    oracle_text: str,
    model: str,
    base_url: str,
    timeout: int = 60,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": oracle_text + _NO_THINK_SUFFIX},
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.6,
            "num_predict": 500,
        },
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read())
    return result["message"]["content"]


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def _load_checkpoint(path: Path) -> dict[str, list[str]]:
    """Return completed {oracle_id:face_ix -> [queries]} rows from a JSONL checkpoint file."""
    done: dict[str, list[str]] = {}
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        queries = [str(q).strip() for q in rec.get("queries", []) if str(q).strip()]
        if not queries:
            continue
        key = f"{rec['oracle_id']}:{rec['face_ix']}"
        done[key] = queries
    return done


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def _merge(base_path: Path, checkpoint: dict[str, list[str]], output_path: Path) -> None:
    payload = json.loads(base_path.read_text(encoding="utf-8"))
    face_lookup = {
        (r["oracle_id"], r["face_ix"]): r["text"] for r in payload["face_texts"]
    }
    existing_pairs = {
        (str(anchor), str(text)) for anchor, text in payload.get("direct_text_pairs", [])
    }

    extra_pairs: list[list[str]] = []
    for key, queries in checkpoint.items():
        oracle_id, face_ix_str = key.rsplit(":", 1)
        text = face_lookup.get((oracle_id, int(face_ix_str)))
        if not text or not queries:
            continue
        for q in queries:
            pair = (q, text)
            if pair in existing_pairs:
                continue
            existing_pairs.add(pair)
            extra_pairs.append([q, text])

    payload.setdefault("direct_text_pairs", [])
    payload["direct_text_pairs"].extend(extra_pairs)
    payload["llm_query_examples"] = int(payload.get("llm_query_examples", 0)) + len(extra_pairs)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload), encoding="utf-8")
    existing = len(payload["direct_text_pairs"]) - len(extra_pairs)
    print(
        f"Merged {len(extra_pairs):,} new LLM pairs into {existing:,} existing "
        f"direct_text_pairs → {output_path}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate_queries_ollama.py",
        description="Generate LLM queries for MTG card faces via local Ollama.",
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("data/llm-queries.jsonl"),
        help="Resumable JSONL output (appended to on each run).",
    )
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument(
        "--min-coverage",
        type=int,
        default=2,
        help="Only process faces with fewer than this many template queries (default: 2).",
    )
    parser.add_argument(
        "--max-per-face",
        type=int,
        default=3,
        help="Max LLM queries to generate per face (default: 3).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after N faces (0 = all). Useful for smoke-testing.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print raw model responses (useful when queries come back empty).",
    )
    parser.add_argument(
        "--merge-output",
        type=Path,
        default=None,
        help="Merge checkpoint into the base dataset and write to this path, then exit.",
    )
    args = parser.parse_args(argv)

    checkpoint = _load_checkpoint(args.checkpoint)

    if args.merge_output:
        _merge(args.dataset, checkpoint, args.merge_output)
        return 0

    # Load face texts
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    face_texts: dict[tuple[str, int], str] = {
        (r["oracle_id"], r["face_ix"]): r["text"] for r in payload["face_texts"]
    }

    # Find gap faces: low template coverage and not yet processed
    gap: list[tuple[str, int, str]] = []
    for (oracle_id, face_ix), text in face_texts.items():
        key = f"{oracle_id}:{face_ix}"
        if key in checkpoint:
            continue
        if len(generate_template_queries(text)) < args.min_coverage:
            gap.append((oracle_id, face_ix, text))

    if args.limit > 0:
        gap = gap[: args.limit]

    print(
        f"Dataset: {len(face_texts):,} faces total\n"
        f"Already in checkpoint: {len(checkpoint):,}\n"
        f"Gap faces to process: {len(gap):,}  (min-coverage={args.min_coverage})"
    )
    if not gap:
        print("Nothing to do.")
        return 0

    # Verify Ollama is reachable before starting
    try:
        urllib.request.urlopen(f"{args.ollama_url}/api/tags", timeout=5)
    except Exception as exc:
        print(f"[ERROR] Cannot reach Ollama at {args.ollama_url}: {exc}")
        print("Make sure Ollama is running: ollama serve")
        return 1

    ckpt_file = args.checkpoint.open("a", encoding="utf-8")
    processed = skipped = 0
    t0 = time.monotonic()

    try:
        for i, (oracle_id, face_ix, text) in enumerate(gap):
            try:
                raw = _call_ollama(text, args.model, args.ollama_url)
                queries = _parse_queries(raw, args.max_per_face)
                if args.debug:
                    print(f"  [RAW] {repr(raw)}", flush=True)
            except Exception as exc:
                print(f"  [WARN] {oracle_id[:8]}:{face_ix} — {exc}", flush=True)
                skipped += 1
                continue
            if not queries:
                print(f"  [WARN] {oracle_id[:8]}:{face_ix} — no valid queries parsed", flush=True)
                skipped += 1
                continue

            rec = {"oracle_id": oracle_id, "face_ix": face_ix, "queries": queries}
            ckpt_file.write(json.dumps(rec) + "\n")
            ckpt_file.flush()
            processed += 1

            elapsed = time.monotonic() - t0
            rate = processed / elapsed
            eta_h = (len(gap) - i - 1) / rate / 3600 if rate > 0 else 0
            print(
                f"[{i+1:>6}/{len(gap)}]  {rate:.1f}/s  ~{eta_h:.1f}h left"
                f"  {oracle_id[:8]}:{face_ix}  {queries}",
                flush=True,
            )
    finally:
        ckpt_file.close()

    print(f"\nDone. processed={processed:,}  skipped={skipped:,}")
    print(f"Checkpoint saved to: {args.checkpoint}")
    print(f"\nWhen ready to merge:\n"
          f"  uv run python scripts/generate_queries_ollama.py \\\n"
          f"    --dataset {args.dataset} \\\n"
          f"    --checkpoint {args.checkpoint} \\\n"
          f"    --merge-output data/training-dataset-llm.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
