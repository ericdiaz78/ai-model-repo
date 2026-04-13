#!/usr/bin/env python3
"""
fetch_direct_usage.py — Pull usage from direct provider APIs (Anthropic, OpenAI, Google).

Each provider requires specific key types:
  Anthropic: ANTHROPIC_ADMIN_KEY (console.anthropic.com → API Keys → Admin key)
  OpenAI:    OPENAI_ADMIN_KEY    (platform.openai.com → API Keys → with api.usage.read scope)
  Google:    GOOGLE_AI_KEY       (aistudio.google.com → API Keys)

Falls back gracefully if a key is missing — runs what it can.

Usage:
  python3 scripts/fetch_direct_usage.py              # all available providers
  python3 scripts/fetch_direct_usage.py --provider anthropic
  python3 scripts/fetch_direct_usage.py --days 30
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
STATE_FILE = REPO_DIR / ".direct-usage-state.json"
ENV_FILE = Path.home() / ".openclaw" / ".env"
OPENCLAW_CFG = Path.home() / ".openclaw" / "openclaw.json"


def load_env():
    """Load keys from .env file and openclaw.json."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    if OPENCLAW_CFG.exists():
        try:
            cfg = json.loads(OPENCLAW_CFG.read_text())
            env.update(cfg.get("env", {}))
        except Exception:
            pass
    env.update(os.environ)  # live env takes precedence
    return env


def get_key(env, *names):
    for n in names:
        if env.get(n):
            return env[n]
    return None


# ─── Anthropic ────────────────────────────────────────────────────────────────

def fetch_anthropic_usage(key, start_date, end_date):
    """
    Anthropic Organization Usage API.
    Requires admin key: console.anthropic.com → Settings → API Keys → Create Admin Key
    Docs: https://docs.anthropic.com/en/api/usage
    """
    results = []
    page = 1
    while True:
        params = {
            "start_date": start_date,  # YYYY-MM-DD
            "end_date": end_date,
            "limit": 100,
            "page": page,
        }
        url = f"https://api.anthropic.com/v1/organizations/usage?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "User-Agent": "ai-model-repo/1.0"
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"  Anthropic API error {e.code}: {body[:200]}")
            print("  → Need Admin API key (not standard API key)")
            print("    Get it: console.anthropic.com → Settings → API Keys → Admin Key")
            return None

        items = data.get("data", data.get("usage", []))
        results.extend(items)
        if not data.get("has_more") or not items:
            break
        page += 1

    # Aggregate by model
    agg = defaultdict(lambda: {"cost": 0.0, "input_tokens": 0, "output_tokens": 0,
                                "cache_read_tokens": 0, "cache_write_tokens": 0, "requests": 0})
    for item in results:
        model = item.get("model", "unknown")
        agg[model]["input_tokens"] += item.get("input_tokens", 0)
        agg[model]["output_tokens"] += item.get("output_tokens", 0)
        agg[model]["cache_read_tokens"] += item.get("cache_read_input_tokens", 0)
        agg[model]["cache_write_tokens"] += item.get("cache_creation_input_tokens", 0)
        agg[model]["requests"] += item.get("request_count", 1)
        # Compute cost if not provided
        cost = item.get("cost", 0)
        agg[model]["cost"] += cost

    return dict(agg)


# ─── OpenAI ───────────────────────────────────────────────────────────────────

def fetch_openai_usage(key, start_ts, end_ts):
    """
    OpenAI Organization Usage API.
    Requires key with api.usage.read scope:
    platform.openai.com → API Keys → Create key → check 'Usage' permission
    Docs: https://platform.openai.com/docs/api-reference/usage
    """
    params = {
        "start_time": int(start_ts),
        "end_time": int(end_ts),
        "bucket_width": "1d",
        "limit": 180,
    }
    url = f"https://api.openai.com/v1/organization/usage/completions?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "User-Agent": "ai-model-repo/1.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        err = json.loads(body).get("error", body[:200]) if body.startswith("{") else body[:200]
        print(f"  OpenAI API error {e.code}: {err}")
        print("  → Need API key with 'api.usage.read' scope")
        print("    Get it: platform.openai.com → API Keys → Create restricted key → Usage: Read")
        return None

    if "error" in data:
        print(f"  OpenAI error: {data['error']}")
        return None

    agg = defaultdict(lambda: {"cost": 0.0, "input_tokens": 0, "output_tokens": 0,
                                "cache_read_tokens": 0, "requests": 0})
    for bucket in data.get("data", []):
        for result in bucket.get("results", []):
            model = result.get("model", "unknown")
            agg[model]["input_tokens"] += result.get("input_tokens", 0)
            agg[model]["output_tokens"] += result.get("output_tokens", 0)
            agg[model]["cache_read_tokens"] += result.get("input_cached_tokens", 0)
            agg[model]["requests"] += result.get("num_model_requests", 0)
            # OpenAI doesn't return cost directly in usage API — compute from pricing
            # We store tokens and let the app compute cost from direct_pricing

    return dict(agg)


# ─── Google ───────────────────────────────────────────────────────────────────

