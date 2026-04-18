#!/usr/bin/env python3
"""
enrich_benchmarks.py — Pull benchmark scores from trusted external sources and write
them into each model's _meta.benchmarks.<source>.

Sources (pluggable):
  - livebench           — livebench.ai (public JSON in GitHub repo)
  - openrouter_stats    — production latency/throughput from OpenRouter API
  - artificial_analysis — stub (needs scrape or API access)
  - gaia                — stub (HuggingFace leaderboard scrape)
  - tau_bench           — stub (HuggingFace leaderboard scrape)
  - lmsys_arena_elo     — stub (HTML scrape)
  - aider               — stub (YAML in GitHub repo)
  - swe_bench           — stub (HuggingFace leaderboard scrape)

Each fetcher:
  - returns dict[model_id -> dict] with the benchmark payload for that source
  - returns empty dict on failure (logged, never raises)
  - sets as_of on every row

Usage:
  python3 scripts/enrich_benchmarks.py                     # dry run, all sources
  python3 scripts/enrich_benchmarks.py --apply             # write changes
  python3 scripts/enrich_benchmarks.py --source livebench  # one source only
  python3 scripts/enrich_benchmarks.py --list-sources      # show fetchers + status
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
TARGETS = [
    REPO_DIR / "models.json",
    REPO_DIR / "models" / "active.json",
    REPO_DIR / "models" / "discovery.json",
]

UA = {"User-Agent": "ai-model-repo/1.0 (+https://github.com/ericdiaz78/ai-model-repo)"}
TODAY = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Fetchers — each returns dict[model_id -> dict with source-specific fields + as_of]
# ---------------------------------------------------------------------------

def fetch_livebench() -> dict[str, dict]:
    """
    LiveBench publishes results to livebench.ai. The repo at github.com/LiveBench/LiveBench
    carries leaderboard CSV/JSON snapshots.

    TODO: pin a stable JSON URL. Current behavior: best-effort fetch from known candidate
    URLs; returns {} on any failure so the enrichment run still proceeds.
    """
    candidates = [
        "https://livebench.ai/api/leaderboard",
        "https://raw.githubusercontent.com/LiveBench/LiveBench/main/leaderboard/results.json",
    ]
    for url in candidates:
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            return _normalize_livebench(data)
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            print(f"  livebench: {url} -> {type(e).__name__}", file=sys.stderr)
            continue
    return {}


def _normalize_livebench(data) -> dict[str, dict]:
    """Adapt LiveBench result shape to our schema. Shape varies, so this is defensive."""
    out = {}
    rows = data if isinstance(data, list) else data.get("results", [])
    for row in rows:
        name = (row.get("model") or row.get("model_name") or "").lower()
        mid = _livebench_to_model_id(name)
        if not mid:
            continue
        out[mid] = {
            "reasoning": row.get("reasoning"),
            "coding": row.get("coding"),
            "mathematics": row.get("math") or row.get("mathematics"),
            "data_analysis": row.get("data_analysis"),
            "language": row.get("language"),
            "instruction_following": row.get("instruction_following") or row.get("if_avg"),
            "global_average": row.get("average") or row.get("global_average"),
            "as_of": TODAY,
        }
    return out


def _livebench_to_model_id(name: str) -> str | None:
    """Map LiveBench's free-form model name to our canonical model_id."""
    n = name.lower().replace(" ", "-")
    aliases = {
        "claude-sonnet-4.6": "anthropic/claude-sonnet-4-6",
        "claude-haiku-4.5": "anthropic/claude-haiku-4-5",
        "gpt-5.4-codex": "openai/gpt-5.4-codex",
        "gemini-2.5-flash": "google/gemini-2.5-flash",
        "gemini-2.5-flash-lite": "google/gemini-2.5-flash-lite",
        "minimax-m2.7": "minimax/minimax-m2.7",
        "deepseek-chat": "deepseek/deepseek-chat",
        "mimo-v2-pro": "xiaomi/mimo-v2-pro",
    }
    for alias, mid in aliases.items():
        if alias in n:
            return mid
    return None


def fetch_openrouter_stats() -> dict[str, dict]:
    """OpenRouter returns top_provider info on /api/v1/models — we use it for production signals."""
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            models = json.loads(r.read()).get("data", [])
    except Exception as e:
        print(f"  openrouter_stats: {type(e).__name__}: {e}", file=sys.stderr)
        return {}

    out = {}
    for m in models:
        tp = m.get("top_provider") or {}
        throughput = tp.get("throughput")
        latency = tp.get("latency")
        if throughput is None and latency is None:
            continue
        out[m["id"]] = {
            "throughput_tps": throughput,
            "latency_p50_ms": latency,
            "as_of": TODAY,
        }
    return out


