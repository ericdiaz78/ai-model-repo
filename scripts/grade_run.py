#!/usr/bin/env python3
"""
grade_run.py — Score a multi-step OpenClaw session pass/fail and, on failure,
attach a failure-point code.

Taxonomy:
  FP1 no_context      — session had no meaningful input or ran <1 real tool call
  FP2 silent          — agent made tool calls but produced no final user-facing reply
  FP3 no_artifacts    — agent acted but never touched a write/send/memory/plan destination
  FP4 abandoned_loop  — last activity >30 min ago AND session not marked completed
  FP5 duplicate       — same sessions_send payload sent twice consecutively to same dest
  FP6 crash           — session aborted, or repeated failing exec without recovery

Pass = multi-step AND closed the loop (>=1 artifact destination, final assistant
text, no crash, no abandoned loop, no duplicate send).

Usage:
  python3 scripts/grade_run.py <session.jsonl> [--status <status>] [--aborted <0|1>] [--ended-at <iso>]
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ACTION_TOOLS = {
    "write": "filesystem",
    "edit": "filesystem",
    "notebook_edit": "filesystem",
    "sessions_send": "message",
    "sessions_spawn": "subagent",
    "sessions_yield": "message",
    "memory_set": "memory",
    "memory_write": "memory",
    "memory_delete": "memory",
    "update_plan": "plan",
    "exec": "shell",
    "process": "shell",
    "web_fetch": "shell",
}


def _parse_ts(ts):
    if not ts:
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, tz=timezone.utc)
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def analyze(session_jsonl: Path) -> dict:
    """Walk the JSONL once, collect every signal the grader needs."""
    total_tool_calls = 0
    action_calls = 0
    destinations = set()
    assistant_text_count = 0
    last_block_type = None
    last_block_role = None
    last_ts = None
    first_ts = None
    last_exec_returncode = None
    consecutive_exec_failures = 0
    max_consecutive_exec_failures = 0
    duplicate_send = False
    prev_send_sig = None
    prev_send_ts = None
    DUP_WINDOW_SEC = 600  # 10 min — tighter gap catches loop-stuck repeats,
                          # not legitimate periodic status updates
    models_used = set()

    try:
        fh = session_jsonl.open()
    except FileNotFoundError:
        return {"error": "session_file_missing", "path": str(session_jsonl)}

    with fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("type") != "message":
                continue
            ts = _parse_ts(r.get("timestamp"))
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
            msg = r.get("message", {}) or {}
            role = msg.get("role")
            if role == "assistant" and msg.get("model"):
                models_used.add(msg["model"])
            content = msg.get("content") or []
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                ct = c.get("type")
                last_block_type = ct
                last_block_role = role
                if ct == "toolCall":
                    total_tool_calls += 1
                    name = c.get("name", "")
                    dest = ACTION_TOOLS.get(name)
                    if dest:
                        action_calls += 1
                        destinations.add(dest)
                    if name == "sessions_send":
                        args = c.get("arguments") or {}
                        to = args.get("to") or args.get("session") or args.get("recipient")
                        body = args.get("text") or args.get("message") or args.get("content") or ""
                        sig = (to, str(body)[:500])
                        if prev_send_sig and sig == prev_send_sig and prev_send_ts and ts:
                            gap = (ts - prev_send_ts).total_seconds()
                            if 0 <= gap <= DUP_WINDOW_SEC:
                                duplicate_send = True
                        prev_send_sig = sig
                        prev_send_ts = ts
                elif ct == "toolResult":
                    # exec tool results often embed JSON with returncode
                    raw = c.get("content") if isinstance(c.get("content"), str) else json.dumps(c.get("content", ""))
                    rc = None
                    if "returncode" in raw:
                        # heuristic: look for non-zero returncode
                        for token in raw.split("returncode"):
                            token = token.strip(" :\"'")
                            if token[:4].lstrip("-").isdigit() or token[:2] in ("0,", "1,", "2,"):
                                try:
                                    rc = int(token.split(",")[0].split("}")[0].strip(" :\"'"))
                                except ValueError:
                                    rc = None
                                break
                    last_exec_returncode = rc
                    if rc is not None and rc != 0:
                        consecutive_exec_failures += 1
                        max_consecutive_exec_failures = max(
                            max_consecutive_exec_failures, consecutive_exec_failures
                        )
                    else:
                        consecutive_exec_failures = 0
                elif ct == "text":
                    if role == "assistant":
                        assistant_text_count += 1
                        # only non-empty counts
                        if not (c.get("text") or "").strip():
                            assistant_text_count -= 1

    return {
        "path": str(session_jsonl),
        "total_tool_calls": total_tool_calls,
        "action_calls": action_calls,
        "destinations": sorted(destinations),
        "assistant_text_blocks": assistant_text_count,
        "last_block_type": last_block_type,
        "last_block_role": last_block_role,
        "first_ts": first_ts.isoformat() if first_ts else None,
        "last_ts": last_ts.isoformat() if last_ts else None,
        "duplicate_send": duplicate_send,
        "max_consecutive_exec_failures": max_consecutive_exec_failures,
        "models_used": sorted(models_used),
    }


def grade(session_jsonl: Path, *, status: str | None = None, aborted: bool = False,
          ended_at: str | None = None, stale_threshold_min: int = 30) -> dict:
    ana = analyze(session_jsonl)
    if "error" in ana:
        return {**ana, "result": "fail", "failure_point": "FP1", "reason": "session_file_missing"}

    now = datetime.now(tz=timezone.utc)
    last_ts = _parse_ts(ana["last_ts"])
    ended = _parse_ts(ended_at)
    effective_last = ended or last_ts

    # FP6 crash
    if aborted:
        return _verdict(ana, "fail", "FP6", "session_aborted")
    if ana["max_consecutive_exec_failures"] >= 3:
        return _verdict(ana, "fail", "FP6", "repeated_exec_failures_no_recovery")

    # FP1 no context
    if ana["total_tool_calls"] == 0 and ana["assistant_text_blocks"] == 0:
        return _verdict(ana, "fail", "FP1", "no_tools_no_reply")
    if ana["total_tool_calls"] < 2 and ana["assistant_text_blocks"] == 0:
        return _verdict(ana, "fail", "FP1", "insufficient_activity")

    # FP5 duplicate
    if ana["duplicate_send"]:
        return _verdict(ana, "fail", "FP5", "consecutive_duplicate_send")

    # FP4 abandoned loop
    if status and status not in ("completed", "idle", "ready"):
        if effective_last and (now - effective_last).total_seconds() / 60 > stale_threshold_min:
            return _verdict(ana, "fail", "FP4", f"stale_{int((now-effective_last).total_seconds()/60)}min_status_{status}")

    # FP3 no artifacts
    if ana["action_calls"] == 0:
        return _verdict(ana, "fail", "FP3", "no_write_or_send")

    # FP2 silent — acted but never produced a final user-facing reply
    # Heuristic: the very last assistant block was a toolCall, not text.
    if ana["last_block_role"] == "assistant" and ana["last_block_type"] == "toolCall":
        return _verdict(ana, "fail", "FP2", "ended_on_toolcall_no_reply")
    if ana["assistant_text_blocks"] == 0:
        return _verdict(ana, "fail", "FP2", "no_assistant_text")

    return _verdict(ana, "pass", None, "loop_closed")


def _verdict(ana: dict, result: str, fp: str | None, reason: str) -> dict:
    return {
        **ana,
        "result": result,
        "failure_point": fp,
        "reason": reason,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session")
    p.add_argument("--status", default=None)
    p.add_argument("--aborted", type=int, default=0)
    p.add_argument("--ended-at", default=None)
    args = p.parse_args()

    out = grade(Path(args.session), status=args.status, aborted=bool(args.aborted), ended_at=args.ended_at)
    print(json.dumps(out, indent=2))
    sys.exit(0 if out.get("result") == "pass" else 2)


if __name__ == "__main__":
    main()