def fetch_google_usage(key, start_date, end_date):
    """
    Google AI Studio usage API.
    Uses GOOGLE_AI_KEY from aistudio.google.com → Get API Key
    Note: Google doesn't have a detailed usage API yet — this checks quota/credit usage.
    For detailed usage, need Google Cloud Billing API (service account required).
    Docs: https://ai.google.dev/gemini-api/docs/usage-metadata
    """
    # Google AI Studio doesn't have a programmatic usage history API yet
    # This is a placeholder that checks the key is valid
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=5"
    req = urllib.request.Request(url, headers={"User-Agent": "ai-model-repo/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            model_count = len(data.get("models", []))
            print(f"  Google AI key valid — {model_count} models accessible")
            print("  ⚠ Google usage API not yet available via AI Studio key")
            print("    For billing data: enable Google Cloud Billing API + service account")
            return None  # No data available yet
    except urllib.error.HTTPError as e:
        print(f"  Google API error {e.code}: need GOOGLE_AI_KEY from aistudio.google.com")
        return None


# ─── Model Matching ────────────────────────────────────────────────────────────

def match_model(slug, models):
    for m in models:
        if m["model_id"] == slug or m.get("openrouter_slug") == slug:
            return m
    # Fuzzy: provider/name contains slug fragments
    slug_parts = slug.lower().replace("-", " ").split()
    for m in models:
        mid = m["model_id"].lower().replace("-", " ")
        if sum(1 for p in slug_parts if p in mid) >= 2:
            return m
    return None


def normalize_model_slug(raw, provider):
    """Normalize provider-specific model names to openrouter-style slugs."""
    raw = raw.lower().strip()
    prefix = {
        "anthropic": "anthropic/",
        "openai": "openai/",
        "google": "google/",
    }.get(provider, "")
    if not raw.startswith(prefix.rstrip("/")):
        raw = prefix + raw
    return raw


def merge_spend(existing, new_data, source, period_start, period_end, now):
    """Merge new spend data into existing spend record."""
    updated = dict(existing) if existing else {}
    updated["total_cost_usd"] = round(updated.get("total_cost_usd", 0) + new_data.get("cost", 0), 6)
    updated["total_input_mtok"] = round(updated.get("total_input_mtok", 0) + new_data.get("input_tokens", 0) / 1e6, 4)
    updated["total_output_mtok"] = round(updated.get("total_output_mtok", 0) + new_data.get("output_tokens", 0) / 1e6, 4)
    updated["total_cache_read_mtok"] = round(updated.get("total_cache_read_mtok", 0) + new_data.get("cache_read_tokens", 0) / 1e6, 4)
    updated["call_count"] = updated.get("call_count", 0) + new_data.get("requests", 0)
    updated["avg_cost_per_call_usd"] = round(updated["total_cost_usd"] / max(updated["call_count"], 1), 6)
    updated["period_start"] = updated.get("period_start", period_start) or period_start
    updated["period_end"] = period_end
    updated["source"] = source
    updated["imported_at"] = now.strftime("%Y-%m-%d %H:%M UTC")
    return updated


def main():
    parser = argparse.ArgumentParser(description="Fetch direct provider usage")
    parser.add_argument("--provider", choices=["anthropic", "openai", "google", "all"], default="all")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    env = load_env()
    now = datetime.now(tz=timezone.utc)
    start_dt = now - timedelta(days=args.days)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")
    start_ts = start_dt.timestamp()

    models = json.loads(MODELS_FILE.read_text())
    total_matched = 0

    # ── Anthropic ──
    if args.provider in ("all", "anthropic"):
        key = get_key(env, "ANTHROPIC_ADMIN_KEY", "ANTHROPIC_MANAGEMENT_KEY")
        if key:
            print("Anthropic: fetching usage...")
            data = fetch_anthropic_usage(key, start_date, end_date)
            if data:
                for slug, usage in data.items():
                    norm = normalize_model_slug(slug, "anthropic")
                    m = match_model(norm, models) or match_model(slug, models)
                    if m:
                        m["spend"] = merge_spend(m.get("spend"), usage,
                            "anthropic-direct", start_date, end_date, now)
                        total_matched += 1
                print(f"  ✓ {len(data)} models, {total_matched} matched")
        else:
            print("Anthropic: ANTHROPIC_ADMIN_KEY not set — skipping")
            print("  → Get it: console.anthropic.com → Settings → API Keys → Admin Key")

    # ── OpenAI ──
    if args.provider in ("all", "openai"):
        key = get_key(env, "OPENAI_ADMIN_KEY", "OPENAI_ORG_KEY")
        if key:
            print("OpenAI: fetching usage...")
            data = fetch_openai_usage(key, start_ts, now.timestamp())
            if data:
                matched = 0
                for slug, usage in data.items():
                    norm = normalize_model_slug(slug, "openai")
                    m = match_model(norm, models) or match_model(slug, models)
                    if m:
                        m["spend"] = merge_spend(m.get("spend"), usage,
                            "openai-direct", start_date, end_date, now)
                        matched += 1
                total_matched += matched
                print(f"  ✓ {len(data)} models, {matched} matched")
        else:
            print("OpenAI: OPENAI_ADMIN_KEY not set — skipping")
            print("  → Get it: platform.openai.com → API Keys → Create with 'Usage: Read' scope")

    # ── Google ──
    if args.provider in ("all", "google"):
        key = get_key(env, "GOOGLE_AI_KEY", "GOOGLE_API_KEY")
        if key:
            print("Google: checking key...")
            fetch_google_usage(key, start_date, end_date)
        else:
            print("Google: GOOGLE_AI_KEY not set — skipping")
            print("  → Get it: aistudio.google.com → Get API Key")

    if total_matched > 0:
        MODELS_FILE.write_text(json.dumps(models, indent=2) + "\n")
        print(f"\nSaved. {total_matched} models updated with direct usage data.")
    else:
        print("\nNo direct usage data written (keys missing or APIs unavailable).")

    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    state["last_sync"] = now.isoformat()
    state["last_sync_ts"] = now.timestamp()
    state["providers_attempted"] = args.provider
    STATE_FILE.write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
