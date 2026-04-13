#!/usr/bin/env python3
"""
import_spend.py — Import provider activity CSVs and populate model spend + daily history.

Supports:
  OpenRouter  — openrouter.ai/activity → Export CSV (per-call rows)
  Anthropic   — console.anthropic.com/settings/usage → Export (daily aggregate rows)
  OpenAI      — platform.openai.com/usage → Export (daily aggregate rows)

Provider is auto-detected from column names. Use --provider to override.

Usage:
  python3 scripts/import_spend.py openrouter_activity.csv
  python3 scripts/import_spend.py openrouter_activity.csv --apply      # write to models.json + spend_history.json
  python3 scripts/import_spend.py anthropic_usage.csv --apply
  python3 scripts/import_spend.py openrouter_activity.csv --show       # print summary only
  python3 scripts/import_spend.py openrouter_activity.csv --history-only  # only update spend_history.json (skip models.json)

This backfills trend chart history from your existing exports.
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
MODELS_FILE = REPO_DIR / "models.json"
SPEND_HISTORY_FILE = REPO_DIR / "spend_history.json"


def detect_column(headers, candidates):
    """Find the first matching column name from a list of candidates."""
    h_lower = {h.lower().strip(): h for h in headers}
    for c in candidates:
        if c.lower() in h_lower:
            return h_lower[c.lower()]
    return None


def normalize_model_id(raw):
    """Normalize OpenRouter model slug to our model_id format."""
    raw = raw.strip()
    # Some exports include provider prefix already, some don't
    # e.g. "minimax/minimax-m2.7" or "minimax-m2.7" or "anthropic/claude-sonnet-4-6"
    return raw


def detect_provider(headers):
    """
    Auto-detect provider from CSV column names.
    Returns 'openrouter', 'anthropic', 'openai', or 'unknown'.
    """
    h = {x.lower().strip() for x in headers}
    if 'model_permaslug' in h or 'native_tokens_prompt' in h:
        return 'openrouter'
    if 'cache_creation_input_tokens' in h or 'cache_read_input_tokens' in h:
        return 'anthropic'
    if 'n_context_tokens_total' in h or 'n_generated_tokens_total' in h or 'snapshot_id' in h:
        return 'openai'
    # Fallback heuristics
    if 'prompt_tokens' in h and 'model' in h:
        return 'openrouter'
    return 'unknown'


def parse_csv(path, provider_hint=None):
    """
    Parse provider activity CSV, return list of row dicts.
    Auto-detects provider from column names unless provider_hint is given.
    Each returned row: {model_id, input_tokens, output_tokens, cache_read_tokens, cost, date, calls}
    """
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        raw_rows = list(reader)

    provider = provider_hint or detect_provider(headers)
    print(f"  Provider detected: {provider}")

    # ── Column maps by provider ────────────────────────────────────────────
    if provider == 'anthropic':
        # console.anthropic.com export — daily aggregates
        # Typical cols: date, model, input_tokens, output_tokens,
        #   cache_creation_input_tokens, cache_read_input_tokens, cost
        model_col = detect_column(headers, ['model', 'Model'])
        input_col = detect_column(headers, ['input_tokens', 'Input Tokens'])
        output_col = detect_column(headers, ['output_tokens', 'Output Tokens'])
        cache_read_col = detect_column(headers, ['cache_read_input_tokens', 'cache_read_tokens', 'Cache Read Tokens'])
        cost_col = detect_column(headers, ['cost', 'Cost', 'total_cost'])
        date_col = detect_column(headers, ['date', 'Date', 'period'])
        requests_col = detect_column(headers, ['requests', 'request_count', 'num_requests'])
        slug_prefix = 'anthropic/'

    elif provider == 'openai':
        # platform.openai.com export — daily aggregates
        # Typical cols: date, snapshot_id (model), n_context_tokens_total, n_generated_tokens_total
        model_col = detect_column(headers, ['snapshot_id', 'model', 'Model', 'model_id'])
        input_col = detect_column(headers, ['n_context_tokens_total', 'input_tokens', 'prompt_tokens'])
        output_col = detect_column(headers, ['n_generated_tokens_total', 'output_tokens', 'completion_tokens'])
        cache_read_col = detect_column(headers, ['cached_context_tokens', 'cache_read_tokens'])
        cost_col = detect_column(headers, ['cost', 'Cost', 'total_cost', 'usage_usd'])
        date_col = detect_column(headers, ['date', 'Date', 'timestamp'])
        requests_col = detect_column(headers, ['n_requests', 'requests', 'request_count'])
        slug_prefix = 'openai/'

    else:
        # OpenRouter — per-call rows or daily aggregates
        model_col = detect_column(headers, ['model', 'model_permaslug', 'slug', 'model_id', 'Model'])
        input_col = detect_column(headers, ['prompt_tokens', 'input_tokens', 'tokens_prompt', 'Input Tokens'])
        output_col = detect_column(headers, ['completion_tokens', 'output_tokens', 'tokens_completion', 'Output Tokens'])
        cache_read_col = detect_column(headers, ['cache_read_tokens', 'cached_tokens', 'Cache Read Tokens', 'native_tokens_cached'])
        cost_col = detect_column(headers, ['usage', 'cost', 'total_cost', 'cost_usd', 'Cost'])
        date_col = detect_column(headers, ['created_at', 'date', 'timestamp', 'Date'])
        requests_col = detect_column(headers, ['requests', 'request_count', 'num_requests'])
        slug_prefix = ''

    if not model_col:
        print(f"ERROR: Could not find model column. Headers: {headers}")
        sys.exit(1)
    if not cost_col:
        print(f"ERROR: Could not find cost column. Headers: {headers}")
        sys.exit(1)

    print(f"  Columns: model={model_col}, input={input_col}, output={output_col}, cost={cost_col}, date={date_col}")

    rows = []
    for row in raw_rows:
        raw_model = (row.get(model_col) or '').strip()
        if not raw_model:
            continue
        # Normalize: prepend provider prefix if not already present
        model_id = normalize_model_id(raw_model)
        if slug_prefix and not model_id.startswith(slug_prefix.rstrip('/')):
            model_id = slug_prefix + model_id

        # Date: extract YYYY-MM-DD from any timestamp format
        raw_date = (row.get(date_col) or '') if date_col else ''
        date = raw_date[:10] if raw_date else ''

        # Calls: use explicit count column if present, otherwise 1 per row
        calls = int(row.get(requests_col) or 1) if requests_col else 1

        rows.append({
            'model_id': model_id,
            'input_tokens': int(float(row.get(input_col) or 0)) if input_col else 0,
            'output_tokens': int(float(row.get(output_col) or 0)) if output_col else 0,
            'cache_read_tokens': int(float(row.get(cache_read_col) or 0)) if cache_read_col else 0,
            'cost': float(row.get(cost_col) or 0),
            'date': date,
            'calls': calls,
        })
    return rows, provider


def aggregate(rows):
    """
    Aggregate rows by model_id (totals) and by (model_id, date) (daily).
    Returns (totals_dict, daily_dict).
    """
    totals = defaultdict(lambda: {
        'total_cost_usd': 0.0,
        'total_input_tokens': 0,
        'total_output_tokens': 0,
        'total_cache_read_tokens': 0,
        'call_count': 0,
        'dates': [],
    })
    # daily[model_id][date] = {cost_usd, input_tokens, output_tokens, calls}
    daily = defaultdict(lambda: defaultdict(lambda: {
        'cost_usd': 0.0, 'input_tokens': 0, 'output_tokens': 0, 'calls': 0
    }))
    for row in rows:
        mid = row['model_id']
        if not mid:
            continue
        calls = row.get('calls', 1)
        totals[mid]['total_cost_usd'] += row['cost']
        totals[mid]['total_input_tokens'] += row['input_tokens']
        totals[mid]['total_output_tokens'] += row['output_tokens']
        totals[mid]['total_cache_read_tokens'] += row['cache_read_tokens']
        totals[mid]['call_count'] += calls
        date = row['date'][:10] if row.get('date') else ''
        if date:
            totals[mid]['dates'].append(date)
            daily[mid][date]['cost_usd'] += row['cost']
            daily[mid][date]['input_tokens'] += row['input_tokens']
            daily[mid][date]['output_tokens'] += row['output_tokens']
            daily[mid][date]['calls'] += calls
    return dict(totals), {k: dict(v) for k, v in daily.items()}


def write_daily_history(daily, source='csv-import'):
    """
    Merge per-day data into spend_history.json.
    daily: {model_id: {date_str: {cost_usd, input_tokens, output_tokens, calls}}}
    Existing entries for a date are overwritten (import is authoritative).
    """
    history = {}
    if SPEND_HISTORY_FILE.exists():
        try:
            history = json.loads(SPEND_HISTORY_FILE.read_text())
        except Exception:
            pass

    updated = 0
    for model_id, days in daily.items():
        existing = {entry['date']: entry for entry in history.get(model_id, [])}
        for date, data in days.items():
            if not date:
                continue
            existing[date] = {
                'date': date,
                'cost_usd': round(data['cost_usd'], 8),
                'input_tokens': data['input_tokens'],
                'output_tokens': data['output_tokens'],
                'calls': data['calls'],
                'source': source,
            }
            updated += 1
        history[model_id] = sorted(existing.values(), key=lambda x: x['date'])

    SPEND_HISTORY_FILE.write_text(json.dumps(history, indent=2) + '\n')
    return updated


def match_model(model_id, existing_models):
    """Match a CSV model_id to an existing model record."""
    # Exact match
    for m in existing_models:
        if m['model_id'] == model_id:
            return m
    # Match by openrouter_slug
    for m in existing_models:
        if m.get('openrouter_slug') == model_id:
            return m
    # Partial match (provider/name substring)
    for m in existing_models:
        if model_id in m['model_id'] or m['model_id'] in model_id:
            return m
    return None


def main():
    parser = argparse.ArgumentParser(description="Import provider spend CSV into model records and daily history")
    parser.add_argument("csv_file", help="Path to activity CSV (OpenRouter, Anthropic, or OpenAI)")
    parser.add_argument("--apply", action="store_true", help="Write to models.json + spend_history.json")
    parser.add_argument("--history-only", action="store_true", help="Only update spend_history.json (skip models.json)")
    parser.add_argument("--show", action="store_true", help="Print summary only, write nothing")
    parser.add_argument("--provider", choices=["openrouter", "anthropic", "openai"],
                        help="Force provider format (auto-detected by default)")
    args = parser.parse_args()

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"ERROR: File not found: {csv_path}")
        sys.exit(1)

    print(f"Parsing {csv_path.name}...")
    rows, provider = parse_csv(csv_path, provider_hint=args.provider)
    print(f"  {len(rows)} rows loaded")

    totals, daily = aggregate(rows)
    total_spend = sum(v['total_cost_usd'] for v in totals.values())
    total_days = sum(len(d) for d in daily.values())

    # Summary table
    print(f"\n{'Model':<55} {'Calls':>6} {'Days':>5} {'Input MTok':>10} {'Output MTok':>11} {'Cost':>10}")
    print("-" * 105)
    for mid, data in sorted(totals.items(), key=lambda x: -x[1]['total_cost_usd']):
        days = len(daily.get(mid, {}))
        print(f"{mid:<55} {data['call_count']:>6} {days:>5} "
              f"{data['total_input_tokens']/1e6:>10.2f} "
              f"{data['total_output_tokens']/1e6:>11.2f} "
              f"${data['total_cost_usd']:>9.4f}")
    print("-" * 105)
    print(f"{'TOTAL':<55} {sum(v['call_count'] for v in totals.values()):>6} {total_days:>5} "
          f"{sum(v['total_input_tokens'] for v in totals.values())/1e6:>10.2f} "
          f"{sum(v['total_output_tokens'] for v in totals.values())/1e6:>11.2f} "
          f"${total_spend:>9.4f}")
    print(f"\n  {len(daily)} models with daily data · {total_days} model-day entries")

    if args.show:
        return

    write = args.apply or args.history_only
    if not write:
        print("\n[DRY RUN] Pass --apply to write. Pass --history-only to only update trend charts.")
        return

    # ── Write daily history ────────────────────────────────────────────────
    source = f'{provider}-csv-import'
    hist_entries = write_daily_history(daily, source=source)
    print(f"\nspend_history.json: {hist_entries} model-day entries written ({len(daily)} models)")

    if args.history_only:
        return

    # ── Match and write totals to models.json ─────────────────────────────
    existing = json.loads(MODELS_FILE.read_text())
    matched = 0
    unmatched = []

    for mid, data in totals.items():
        m = match_model(mid, existing)
        if m:
            dates = sorted(set(data['dates']))
            avg_cost = round(data['total_cost_usd'] / max(data['call_count'], 1), 6)
            m['spend'] = {
                'total_cost_usd': round(data['total_cost_usd'], 6),
                'total_input_mtok': round(data['total_input_tokens'] / 1e6, 4),
                'total_output_mtok': round(data['total_output_tokens'] / 1e6, 4),
                'total_cache_read_mtok': round(data['total_cache_read_tokens'] / 1e6, 4),
                'call_count': data['call_count'],
                'avg_cost_per_call_usd': avg_cost,
                'period_start': dates[0] if dates else '',
                'period_end': dates[-1] if dates else '',
                'source': source,
                'imported_at': datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            }
            matched += 1
        else:
            unmatched.append(mid)

    if unmatched:
        print(f"\nUnmatched models ({len(unmatched)}):")
        for u in unmatched[:10]:
            print(f"  {u}")
        if len(unmatched) > 10:
            print(f"  … and {len(unmatched)-10} more")

    MODELS_FILE.write_text(json.dumps(existing, indent=2) + "\n")
    print(f"models.json: {matched} models updated with spend totals")


if __name__ == "__main__":
    main()