def fetch_artificial_analysis() -> dict[str, dict]:
    """TODO: artificialanalysis.ai has a public leaderboard. API access requires signup;
    HTML scrape is possible but brittle. Leaving as stub for now — populate manually or
    wire up once we decide on an access pattern.
    """
    print("  artificial_analysis: stub (not yet implemented)", file=sys.stderr)
    return {}


def fetch_gaia() -> dict[str, dict]:
    """TODO: HuggingFace hosts the GAIA leaderboard. Space:
    https://huggingface.co/spaces/gaia-benchmark/leaderboard
    The leaderboard is a Gradio app; data may be downloadable via HF dataset or Space API.
    """
    print("  gaia: stub (not yet implemented)", file=sys.stderr)
    return {}


def fetch_tau_bench() -> dict[str, dict]:
    """TODO: TAU-bench results published at sierra.ai and in the tau-bench GitHub repo.
    Consider scraping the README table or pulling from the official results JSON once located.
    """
    print("  tau_bench: stub (not yet implemented)", file=sys.stderr)
    return {}


def fetch_lmsys_arena_elo() -> dict[str, dict]:
    """TODO: LMSYS Arena leaderboard at lmarena.ai. HTML table is scrapable; watch for
    rate limits and layout changes. HuggingFace Space sometimes exposes the underlying CSV.
    """
    print("  lmsys_arena_elo: stub (not yet implemented)", file=sys.stderr)
    return {}


def fetch_aider() -> dict[str, dict]:
    """TODO: aider.chat/docs/leaderboards/ — pull the YAML from
    github.com/paul-gauthier/aider/tree/main/benchmark
    """
    print("  aider: stub (not yet implemented)", file=sys.stderr)
    return {}


def fetch_swe_bench() -> dict[str, dict]:
    """TODO: SWE-bench verified leaderboard at swebench.com. HF Space may expose the data."""
    print("  swe_bench: stub (not yet implemented)", file=sys.stderr)
    return {}


FETCHERS = {
    "livebench": fetch_livebench,
    "openrouter_stats": fetch_openrouter_stats,
    "artificial_analysis": fetch_artificial_analysis,
    "gaia": fetch_gaia,
    "tau_bench": fetch_tau_bench,
    "lmsys_arena_elo": fetch_lmsys_arena_elo,
    "aider": fetch_aider,
    "swe_bench": fetch_swe_bench,
}


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def apply_enrichment(target: Path, all_data: dict[str, dict[str, dict]], apply: bool) -> int:
    data = json.loads(target.read_text())
    updated = 0
    for record in data:
        mid = record.get("model_id")
        meta = record.setdefault("_meta", {})
        benchmarks = meta.setdefault("benchmarks", {})
        touched = False
        for source, by_model in all_data.items():
            payload = by_model.get(mid)
            if not payload:
                continue
            cleaned = {k: v for k, v in payload.items() if v is not None}
            if not cleaned:
                continue
            benchmarks[source] = cleaned
            touched = True
        if touched:
            meta["last_updated"] = TODAY
            updated += 1
    if updated and apply:
        target.write_text(json.dumps(data, indent=2) + "\n")
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--source", help="Only run this source (default: all)")
    parser.add_argument("--list-sources", action="store_true")
    args = parser.parse_args()

    if args.list_sources:
        for name, fn in FETCHERS.items():
            doc = (fn.__doc__ or "").strip().split("\n")[0]
            print(f"  {name:22} {doc}")
        return

    to_run = [args.source] if args.source else list(FETCHERS.keys())
    for s in to_run:
        if s not in FETCHERS:
            print(f"Unknown source: {s}", file=sys.stderr); sys.exit(1)

    all_data: dict[str, dict[str, dict]] = {}
    for s in to_run:
        print(f"Fetching {s}...")
        rows = FETCHERS[s]()
        print(f"  {s}: {len(rows)} models with data")
        if rows:
            all_data[s] = rows

    if not all_data:
        print("\nNo data collected. Nothing to write.")
        return

    total = 0
    for path in TARGETS:
        if path.exists():
            n = apply_enrichment(path, all_data, args.apply)
            total += n
            if n:
                print(f"  {path.name}: {n} records touched")

    print(f"\nSummary: {total} records updated across {len(TARGETS)} files")
    if not args.apply:
        print("[DRY RUN] Pass --apply to write changes.")


if __name__ == "__main__":
    main()
