#!/usr/bin/env python3
"""
refresh_descriptions.py — One-off: refresh performance_notes for auto-ingested models
whose descriptions were truncated at 300 chars by the old ingest cap.

Safety rules:
- Only touches records where _meta.auto_ingested is true
- Only replaces if current performance_notes is a strict prefix of OpenRouter's current description
  (so human edits are never overwritten)
- Dry run by default; pass --apply to write

Usage:
  python3 scripts/refresh_descriptions.py           # dry run
  python3 scripts/refresh_descriptions.py --apply   # write changes
"""

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
OPENROUTER_API = "https://openrouter.ai/api/v1/models"
TARGETS = [
    REPO_DIR / "models.json",
    REPO_DIR / "models" / "active.json",
    REPO_DIR / "models" / "discovery.json",
]


def fetch_openrouter_descriptions() -> dict[str, str]:
    req = urllib.request.Request(OPENROUTER_API, headers={"User-Agent": "ai-model-repo/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read()).get("data", [])
    return {m["id"]: m.get("description", "") for m in data}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print(f"Fetching live descriptions from OpenRouter...")
    or_descs = fetch_openrouter_descriptions()
    print(f"  {len(or_descs)} descriptions available\n")

    total_updated = 0
    total_files = 0

    for target in TARGETS:
        if not target.exists():
            continue
        data = json.loads(target.read_text())
        if not isinstance(data, list):
            continue

        updated = 0
        for record in data:
            mid = record.get("model_id")
            current = record.get("performance_notes", "") or ""
            full = or_descs.get(mid, "") or ""
            meta = record.get("_meta", {})

            if not full or not meta.get("auto_ingested"):
                continue

            # Only replace if current is a strict prefix of the full OpenRouter description
            # AND current is shorter (i.e. truly truncated).
            if current and len(current) < len(full) and full.startswith(current.rstrip("."). rstrip()[:260]):
                record["performance_notes"] = full
                meta["last_updated"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
                record["_meta"] = meta
                updated += 1
                total_updated += 1
                print(f"  {target.name}: {mid}  {len(current)} -> {len(full)} chars")

        if updated:
            total_files += 1
            if args.apply:
                target.write_text(json.dumps(data, indent=2) + "\n")

    print(f"\nSummary: {total_updated} records across {total_files} files")
    if not args.apply:
        print("[DRY RUN] Pass --apply to write changes.")


if __name__ == "__main__":
    main()
