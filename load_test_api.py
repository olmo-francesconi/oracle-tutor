import argparse
import asyncio
from collections import Counter
import random
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class Stats:
    ok: int = 0
    failed: int = 0
    status_429: int = 0
    status_503: int = 0
    lat_ms: list[float] = field(default_factory=list)
    exc: Counter[str] = field(default_factory=Counter)


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    values = sorted(values)
    k = int((len(values) - 1) * p)
    return values[k]


async def worker(
    *,
    client: httpx.AsyncClient,
    url: str,
    stop_at: float,
    stats: Stats,
    think_ms: int,
) -> None:
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        try:
            r = await client.get(url)
            dt = (time.perf_counter() - t0) * 1000.0
            stats.lat_ms.append(dt)

            if 200 <= r.status_code < 300:
                stats.ok += 1
            else:
                stats.failed += 1
                if r.status_code == 429:
                    stats.status_429 += 1
                if r.status_code == 503:
                    stats.status_503 += 1
        except Exception as e:
            stats.failed += 1
            stats.exc[type(e).__name__] += 1

        if think_ms > 0:
            await asyncio.sleep((think_ms + random.randint(0, think_ms)) / 1000.0)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument(
        "--path",
        default="/health",
        help="Examples: /health, /suggest-names?q=sho&limit=10, /search-oracle?q=deals%203%20damage&limit=20&offset=0",
    )
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--seconds", type=int, default=15)
    ap.add_argument("--think-ms", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=5.0)
    args = ap.parse_args()

    url = args.base.rstrip("/") + args.path

    limits = httpx.Limits(
        max_connections=max(10, args.concurrency * 2),
        max_keepalive_connections=max(10, args.concurrency),
        keepalive_expiry=30.0,
    )
    stats = Stats()

    async with httpx.AsyncClient(timeout=args.timeout, limits=limits) as client:
        stop_at = time.perf_counter() + args.seconds
        tasks = [
            asyncio.create_task(
                worker(
                    client=client,
                    url=url,
                    stop_at=stop_at,
                    stats=stats,
                    think_ms=args.think_ms,
                )
            )
            for _ in range(args.concurrency)
        ]
        await asyncio.gather(*tasks)

    total = stats.ok + stats.failed
    rps = total / max(0.001, args.seconds)

    print(f"URL: {url}")
    print(
        f"Concurrency: {args.concurrency}, Duration: {args.seconds}s, Think: {args.think_ms}ms, Timeout: {args.timeout}s"
    )
    print(f"Total: {total}, OK: {stats.ok}, Failed: {stats.failed}, RPS: {rps:.1f}")
    print(f"429: {stats.status_429}, 503: {stats.status_503}")
    if stats.exc:
        top = ", ".join(f"{k}={v}" for k, v in stats.exc.most_common(5))
        print(f"Exceptions(top): {top}")
    if stats.lat_ms:
        print(
            "Latency ms:"
            f" p50={pct(stats.lat_ms, 0.50):.1f}"
            f" p90={pct(stats.lat_ms, 0.90):.1f}"
            f" p95={pct(stats.lat_ms, 0.95):.1f}"
            f" p99={pct(stats.lat_ms, 0.99):.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

