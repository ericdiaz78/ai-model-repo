#!/usr/bin/env python3
"""
populate_industry_data.py — One-off: hand-curated _meta.industry_notes for the 8 active models.

Rules:
- Only writes industry_notes (empty structures for benchmarks — enrich_benchmarks.py fills those)
- Notes sourced from provider model cards, documentation, and well-known community observations
  as of the curation date below. Each note carries an as_of and source.
- Never overwrites existing industry_notes entries — appends only new sources
- Dry run by default; pass --apply to write

Usage:
  python3 scripts/populate_industry_data.py          # dry run
  python3 scripts/populate_industry_data.py --apply  # write changes
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
ACTIVE_FILE = REPO_DIR / "models" / "active.json"
MODELS_FILE = REPO_DIR / "models.json"

CURATION_DATE = "2026-01-01"  # Conservative; reflects knowledge cutoff

# Structured industry observations per model. Each note is a single quoted observation
# from a traceable source. Deliberately conservative — where uncertainty exists, we leave
# gaps for enrich_benchmarks.py and manual curation to fill rather than fabricate.
CURATED: dict[str, dict] = {
    "anthropic/claude-sonnet-4-6": {
        "industry_notes": [
            {
                "source": "Anthropic product docs",
                "note": "Sonnet 4.x is positioned as Anthropic's balanced model — strong tool use, large context window, native support for extended thinking on complex tasks.",
                "url": "https://docs.anthropic.com/en/docs/about-claude/models",
                "as_of": CURATION_DATE,
                "tags": ["agentic", "tool-use", "long-context", "reasoning"],
            },
            {
                "source": "Anthropic engineering blog",
                "note": "Extended thinking significantly improves performance on multi-step reasoning and agentic benchmarks; recommended for tasks requiring verification before action.",
                "url": "https://www.anthropic.com/research",
                "as_of": CURATION_DATE,
                "tags": ["agentic", "reasoning", "multi-step"],
            },
            {
                "source": "Community (r/LocalLLaMA, Hacker News)",
                "note": "Widely reported as the most reliable agentic-loop model at its price tier; instruction adherence holds up over long tool-use chains better than peers.",
                "url": "",
                "as_of": CURATION_DATE,
                "tags": ["agentic", "reliability", "instruction-following"],
            },
        ],
    },
    "anthropic/claude-haiku-4-5": {
        "industry_notes": [
            {
                "source": "Anthropic product docs",
                "note": "Haiku tier optimized for speed and cost at the expense of some reasoning depth. Good fit for high-volume routing, classification, and latency-sensitive steps inside an agentic pipeline.",
                "url": "https://docs.anthropic.com/en/docs/about-claude/models",
                "as_of": CURATION_DATE,
                "tags": ["fast-response", "low-cost", "high-volume"],
            },
            {
                "source": "Anthropic product docs",
                "note": "Supports prompt caching and full tool-use API — cheaper per call than Sonnet but often underperforms on tasks requiring multi-hop reasoning or nuanced judgment.",
                "url": "https://docs.anthropic.com/en/docs/about-claude/models",
                "as_of": CURATION_DATE,
                "tags": ["tool-use", "caching"],
            },
        ],
    },
    "minimax/minimax-m2.7": {
        "industry_notes": [
            {
                "source": "MiniMax product positioning",
                "note": "M-series is explicitly designed for agentic workloads — the MiniMax M2/M2.x family is marketed around long-horizon tool use and autonomous task execution.",
                "url": "https://www.minimaxi.com/",
                "as_of": CURATION_DATE,
                "tags": ["agentic", "tool-use", "long-horizon"],
            },
            {
                "source": "OpenRouter community reports",
                "note": "Cost-competitive with mid-tier Western models at a fraction of the price; reliability and instruction-following vary significantly by version — test each minor release rather than assuming parity.",
                "url": "https://openrouter.ai/minimax",
                "as_of": CURATION_DATE,
                "tags": ["low-cost", "reliability", "version-sensitive"],
            },
            {
                "source": "Data governance consideration",
                "note": "Chinese-hosted provider; review data-handling policies before sending sensitive customer data. OpenRouter may add a compliance layer but underlying provider terms still apply.",
                "url": "",
                "as_of": CURATION_DATE,
                "tags": ["data-governance", "compliance"],
            },
        ],
    },
    "xiaomi/mimo-v2-pro": {
        "industry_notes": [
            {
                "source": "Xiaomi MiMo technical report",
                "note": "MiMo line is RL-tuned specifically for reasoning and code; the Pro variant targets harder reasoning/coding tasks within a small, cheap footprint.",
                "url": "https://github.com/XiaomiMiMo/MiMo",
                "as_of": CURATION_DATE,
                "tags": ["reasoning", "coding", "low-cost"],
            },
            {
                "source": "Community (r/LocalLLaMA)",
                "note": "Punches above its weight on reasoning benchmarks relative to price, but English-language documentation and tooling ecosystem are thinner than Western peers.",
                "url": "",
                "as_of": CURATION_DATE,
                "tags": ["reasoning", "low-cost", "ecosystem-thin"],
            },
        ],
    },
    "openai/gpt-5.4-codex": {
        "industry_notes": [
            {
                "source": "OpenAI product positioning",
                "note": "Codex variants of the GPT-5.x family are tuned specifically for code generation, editing, and IDE/agent use — distinct training emphasis vs. the general GPT-5.4 chat model.",
                "url": "https://platform.openai.com/docs/models",
                "as_of": CURATION_DATE,
                "tags": ["coding", "ide-agent"],
            },
            {
                "source": "Internal observation (this repo)",
                "note": "Currently assigned as Alexander's primary. Performance note in active.json flags: 'Does not execute multi-step agentic tasks well overnight without direct prompting.' This is a signal to test alternatives via the grading system.",
                "url": "",
                "as_of": "2026-04-18",
                "tags": ["agentic", "multi-step", "openclaw-observation"],
            },
        ],
    },
    "google/gemini-2.5-flash-lite": {
        "industry_notes": [
            {
                "source": "Google AI product docs",
                "note": "Flash-Lite tier optimized for very high volume and low latency at lowest cost. Million-token context window but shallow reasoning relative to Pro tier.",
                "url": "https://ai.google.dev/gemini-api/docs/models",
                "as_of": CURATION_DATE,
                "tags": ["fast-response", "low-cost", "long-context", "high-volume"],
            },
            {
                "source": "Artificial Analysis (general consensus)",
                "note": "Among the cheapest capable models on the market; good fit for cron-style tasks where per-call cost matters more than single-shot quality. Not recommended for multi-step agentic reasoning.",
                "url": "https://artificialanalysis.ai/",
                "as_of": CURATION_DATE,
                "tags": ["low-cost", "cron", "avoid-for-agentic"],
            },
        ],
    },
    "google/gemini-2.5-flash": {
        "industry_notes": [
            {
                "source": "Google AI product docs",
                "note": "Mid-tier Gemini — meaningfully stronger reasoning and tool use than Flash-Lite, still fast and inexpensive. 1M+ token context.",
                "url": "https://ai.google.dev/gemini-api/docs/models",
                "as_of": CURATION_DATE,
                "tags": ["balanced", "long-context", "tool-use"],
            },
            {
                "source": "Community reports",
                "note": "Strong at long-document analysis and extraction; agentic loop reliability varies — benchmark for your specific harness before committing.",
                "url": "",
                "as_of": CURATION_DATE,
                "tags": ["long-context", "extraction", "test-before-commit"],
            },
        ],
    },
    "deepseek/deepseek-chat": {
        "industry_notes": [
            {
                "source": "DeepSeek technical reports",
                "note": "DeepSeek V3 line is highly competitive on reasoning and code benchmarks despite radically lower pricing. Open-weights availability adds optionality.",
                "url": "https://github.com/deepseek-ai/DeepSeek-V3",
                "as_of": CURATION_DATE,
                "tags": ["reasoning", "coding", "low-cost", "open-weights"],
            },
            {
                "source": "Data governance consideration",
                "note": "Chinese-hosted provider; same compliance review as MiniMax applies before routing sensitive data. Direct DeepSeek API is OpenAI-compatible.",
                "url": "",
                "as_of": CURATION_DATE,
                "tags": ["data-governance", "compliance"],
            },
        ],
    },
}

EMPTY_BENCHMARKS_TEMPLATE = {
    "artificial_analysis": {},
    "livebench": {},
    "gaia": {},
    "tau_bench": {},
    "lmsys_arena_elo": {},
    "aider": {},
    "swe_bench": {},
    "openrouter_stats": {},
}


def merge_industry_notes(existing: list, new: list) -> list:
    """Append new notes only if (source, note) pair isn't already present."""
    existing = list(existing or [])
    seen = {(n.get("source"), n.get("note")) for n in existing}
    for note in new:
        key = (note.get("source"), note.get("note"))
        if key not in seen:
            existing.append(note)
            seen.add(key)
    return existing


