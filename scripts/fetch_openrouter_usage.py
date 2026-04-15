#!/usr/bin/env python3
"""
fetch_openrouter_usage.py — Pull live usage from OpenRouter API and update model spend data.

Runs via cron (hourly). No CSV needed — hits the management API directly.
Uses OPENROUTER_MANAGEMENT_KEY from environment.

Usage:
  python3 scripts/fetch_openrouter_usage.py          # last 7 days (default)
  python3 scripts/fetch_openrouter_usage.py --days 30
  python3 scripts/fetch_openrouter_usage.py --since 2026-04-01
"""

import argparse
import json
import os
import urllib.request
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
MODELS_FILE = REPO_DIR / "models.json"
STATE_FILE = REPO_DIR / ".usage-sync-state.json"  # tracks last successful pull

OPENROUTER_ACTIVITY_URL = "https://openrouter.ai/api/v1/activity"
OPENROUTER_CREDITS_URL = "https://openrouter.ai/api/v1/credits"
SPEND_HISTORY_FILE = REPO_DIR / "spend_history.json"


def load_history():
    if SPEND_HISTORY_FILE.exists():
        try:
            return json.loads(SPEND_HISTORY_FILE.read_text())
        except Exception:
            pass
    return {}


def save_history(history):
    SPEND_HISTORY_FILE.write_text(json.dumps(history, indent=2) + "\n")


def get_management_key():
    key = os.environ.get("OPENROUTER_MANAGEMENT_KEY", "")
    if not key:
        # Try reading from openclaw.json
        try:
            openclaw = Path.home() / ".openclaw" / "openclaw.json"
            cfg = json.loads(openclaw.read_text())
            key = cfg.get("env", {}).get("OPENROUTER_MANAGEMENT_KEY", "")
        except Exception:
            pass
    if not key:
        raise RuntimeError("OPENROUTER_MANAGEMENT_KEY not found in env or openclaw.json")
    return key


def fetch_activity(key, start_ts, end_ts=None, limit=1000):
    """Fetch activity records from OpenRouter API."""
    params = {
        "start_time": int(start_ts),
        "limit": limit,
        "offset": 0,
    }
    if end_ts:
        params["end_time"] = int(end_ts)

    url = f"{OPENROUTER_ACTIVITY_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "User-Agent": "ai-model-repo/1.0"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    return data.get("data", [])


