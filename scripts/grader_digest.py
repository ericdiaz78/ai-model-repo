#!/usr/bin/env python3
"""
grader_digest.py — Summarize the last N days of hourly grader logs and post a
digest to Slack #build.

Reads: /home/ericd/.openclaw/logs/ai-model-repo-grader/YYYY-MM-DD.log
Posts: one-line summary + optional top-failure-points breakdown
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

LOG_DIR = Path("/home/ericd/.openclaw/logs/ai-model-repo-grader")
OPENCLAW_CFG = Path("/home/ericd/.openclaw/openclaw.json")
BUILD_CHANNEL = "C0AGMCJENRY"

RESULT_RE = re.compile(r"result:\s*\{([^}]+)\}")
FP_RE = re.compile(r"failure points:\s*\{([^}]+)\}")
GRADED_RE = re.compile(r"graded\s+(\d+)\s+multi-step")


def parse_counts(line: str, pattern: re.Pattern) -> dict:
    m = pattern.search(line)
    if not m:
        return {}
    out = {}
    for part in m.group(1).split(","):
        part = part.strip()
        if not part:
            continue
        k, _, v = part.partition(":")
        k = k.strip().strip("'\"")
        try:
            out[k] = int(v.strip())
        except ValueError:
            pass
    return out


def collect(days: int) -> dict:
    today = datetime.now(timezone.utc).date()
    files = []
    for i in range(days):
        d = today - timedelta(days=i)
        p = LOG_DIR / f"{d.isoformat()}.log"
        if p.exists():
            files.append(p)

    runs = []  # list of (timestamp_iso, graded, result_counts, fp_counts)
    current_ts = None
    for f in sorted(files):
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("==="):
                m = re.search(r"===\s*(\S+)\s+grade_hourly", line)
                current_ts = m.group(1) if m else None
                continue
            if line.startswith("result:"):
                result = parse_counts(line, RESULT_RE)
                runs.append({
                    "ts": current_ts,
                    "result": result,
                    "fps": {},
                })
            elif line.startswith("failure points:"):
                if runs:
                    runs[-1]["fps"] = parse_counts(line, FP_RE)

    return {"runs": runs, "days": days}


def summarize(data: dict) -> str:
    runs = data["runs"]
    if not runs:
        return f"Grader digest: no log entries in last {data['days']} days."

    first = runs[0]
    last = runs[-1]
    first_pass = first["result"].get("pass", 0)
    first_fail = first["result"].get("fail", 0)
    last_pass = last["result"].get("pass", 0)
    last_fail = last["result"].get("fail", 0)
    first_total = first_pass + first_fail
    last_total = last_pass + last_fail

    pct_first = (100 * first_pass / first_total) if first_total else 0
    pct_last = (100 * last_pass / last_total) if last_total else 0
    delta = pct_last - pct_first

    fp_totals = Counter()
    for r in runs:
        for k, v in r["fps"].items():
            fp_totals[k] += v
    top_fp = fp_totals.most_common(3)

    arrow = "→"
    trend = f"{pct_first:.0f}% {arrow} {pct_last:.0f}% ({delta:+.0f}pts)"
    top_str = ", ".join(f"{k}={v}" for k, v in top_fp) if top_fp else "none"

    lines = [
        f"Grader {data['days']}-day digest:",
        f"  Pass rate: {trend}",
        f"  Latest: {last_pass}/{last_total} passing ({last['ts']})",
        f"  Failure modes (total occurrences across {len(runs)} runs): {top_str}",
    ]
    return "\n".join(lines)


def post_slack(text: str, dry_run: bool = False):
    if dry_run:
        print("[DRY RUN] Would post to Slack:")
        print(text)
        return
    import urllib.request
    cfg = json.loads(OPENCLAW_CFG.read_text())
    token = cfg["channels"]["slack"]["accounts"]["alexander"]["botToken"]
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": BUILD_CHANNEL, "text": text}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
        if not body.get("ok"):
            raise SystemExit(f"Slack error: {body}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = collect(args.days)
    text = summarize(data)
    post_slack(text, dry_run=args.dry_run)
    if not args.dry_run:
        print(text)


if __name__ == "__main__":
    main()
