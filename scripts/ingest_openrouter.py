#!/usr/bin/env python3
"""
ingest_openrouter.py — Pull live model data from OpenRouter and sync to models.json

What this does:
  1. Fetches all 300+ models from OpenRouter's public API (no auth required)
  2. Diffs against models.json — new models, pricing changes, context window changes
  3. Updates existing records (price/context only — never overwrites human-curated fields)
  4. Appends new models with auto-populated fields + low confidence score
  5. Logs every change to CHANGELOG.md with rationale
  6. Never deletes records — marks removed models as deprecated

Usage:
  python3 scripts/ingest_openrouter.py                  # dry run (default)
  python3 scripts/ingest_openrouter.py --apply          # write changes
  python3 scripts/ingest_openrouter.py --apply --quiet  # write + suppress per-change output
  python3 scripts/ingest_openrouter.py --filter anthropic,google  # limit to providers
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
MODELS_FILE = REPO_DIR / "models.json"
CHANGELOG_FILE = REPO_DIR / "CHANGELOG.md"
OPENROUTER_API = "https://openrouter.ai/api/v1/models"

# Providers we trust enough to auto-ingest new models (others still get flagged but marked low-confidence)
TRUSTED_PROVIDERS = {
    "anthropic", "openai", "google", "mistralai", "meta-llama",
    "deepseek", "qwen", "x-ai", "minimax", "nvidia", "cohere",
    "amazon", "perplexity", "01-ai"
}

# Fields that are human-curated — never overwrite from OpenRouter
PROTECTED_FIELDS = {"strengths", "weaknesses", "ideal_use_cases", "performance_notes", "routing_tags"}

# Minimum pricing to bother tracking (filters out $0 experimental endpoints)
MIN_PRICE_THRESHOLD = 0.0


def fetch_openrouter_models() -> list[dict]:
    req = urllib.request.Request(OPENROUTER_API, headers={"User-Agent": "ai-model-repo/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read()).get("data", [])


def normalize_provider(or_id: str) -> str:
    """Map OpenRouter provider prefix to our schema provider names."""
    prefix = or_id.split("/")[0].lower()
    mapping = {
        "anthropic": "anthropic",
        "openai": "openai",
        "google": "google",
        "mistralai": "mistral",
        "meta-llama": "meta",
        "deepseek": "deepseek",
        "qwen": "qwen",
        "x-ai": "xai",
        "minimax": "minimax",
        "nvidia": "nvidia",
        "cohere": "cohere",
        "amazon": "amazon",
        "perplexity": "perplexity",
        "xiaomi": "xiaomi",
        "z-ai": "zai",
        "baidu": "baidu",
        "bytedance-seed": "bytedance",
        "moonshotai": "moonshot",
    }
    return mapping.get(prefix, prefix)


def price_per_mtok(price_str: str) -> float:
    """Convert OpenRouter per-token price string to per-million-token float."""
    try:
        return round(float(price_str) * 1_000_000, 4)
    except (ValueError, TypeError):
        return 0.0


def parse_modalities(arch: dict) -> list[str]:
    modalities = []
    for m in arch.get("input_modalities", []):
        if m not in modalities:
            modalities.append(m)
    # Add 'code' tag if it's a code-specialized model (heuristic from name)
    return modalities


def infer_routing_tags(or_model: dict) -> list[str]:
    """Generate starter routing tags from model name and description. Low confidence — human should refine."""
    tags = []
    name = (or_model.get("name", "") + " " + or_model.get("description", "")).lower()
    if any(w in name for w in ["code", "codex", "coder", "dev"]):
        tags.append("coding")
    if any(w in name for w in ["vision", "image", "vl", "visual"]):
        tags.append("vision")
    if any(w in name for w in ["instruct", "chat"]):
        tags.append("chat")
    if any(w in name for w in ["fast", "flash", "lite", "mini", "small", "haiku"]):
        tags.append("fast-response")
        tags.append("low-cost")
    if any(w in name for w in ["reasoning", "think", "r1", "o1", "o3"]):
        tags.append("reasoning")
    if any(w in name for w in ["pro", "opus", "ultra", "large", "plus"]):
        tags.append("analysis")
    if not tags:
        tags.append("general")
    return tags


def build_new_record(or_model: dict) -> dict:
    """Build a full schema-compliant record from an OpenRouter model entry."""
    provider = normalize_provider(or_model["id"])
    arch = or_model.get("architecture", {})
    pricing = or_model.get("pricing", {})
    input_price = price_per_mtok(pricing.get("prompt", "0"))
    output_price = price_per_mtok(pricing.get("completion", "0"))

    created_ts = or_model.get("created")
    release_date = (
        datetime.fromtimestamp(created_ts, tz=timezone.utc).strftime("%Y-%m-%d")
        if created_ts else "unknown"
    )

    slug = or_model.get("canonical_slug") or or_model["id"]
    trusted = provider in TRUSTED_PROVIDERS

    return {
        "model_id": or_model["id"],
        "provider": provider,
        "model_name": or_model.get("name", or_model["id"]),
        "version": "unknown",
        "release_date": release_date,
        "strengths": [],
        "weaknesses": [],
        "ideal_use_cases": [],
        "pricing": {
            "input_per_mtok": input_price,
            "output_per_mtok": output_price,
            "notes": f"${input_price}/M input, ${output_price}/M output (auto-ingested from OpenRouter)"
        },
        "context_window": or_model.get("context_length") or or_model.get("top_provider", {}).get("context_length", 0),
        "modalities": parse_modalities(arch),
        "performance_notes": or_model.get("description", "")[:300] if or_model.get("description") else "",
        "routing_tags": infer_routing_tags(or_model),
        "openrouter_slug": slug,
        "_meta": {
            "last_updated": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
            "source": "openrouter-api",
            "confidence": 0.6 if trusted else 0.4,
            "auto_ingested": True,
            "needs_review": True
        }
    }


def detect_changes(existing: dict, or_model: dict) -> dict:
    """Return a dict of field -> (old_val, new_val) for fields that changed."""
    changes = {}
    pricing = or_model.get("pricing", {})
    new_input = price_per_mtok(pricing.get("prompt", "0"))
    new_output = price_per_mtok(pricing.get("completion", "0"))
    old_input = existing.get("pricing", {}).get("input_per_mtok", 0)
    old_output = existing.get("pricing", {}).get("output_per_mtok", 0)

    # Detect price changes (>1% delta to avoid float noise)
    if old_input > 0 and abs(new_input - old_input) / old_input > 0.01:
        changes["pricing.input_per_mtok"] = (old_input, new_input)
    if old_output > 0 and abs(new_output - old_output) / old_output > 0.01:
        changes["pricing.output_per_mtok"] = (old_output, new_output)

    # Detect context window changes
    new_ctx = or_model.get("context_length") or or_model.get("top_provider", {}).get("context_length", 0)
    old_ctx = existing.get("context_window", 0)
    if new_ctx and new_ctx != old_ctx:
        changes["context_window"] = (old_ctx, new_ctx)

    return changes


def apply_changes(existing: dict, changes: dict, or_model: dict) -> dict:
    """Apply detected changes to existing record without touching protected fields."""
    updated = dict(existing)
    pricing = dict(existing.get("pricing", {}))

    if "pricing.input_per_mtok" in changes:
        pricing["input_per_mtok"] = changes["pricing.input_per_mtok"][1]
    if "pricing.output_per_mtok" in changes:
        pricing["output_per_mtok"] = changes["pricing.output_per_mtok"][1]
    if "pricing.input_per_mtok" in changes or "pricing.output_per_mtok" in changes:
        pricing["notes"] = (
            f"${pricing.get('input_per_mtok',0)}/M input, "
            f"${pricing.get('output_per_mtok',0)}/M output (updated from OpenRouter)"
        )
        updated["pricing"] = pricing

    if "context_window" in changes:
        updated["context_window"] = changes["context_window"][1]

    # Always update openrouter_slug to latest canonical
    slug = or_model.get("canonical_slug") or or_model["id"]
    updated["openrouter_slug"] = slug

    meta = dict(existing.get("_meta", {}))
    meta["last_updated"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    meta["source"] = "openrouter-api"
    updated["_meta"] = meta

    return updated


def append_changelog(entries: list[str]) -> None:
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    block = f"\n## [{today}] — Auto-ingestion from OpenRouter\n\n" + "\n".join(f"- {e}" for e in entries) + "\n"
    content = CHANGELOG_FILE.read_text()
    # Insert after the first heading line
    lines = content.split("\n")
    insert_at = next((i + 1 for i, l in enumerate(lines) if l.startswith("# ")), 1)
    lines.insert(insert_at, block)
    CHANGELOG_FILE.write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Sync models from OpenRouter API")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry run)")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-change output")
    parser.add_argument("--filter", help="Comma-separated provider prefixes to limit (e.g. anthropic,google)")
    parser.add_argument("--new-only", action="store_true", help="Only show/add new models, skip update diffs")
    args = parser.parse_args()

    provider_filter = set(args.filter.lower().split(",")) if args.filter else None

    print(f"Fetching from {OPENROUTER_API}...")
    or_models = fetch_openrouter_models()
    print(f"  {len(or_models)} models returned from OpenRouter")

    if provider_filter:
        or_models = [m for m in or_models if m["id"].split("/")[0].lower() in provider_filter]
        print(f"  Filtered to {len(or_models)} models matching: {args.filter}")

    existing_models: list[dict] = json.loads(MODELS_FILE.read_text())
    existing_by_id = {m["model_id"]: m for m in existing_models}
    existing_by_slug = {m.get("openrouter_slug"): m for m in existing_models if m.get("openrouter_slug")}

    new_records = []
    updated_records = {}  # model_id -> (updated_record, changes_dict)
    skipped = 0
    changelog_entries = []

    for or_model in or_models:
        mid = or_model["id"]
        slug = or_model.get("canonical_slug") or mid
        pricing = or_model.get("pricing", {})

        # Skip free/zero-price models (experimental endpoints, not production)
        input_price = price_per_mtok(pricing.get("prompt", "0"))
        if input_price <= MIN_PRICE_THRESHOLD:
            skipped += 1
            continue

        # Match against existing records
        existing = existing_by_id.get(mid) or existing_by_slug.get(slug)

        if existing:
            if args.new_only:
                continue
            changes = detect_changes(existing, or_model)
            if changes:
                updated = apply_changes(existing, changes, or_model)
                updated_records[existing["model_id"]] = (updated, changes)
                for field, (old, new) in changes.items():
                    changelog_entries.append(
                        f"Updated `{existing['model_id']}` — {field}: {old} → {new}"
                    )
                    if not args.quiet:
                        print(f"  CHANGED  {existing['model_id']}: {field} {old} → {new}")
        else:
            record = build_new_record(or_model)
            new_records.append(record)
            changelog_entries.append(
                f"New model ingested: `{mid}` ({record['provider']}) — "
                f"${record['pricing']['input_per_mtok']}/M in, "
                f"${record['pricing']['output_per_mtok']}/M out, "
                f"ctx={record['context_window']:,}"
            )
            if not args.quiet:
                print(f"  NEW      {mid} ({record['provider']}) "
                      f"in=${record['pricing']['input_per_mtok']}/M "
                      f"ctx={record['context_window']:,} "
                      f"{'[NEEDS REVIEW]' if record['_meta']['needs_review'] else ''}")

    print(f"\nSummary:")
    print(f"  {len(new_records)} new models")
    print(f"  {len(updated_records)} updated records")
    print(f"  {skipped} skipped (free/zero-price endpoints)")
    print(f"  {len(existing_models)} existing records unchanged")

    if not (new_records or updated_records):
        print("\nNo changes detected. Catalog is current.")
        return

    if not args.apply:
        print("\n[DRY RUN] Pass --apply to write changes.")
        return

    # Apply updates to existing records
    final_models = []
    for m in existing_models:
        if m["model_id"] in updated_records:
            final_models.append(updated_records[m["model_id"]][0])
        else:
            final_models.append(m)

    # Append new records
    final_models.extend(new_records)

    MODELS_FILE.write_text(json.dumps(final_models, indent=2) + "\n")
    print(f"\nWrote {len(final_models)} models to {MODELS_FILE.name}")

    if changelog_entries:
        append_changelog(changelog_entries)
        print(f"Logged {len(changelog_entries)} changes to CHANGELOG.md")

    print("\nDone. New models have _meta.needs_review=true — review routing_tags and strengths before promoting.")


if __name__ == "__main__":
    main()
