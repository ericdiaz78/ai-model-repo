#!/usr/bin/env bash
# grade_hourly.sh — run the grader over the last ~48h of sessions and write results.
# Intended to be called from crontab every hour. Safe to run more often.
set -euo pipefail

REPO="/home/ericd/.openclaw/workspace-alexander/ai-model-repo"
LOG="/home/ericd/.openclaw/logs/ai-model-repo-grader"
mkdir -p "$LOG"

SINCE=$(date -u -d '2 days ago' +%Y-%m-%d)
OUT="$LOG/$(date -u +%Y-%m-%d).log"

cd "$REPO"
{
  echo "=== $(date -u +%FT%TZ) grade_hourly ==="
  python3 scripts/scan_and_grade.py --since "$SINCE" --apply
  echo
} >> "$OUT" 2>&1
