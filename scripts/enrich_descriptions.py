#!/usr/bin/env python3
"""
enrich_descriptions.py — Pull full model descriptions from OpenRouter's model
pages (the API truncates at ~250 chars; the page has the full 1000-2000 char
blurb inside its Next.js RSC payload). Fallback to HuggingFace for open-weights
repos when OpenRouter has nothing longer.

Writes to _meta.vendor_description (never touches performance_notes — that
field is reserved for hand-curated observations on active-shelf models).

Usage:
  python3 scripts/enrich_descriptions.py                    # dry run
  python3 scripts/enrich_descriptions.py --apply            # write
  python3 scripts/enrich_descriptions.py --model openai/gpt-5.3-codex
"""

import argparse
import json
import re
import sys
import time
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
UA = {"User-Agent": "Mozilla/5.0 (compatible; ai-model-repo/1.0; +https://github.com/ericdiaz78/ai-model-repo)"}
TODAY = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _fetch(url: str, timeout: int = 20) -> str | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"  fetch {url} -> {type(e).__name__}", file=sys.stderr)
        return None


def _decode_next_f_chunk(raw: str) -> str:
    """__next_f.push payload is JSON-escaped; decode \\n, \\", \\u00xx, etc."""
    try:
        # The payload is valid JSON string content; wrap and parse
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw.encode("utf-8").decode("unicode_escape", errors="replace")


_DESC_FIELD_RE = re.compile(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"')


def fetch_openrouter_description(model_id: str, api_preview: str = "") -> str | None:
    """OpenRouter model page embeds the full description as a JSON field
    `"description":"..."` inside one of the __next_f.push chunks. We decode
    each chunk, scan for that field, and pick the longest candidate that
    looks like prose (ignoring meta descriptions that repeat pricing text).
    """
    html = _fetch(f"https://openrouter.ai/{model_id}")
    if not html:
        return None

    chunks = re.findall(r'self\.__next_f\.push\(\[\s*1\s*,\s*"((?:[^"\\]|\\.)+)"\s*\]\)', html)
    if not chunks:
        return None

    best: str | None = None
    for raw in chunks:
        text = _decode_next_f_chunk(raw)
        if not text:
            continue
        for match in _DESC_FIELD_RE.finditer(text):
            # The captured group is still JSON-escaped (\\n, \\", etc.) — decode once more.
            try:
                candidate = json.loads(f'"{match.group(1)}"')
            except json.JSONDecodeError:
                candidate = match.group(1)
            candidate = candidate.strip()
            if len(candidate) < 200:
                continue
            # Skip the <meta name="description"> variant — it tacks pricing/context
            # onto the real blurb (e.g. "$3 per million input tokens").
            if "per million" in candidate and len(candidate) < 1500:
                continue
            if best is None or len(candidate) > len(best):
                best = candidate

    return best


def fetch_huggingface_description(model_id: str) -> str | None:
    """Some model_ids map cleanly to HF repos (deepseek-ai/DeepSeek-V3, etc.).
    We try a handful of canonical HF slugs per provider prefix.
    """
    provider, _, tail = model_id.partition("/")
    candidates = {
        "deepseek": [f"deepseek-ai/{tail}", f"deepseek-ai/{tail.title()}"],
        "minimax": [f"MiniMaxAI/{tail}", f"MiniMax-AI/{tail}"],
        "xiaomi": [f"XiaomiMiMo/{tail}"],
        "mistralai": [f"mistralai/{tail}"],
        "meta-llama": [f"meta-llama/{tail}"],
    }.get(provider, [])

    for slug in candidates:
        data = _fetch(f"https://huggingface.co/api/models/{slug}", timeout=15)
        if not data:
            continue
        try:
            meta = json.loads(data)
        except json.JSONDecodeError:
            continue
        desc = (meta.get("cardData") or {}).get("description") or ""
        if not desc:
            # Try README snippet
            desc = (meta.get("description") or "")
        if len(desc) > 200:
            return desc.strip()
    return None


def enrich_one(record: dict) -> tuple[str | None, str | None]:
    """Returns (new_description, source) or (None, None) if nothing usable."""
    mid = record.get("model_id")
    if not mid:
        return None, None

    existing = (record.get("_meta", {}) or {}).get("vendor_description")
    # Don't refetch if we already have something substantive AND it's actually prose
    if existing and len(existing) > 500:
        head = existing[:200]
        struct_chars = sum(head.count(c) for c in '"[]{}$:\\')
        letters = sum(1 for c in head if c.isalpha())
        if struct_chars <= 15 and letters >= 120:
            return None, None

    preview = record.get("performance_notes") or ""
    desc = fetch_openrouter_description(mid, api_preview=preview)
    source = "openrouter"
    if not desc:
        desc = fetch_huggingface_description(mid)
        source = "huggingface" if desc else None

    if not desc:
        return None, None

    # Only accept if meaningfully longer than the current truncated performance_notes
    current = record.get("performance_notes") or ""
    if len(desc) <= len(current):
        return None, None

    return desc, source


def process(target: Path, only: str | None, apply: bool) -> int:
    if not target.exists():
        return 0
    data = json.loads(target.read_text())
    updated = 0
    for record in data:
        mid = record.get("model_id")
        if only and mid != only:
            continue
        new_desc, source = enrich_one(record)
        if not new_desc:
            continue
        meta = record.setdefault("_meta", {})
        before_len = len((meta.get("vendor_description") or ""))
        meta["vendor_description"] = new_desc
        meta["vendor_description_source"] = source
        meta["vendor_description_fetched_at"] = TODAY
        meta["last_updated"] = TODAY
        updated += 1
        print(f"  {target.name}: {mid}  {before_len} -> {len(new_desc)} chars ({source})")
        time.sleep(0.8)  # be polite to OpenRouter
    if updated and apply:
        target.write_text(json.dumps(data, indent=2) + "\n")
    return updated


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--model", help="Only enrich this model_id")
    args = p.parse_args()

    total = 0
    for t in TARGETS:
        print(f"\nProcessing {t.name}...")
        total += process(t, args.model, args.apply)

    print(f"\nSummary: {total} records enriched across {len(TARGETS)} files")
    if not args.apply:
        print("[DRY RUN] Pass --apply to write changes.")


if __name__ == "__main__":
    main()