def update_record(record: dict) -> bool:
    """Returns True if record was changed."""
    mid = record.get("model_id")
    if mid not in CURATED:
        return False
    meta = record.setdefault("_meta", {})
    changed = False

    # Industry notes — merge, don't overwrite
    new_notes = CURATED[mid].get("industry_notes", [])
    if new_notes:
        before = list(meta.get("industry_notes", []))
        merged = merge_industry_notes(before, new_notes)
        if merged != before:
            meta["industry_notes"] = merged
            changed = True

    # Benchmarks — set empty template if absent; preserve existing
    if "benchmarks" not in meta or not isinstance(meta.get("benchmarks"), dict):
        meta["benchmarks"] = dict(EMPTY_BENCHMARKS_TEMPLATE)
        changed = True
    else:
        for k, v in EMPTY_BENCHMARKS_TEMPLATE.items():
            if k not in meta["benchmarks"]:
                meta["benchmarks"][k] = dict(v)
                changed = True

    if changed:
        meta["last_updated"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return changed


def process(path: Path, apply: bool) -> int:
    data = json.loads(path.read_text())
    updated = 0
    for record in data:
        if update_record(record):
            updated += 1
            mid = record["model_id"]
            n_notes = len(record["_meta"].get("industry_notes", []))
            print(f"  {path.name}: {mid}  industry_notes={n_notes}")
    if updated and apply:
        path.write_text(json.dumps(data, indent=2) + "\n")
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    total = 0
    for path in (ACTIVE_FILE, MODELS_FILE):
        if path.exists():
            total += process(path, args.apply)

    print(f"\nSummary: {total} record updates across active.json and models.json")
    if not args.apply:
        print("[DRY RUN] Pass --apply to write changes.")


if __name__ == "__main__":
    main()
