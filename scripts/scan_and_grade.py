#!/usr/bin/env python3
"""
scan_and_grade.py — Hourly job. Walks agent session indexes, filters to recent
sessions, classifies each as multi-step or not, grades multi-step ones, attributes
to the model in use, and appends trials to each model's _meta.our_observations.

Pass-rate is recomputed from the rolling trial window (default 30 days).

Writes to: models/active.json and models.json (mirrored for UI).

Usage:
  python3 scripts/scan_and_grade.py                     # dry run (default)
  python3 scripts/scan_and_grade.py --apply             # write
  python3 scripts/scan_and_grade.py --window-days 30
  python3 scripts/scan_and_grade.py --since 2026-04-10  # grade only newer sessions
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
ACTIVE_FILE = REPO_DIR / "models" / "active.json"
MODELS_FILE = REPO_DIR / "models.json"
AGENTS_DIR = Path.home() / ".openclaw" / "agents"
AGENTS = ["build", "strategy", "general", "sage"]  # tracked agents

sys.path.insert(0, str(Path(__file__).parent))
from classify_multistep import classify  # noqa
from grade_run import grade  # noqa
from active_model_at import resolve, AGENT_ROLE  # noqa

TODAY = datetime.now(tz=timezone.utc)


def _parse_ts_ms(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e12 else v, tz=timezone.utc)
    if isinstance(v, str):
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return None
    return None


def load_sessions(agent: str) -> list[dict]:
    idx = AGENTS_DIR / agent / "sessions" / "sessions.json"
    if not idx.exists():
        return []
    try:
        d = json.loads(idx.read_text())
    except json.JSONDecodeError:
        return []
    out = []
    for key, rec in d.items():
        if key == "global" or not isinstance(rec, dict):
            continue
        sf = rec.get("sessionFile")
        if not sf:
            continue
        out.append({
            "agent": agent,
            "session_key": key,
            "session_id": rec.get("sessionId"),
            "session_file": sf,
            "status": rec.get("status"),
            "aborted": bool(rec.get("abortedLastRun")),
            "started_at": _parse_ts_ms(rec.get("startedAt")),
            "ended_at": _parse_ts_ms(rec.get("endedAt") or rec.get("updatedAt")),
            "model": rec.get("model"),
            "model_provider": rec.get("modelProvider"),
            "run_id": rec.get("sessionId"),
        })
    return out


def process_sessions(since: datetime | None) -> list[dict]:
    trials = []
    for agent in AGENTS:
        for sess in load_sessions(agent):
            if since and sess["ended_at"] and sess["ended_at"] < since:
                continue
            path = Path(sess["session_file"])
            if not path.exists():
                continue
            cls = classify(path)
            if not cls.get("is_multi_step"):
                continue
            end_iso = sess["ended_at"].isoformat() if sess["ended_at"] else None
            g = grade(path, status=sess["status"], aborted=sess["aborted"], ended_at=end_iso)
            ref_ts = sess["ended_at"] or sess["started_at"] or TODAY
            attr = resolve(agent, ref_ts)
            trials.append({
                "model_id": attr["model_id"],
                "agent": agent,
                "agent_role": attr["role"],
                "date": ref_ts.strftime("%Y-%m-%d"),
                "run_id": sess["run_id"],
                "session_id": sess["session_id"],
                "result": g["result"],
                "failure_point": g.get("failure_point"),
                "reason": g.get("reason"),
                "action_calls": g.get("action_calls"),
                "destinations": g.get("destinations"),
                "duration_sec": int((sess["ended_at"] - sess["started_at"]).total_seconds())
                    if sess["ended_at"] and sess["started_at"] else None,
            })
    return trials


def upsert_trials(record: dict, trials_for_model: list[dict], window_days: int):
    meta = record.setdefault("_meta", {})
    obs = meta.setdefault("our_observations", {})
    existing = obs.setdefault("trials", [])
    seen = {t.get("run_id") for t in existing if t.get("run_id")}
    for t in trials_for_model:
        rid = t.get("run_id")
        if rid and rid in seen:
            continue
        existing.append({
            "date": t["date"],
            "agent": t["agent"],
            "agent_role": t["agent_role"],
            "result": t["result"],
            "failure_point": t["failure_point"],
            "reason": t["reason"],
            "session_id": t["session_id"],
            "run_id": t["run_id"],
            "notes": f"{t['action_calls']} actions across {','.join(t['destinations'] or [])}"
                     + (f"; {t['duration_sec']}s" if t["duration_sec"] else ""),
        })
        if rid:
            seen.add(rid)
    # Prune trials older than 2 * window_days to cap growth
    cutoff = (TODAY - timedelta(days=window_days * 2)).strftime("%Y-%m-%d")
    existing[:] = [t for t in existing if t.get("date", "") >= cutoff]
    # Compute rolling pass_rate
    cutoff_rolling = (TODAY - timedelta(days=window_days)).strftime("%Y-%m-%d")
    in_window = [t for t in existing if t.get("date", "") >= cutoff_rolling]
    obs["pass_rate"] = _compute_pass_rate(in_window, window_days)


def _compute_pass_rate(trials: list[dict], window_days: int) -> dict:
    if not trials:
        return {
            "builder": None, "strategy": None, "gm": None, "sage": None,
            "overall": None, "sample_size": 0, "window_days": window_days,
            "computed_at": TODAY.strftime("%Y-%m-%d"),
        }
    def rate(subset):
        if not subset:
            return None
        passed = sum(1 for t in subset if t["result"] == "pass")
        return round(passed / len(subset), 3)
    by_role = {r: [t for t in trials if t.get("agent_role") == r]
               for r in ("builder", "strategy", "gm", "sage")}
    return {
        "builder": rate(by_role["builder"]),
        "strategy": rate(by_role["strategy"]),
        "gm": rate(by_role["gm"]),
        "sage": rate(by_role["sage"]),
        "overall": rate(trials),
        "sample_size": len(trials),
        "window_days": window_days,
        "computed_at": TODAY.strftime("%Y-%m-%d"),
    }


def write_trials(all_trials: list[dict], apply: bool, window_days: int) -> dict:
    # group by model_id
    by_model: dict[str, list[dict]] = {}
    for t in all_trials:
        if not t["model_id"]:
            continue
        by_model.setdefault(t["model_id"], []).append(t)

    summary = {"files_updated": 0, "models_touched": 0}
    for path in (ACTIVE_FILE, MODELS_FILE):
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        touched_in_file = 0
        for record in data:
            mid = record.get("model_id")
            trials = by_model.get(mid)
            if not trials:
                # still refresh pass_rate so stale counts decay
                upsert_trials(record, [], window_days)
                continue
            upsert_trials(record, trials, window_days)
            touched_in_file += 1
        if touched_in_file and apply:
            path.write_text(json.dumps(data, indent=2) + "\n")
            summary["files_updated"] += 1
            summary["models_touched"] = max(summary["models_touched"], touched_in_file)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--since", default=None, help="Only grade sessions ending on/after this date (YYYY-MM-DD)")
    args = p.parse_args()

    since = None
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    print(f"Scanning {len(AGENTS)} agents... window={args.window_days}d since={args.since}")
    trials = process_sessions(since)
    print(f"  classified + graded {len(trials)} multi-step sessions")

    by_result = {"pass": 0, "fail": 0}
    by_fp: dict[str, int] = {}
    for t in trials:
        by_result[t["result"]] += 1
        if t["failure_point"]:
            by_fp[t["failure_point"]] = by_fp.get(t["failure_point"], 0) + 1
    print(f"  result: {by_result}")
    if by_fp:
        print(f"  failure points: {by_fp}")

    summary = write_trials(trials, args.apply, args.window_days)
    print(f"Summary: {summary}")
    if not args.apply:
        print("[DRY RUN] Pass --apply to write changes.")


if __name__ == "__main__":
    main()
