#!/usr/bin/env python3
"""
import_spend.py — Import OpenRouter activity CSV and attach spend data to models

Usage:
  python3 scripts/import_spend.py openrouter_activity.csv
  python3 scripts/import_spend.py openrouter_activity.csv --apply   # write to models.json
  python3 scripts/import_spend.py openrouter_activity.csv --show    # just print summary

OpenRouter CSV columns (auto-detected):
  The CSV may have various column names. This script tries common variants.
  Expected: model/slug, input_tokens, output_tokens, cost/total_cost, date/created_at

Download your CSV from: https://openrouter.ai/activity (CSV export button)
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


def parse_csv(path):
    """Parse OpenRouter activity CSV, return list of row dicts."""
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        # Detect columns
        model_col = detect_column(headers, ['model', 'slug', 'model_id', 'model_slug', 'Model'])
        input_col = detect_column(headers, ['input_tokens', 'prompt_tokens', 'input', 'tokens_prompt', 'Input Tokens'])
        output_col = detect_column(headers, ['output_tokens', 'completion_tokens', 'output', 'tokens_completion', 'Output Tokens'])
        cost_col = detect_column(headers, ['cost', 'total_cost', 'cost_usd', 'price', 'Cost', 'Total Cost'])
        date_col = detect_column(headers, ['date', 'created_at', 'timestamp', 'Date', 'Created At'])
        cache_read_col = detect_column(headers, ['cache_read_tokens', 'cached_tokens', 'cache_tokens', 'Cache Read Tokens'])

        if not model_col:
            print(f"ERROR: Could not find model column. Headers found: {headers}")
            sys.exit(1)
        if not cost_col:
            print(f"ERROR: Could not find cost column. Headers found: {headers}")
            sys.exit(1)

        print(f"Columns detected:")
        print(f"  model={model_col}, input={input_col}, output={output_col}")
        print(f"  cost={cost_col}, date={date_col}, cache_read={cache_read_col}")

        rows = []
        for row in reader:
            rows.append({
                'model_id': normalize_model_id(row.get(model_col, '')),
                'input_tokens': int(row.get(input_col, 0) or 0) if input_col else 0,
                'output_tokens': int(row.get(output_col, 0) or 0) if output_col else 0,
                'cache_read_tokens': int(row.get(cache_read_col, 0) or 0) if cache_read_col else 0,
                'cost': float(row.get(cost_col, 0) or 0),
                'date': row.get(date_col, '') if date_col else '',
            })
        return rows


def aggregate(rows):
    """Aggregate rows by model_id."""
    agg = defaultdict(lambda: {
        'total_cost_usd': 0.0,
        'total_input_tokens': 0,
        'total_output_tokens': 0,
        'total_cache_read_tokens': 0,
        'call_count': 0,
        'dates': [],
    })
    for row in rows:
        mid = row['model_id']
        if not mid:
            continue
        agg[mid]['total_cost_usd'] += row['cost']
        agg[mid]['total_input_tokens'] += row['input_tokens']
        agg[mid]['total_output_tokens'] += row['output_tokens']
        agg[mid]['total_cache_read_tokens'] += row['cache_read_tokens']
        agg[mid]['call_count'] += 1
        if row['date']:
            agg[mid]['dates'].append(row['date'])
    return dict(agg)


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
    parser = argparse.ArgumentParser(description="Import OpenRouter spend CSV into model records")
    parser.add_argument("csv_file", help="Path to OpenRouter activity CSV")
    parser.add_argument("--apply", action="store_true", help="Write spend data to models.json")
    parser.add_argument("--show", action="store_true", help="Print spend summary only")
    args = parser.parse_args()

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"ERROR: File not found: {csv_path}")
        sys.exit(1)

    print(f"Parsing {csv_path.name}...")
    rows = parse_csv(csv_path)
    print(f"  {len(rows)} rows loaded")

    agg = aggregate(rows)
    total_spend = sum(v['total_cost_usd'] for v in agg.values())

    # Print summary sorted by cost
    print(f"\n{'Model':<55} {'Calls':>6} {'Input MTok':>10} {'Output MTok':>11} {'Cache MTok':>10} {'Cost':>10}")
    print("-" * 110)
    for mid, data in sorted(agg.items(), key=lambda x: -x[1]['total_cost_usd']):
        in_mtok = data['total_input_tokens'] / 1_000_000
        out_mtok = data['total_output_tokens'] / 1_000_000
        cache_mtok = data['total_cache_read_tokens'] / 1_000_000
        print(f"{mid:<55} {data['call_count']:>6} {in_mtok:>10.2f} {out_mtok:>11.2f} {cache_mtok:>10.2f} ${data['total_cost_usd']:>9.4f}")
    print("-" * 110)
    print(f"{'TOTAL':<55} {sum(v['call_count'] for v in agg.values()):>6} "
          f"{sum(v['total_input_tokens'] for v in agg.values())/1e6:>10.2f} "
          f"{sum(v['total_output_tokens'] for v in agg.values())/1e6:>11.2f} "
          f"{'':>10} ${total_spend:>9.4f}")

    if args.show:
        return

    # Match to existing models
    existing = json.loads(MODELS_FILE.read_text())
    matched = 0
    unmatched = []

    for mid, data in agg.items():
        m = match_model(mid, existing)
        if m:
            dates = sorted(data['dates'])
            in_mtok = round(data['total_input_tokens'] / 1_000_000, 4)
            out_mtok = round(data['total_output_tokens'] / 1_000_000, 4)
            cache_mtok = round(data['total_cache_read_tokens'] / 1_000_000, 4)
            avg_cost_per_call = round(data['total_cost_usd'] / max(data['call_count'], 1), 6)

            m['spend'] = {
                'total_cost_usd': round(data['total_cost_usd'], 6),
                'total_input_mtok': in_mtok,
                'total_output_mtok': out_mtok,
                'total_cache_read_mtok': cache_mtok,
                'call_count': data['call_count'],
                'avg_cost_per_call_usd': avg_cost_per_call,
                'period_start': dates[0] if dates else '',
                'period_end': dates[-1] if dates else '',
                'imported_at': datetime.now(tz=timezone.utc).strftime('%Y-%m-%d'),
            }
            matched += 1
        else:
            unmatched.append(mid)

    print(f"\nMatched {matched} models, {len(unmatched)} unmatched:")
    for u in unmatched[:20]:
        print(f"  {u}")

    if not args.apply:
        print("\n[DRY RUN] Pass --apply to write spend data to models.json")
        return

    MODELS_FILE.write_text(json.dumps(existing, indent=2) + "\n")
    print(f"\nWrote spend data to {MODELS_FILE.name}")
    print(f"  {matched} models updated with spend history")


if __name__ == "__main__":
    main()