def fetch_credits(key):
    req = urllib.request.Request(OPENROUTER_CREDITS_URL, headers={
        "Authorization": f"Bearer {key}",
        "User-Agent": "ai-model-repo/1.0"
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read()).get("data", {})


def aggregate_activity(records):
    """Aggregate activity records by model slug, and collect daily breakdowns."""
    agg = defaultdict(lambda: {
        "total_cost_usd": 0.0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_read_tokens": 0,
        "call_count": 0,
        "dates": set(),
    })
    # daily[slug][date] = {cost_usd, input_tokens, output_tokens, calls}
    daily = defaultdict(lambda: defaultdict(lambda: {
        "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "calls": 0
    }))
    for r in records:
        slug = r.get("model_permaslug") or r.get("model", "")
        if not slug:
            continue
        cost = float(r.get("usage", 0))
        inp = int(r.get("prompt_tokens", 0))
        out = int(r.get("completion_tokens", 0))
        calls = int(r.get("requests", 1))
        agg[slug]["total_cost_usd"] += cost
        agg[slug]["total_input_tokens"] += inp
        agg[slug]["total_output_tokens"] += out
        agg[slug]["call_count"] += calls
        date = (r.get("date") or "")[:10]
        if date:
            agg[slug]["dates"].add(date)
            daily[slug][date]["cost_usd"] += cost
            daily[slug][date]["input_tokens"] += inp
            daily[slug][date]["output_tokens"] += out
            daily[slug][date]["calls"] += calls
    return dict(agg), {slug: dict(days) for slug, days in daily.items()}


def merge_spend_history(history, slug, new_daily):
    """Merge new daily data into spend history, replacing overlapping day buckets."""
    existing = {entry["date"]: entry for entry in history.get(slug, [])}
    for date, data in new_daily.items():
        existing[date] = {
            "date": date,
            "cost_usd": round(data["cost_usd"], 8),
            "input_tokens": int(data["input_tokens"]),
            "output_tokens": int(data["output_tokens"]),
            "calls": int(data["calls"]),
        }
    history[slug] = sorted(existing.values(), key=lambda x: x["date"])
    return history[slug]


def summarize_history(entries):
    if not entries:
        return None
    total_cost = round(sum(entry.get("cost_usd", 0) for entry in entries), 6)
    total_input_mtok = round(sum(entry.get("input_tokens", 0) for entry in entries) / 1e6, 4)
    total_output_mtok = round(sum(entry.get("output_tokens", 0) for entry in entries) / 1e6, 4)
    total_calls = sum(entry.get("calls", 0) for entry in entries)
    return {
        "total_cost_usd": total_cost,
        "total_input_mtok": total_input_mtok,
        "total_output_mtok": total_output_mtok,
        "total_cache_read_mtok": 0,
        "call_count": total_calls,
        "avg_cost_per_call_usd": round(total_cost / max(total_calls, 1), 6),
        "period_start": entries[0]["date"],
        "period_end": entries[-1]["date"],
    }


def match_model(slug, models):
    for m in models:
        if m["model_id"] == slug:
            return m
        if m.get("openrouter_slug") == slug:
            return m
    # Partial match
    for m in models:
        if slug in m["model_id"] or m["model_id"] in slug:
            return m
    return None


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Fetch OpenRouter usage and update model spend data")
    parser.add_argument("--days", type=int, default=7, help="Number of days to fetch (default: 7)")
    parser.add_argument("--since", help="Fetch since date YYYY-MM-DD (overrides --days)")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-model output")
    args = parser.parse_args()

    key = get_management_key()
    now = datetime.now(tz=timezone.utc)

    if args.since:
        start_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        # Use state to determine last sync, fall back to --days
        state = load_state()
        last_sync = state.get("last_sync_ts")
        if last_sync:
            start_dt = datetime.fromtimestamp(last_sync, tz=timezone.utc) - timedelta(hours=1)  # 1hr overlap
        else:
            start_dt = now - timedelta(days=args.days)

    start_ts = start_dt.timestamp()
    print(f"Fetching activity since {start_dt.strftime('%Y-%m-%d %H:%M')} UTC...")

    # Pull credits balance too
    credits = fetch_credits(key)
    total_usage = credits.get("total_usage", 0)
    total_credits = credits.get("total_credits", 0)
    print(f"Account: ${total_usage:.4f} used / ${total_credits:.2f} credits")

    # Fetch activity
    records = fetch_activity(key, start_ts)
    print(f"  {len(records)} activity records returned")

    if not records:
        print("No new activity. State updated.")
        save_state({"last_sync_ts": now.timestamp(), "last_sync": now.isoformat()})
        return

    agg, daily = aggregate_activity(records)
    history = load_history()

    # Print summary
    if not args.quiet:
        print(f"\n{'Model':<50} {'Calls':>6} {'Cost':>10} {'Input MTok':>10} {'Output MTok':>11}")
        print("-" * 92)
        for slug, data in sorted(agg.items(), key=lambda x: -x[1]["total_cost_usd"]):
            print(f"{slug:<50} {data['call_count']:>6} "
                  f"${data['total_cost_usd']:>9.4f} "
                  f"{data['total_input_tokens']/1e6:>10.2f} "
                  f"{data['total_output_tokens']/1e6:>11.2f}")
        print(f"\nTotal activity cost (this window): ${sum(v['total_cost_usd'] for v in agg.values()):.4f}")

    # Merge into models.json
    models = json.loads(MODELS_FILE.read_text())
    matched = 0
    unmatched = []

    all_dates = []
    for data in agg.values():
        all_dates.extend(data["dates"])
    period_start = min(all_dates) if all_dates else start_dt.strftime("%Y-%m-%d")
    period_end = max(all_dates) if all_dates else now.strftime("%Y-%m-%d")

    for slug, data in agg.items():
        if slug in daily:
            merge_spend_history(history, slug, daily[slug])

        m = match_model(slug, models)
        if m:
            summary = summarize_history(history.get(slug, []))
            if summary is None:
                summary = {
                    "total_cost_usd": round(data["total_cost_usd"], 6),
                    "total_input_mtok": round(data["total_input_tokens"] / 1e6, 4),
                    "total_output_mtok": round(data["total_output_tokens"] / 1e6, 4),
                    "total_cache_read_mtok": round(data["total_cache_read_tokens"] / 1e6, 4),
                    "call_count": data["call_count"],
                    "avg_cost_per_call_usd": round(data["total_cost_usd"] / max(data["call_count"], 1), 6),
                    "period_start": period_start,
                    "period_end": period_end,
                }
            m["spend"] = {
                **summary,
                "source": "openrouter-api",
                "imported_at": now.strftime("%Y-%m-%d %H:%M UTC"),
            }
            matched += 1
        else:
            unmatched.append(slug)

    save_history(history)
    MODELS_FILE.write_text(json.dumps(models, indent=2) + "\n")

    state = {
        "last_sync_ts": now.timestamp(),
        "last_sync": now.isoformat(),
        "last_matched": matched,
        "last_unmatched": len(unmatched),
        "account_total_usage_usd": total_usage,
        "account_total_credits_usd": total_credits,
    }
    save_state(state)

    print(f"\nUpdated {matched} models. {len(unmatched)} unmatched slugs: {unmatched[:5]}")
    print(f"State saved. Next run will fetch from {now.strftime('%Y-%m-%d %H:%M')} UTC.")


if __name__ == "__main__":
    main()
