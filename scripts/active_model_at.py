#!/usr/bin/env python3
"""
active_model_at.py — Resolve which model an agent was running at a given timestamp.

Priority (first hit wins):
  1. `model_changes.jsonl` (this repo) — entries written by the ai-model-repo UI
     when Eric switches an agent's primary. Chronological, append-only.
  2. Current `~/.openclaw/openclaw.json` — agents.list[].model.primary fallback
     if no historical change covers that (agent, timestamp).

Normalizes provider-prefixed IDs down to the canonical model_id used in the repo:
  openrouter/google/gemini-2.5-flash  -> google/gemini-2.5-flash
  openai-codex/gpt-5.4                -> openai/gpt-5.4-codex
  anthropic/claude-sonnet-4-6         -> anthropic/claude-sonnet-4-6

Usage:
  python3 scripts/active_model_at.py <agent_id> <iso_timestamp>
  python3 scripts/active_model_at.py build 2026-04-15T18:00:00Z
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
MODEL_CHANGES = REPO_DIR / "model_changes.jsonl"
OPENCLAW_JSON = Path.home() / ".openclaw" / "openclaw.json"

AGENT_ROLE = {
    "build": "builder",
    "strategy": "strategy",
    "general": "gm",
    "main": "gm",
    "sage": "sage",
}


def _parse_ts(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def normalize_model_id(raw: str) -> str:
    """Strip provider prefixes and adapt naming to ai-model-repo canonical IDs."""
    if not raw:
        return ""
    s = raw.strip()
    # openrouter/<provider>/<model> -> <provider>/<model>
    if s.startswith("openrouter/"):
        s = s[len("openrouter/"):]
    # openai-codex/<gpt-5.x> -> openai/<gpt-5.x>-codex
    if s.startswith("openai-codex/"):
        tail = s[len("openai-codex/"):]
        if "codex" not in tail:
            tail = f"{tail}-codex"
        s = f"openai/{tail}"
    return s


def load_history() -> list[dict]:
    if not MODEL_CHANGES.exists():
        return []
    out = []
    for line in MODEL_CHANGES.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    out.sort(key=lambda r: r.get("timestamp", ""))
    return out


def load_current_defaults() -> dict[str, str]:
    if not OPENCLAW_JSON.exists():
        return {}
    try:
        d = json.loads(OPENCLAW_JSON.read_text())
    except json.JSONDecodeError:
        return {}
    out = {}
    for a in d.get("agents", {}).get("list", []) or []:
        aid = a.get("id") or a.get("name")
        m = a.get("model")
        if isinstance(m, dict):
            m = m.get("primary")
        if aid and m:
            out[aid] = m
    return out


def resolve(agent: str, at: datetime) -> dict:
    at = at.astimezone(timezone.utc)
    history = load_history()
    match = None
    for row in history:
        if row.get("agent") != agent:
            continue
        try:
            row_ts = _parse_ts(row["timestamp"])
        except (KeyError, ValueError):
            continue
        if row_ts <= at:
            match = row  # keep latest that still precedes `at`

    if match:
        raw = match.get("new_primary", "")
        source = "model_changes.jsonl"
        change_ts = match.get("timestamp")
    else:
        raw = load_current_defaults().get(agent, "")
        source = "openclaw.json (current)"
        change_ts = None

    return {
        "agent": agent,
        "role": AGENT_ROLE.get(agent, agent),
        "at": at.isoformat(),
        "raw_model": raw,
        "model_id": normalize_model_id(raw),
        "source": source,
        "change_ts": change_ts,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("agent")
    p.add_argument("timestamp", help="ISO 8601 timestamp (e.g. 2026-04-15T18:00:00Z)")
    args = p.parse_args()

    try:
        ts = _parse_ts(args.timestamp)
    except ValueError as e:
        print(f"bad timestamp: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(resolve(args.agent, ts), indent=2))


if __name__ == "__main__":
    main()
