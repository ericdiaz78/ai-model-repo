#!/usr/bin/env python3
"""
classify_multistep.py — Decide whether an OpenClaw session counts as a multi-step run.

Rule (all three must hold):
  1. >=2 dependent actions: at least 2 write/edit/send/spawn/exec tool calls
     (reads alone don't chain meaningfully)
  2. >=2 distinct artifact destinations: at least 2 different destination kinds
     among {filesystem, message, memory, plan, shell, subagent}
  3. Agent chose what to do: at least 1 thinking block OR 1 update_plan call
     (otherwise the user drove every step — not agentic multi-step)

Single-step runs (a read, a classification, a one-shot reply) are excluded from
grading since they don't exercise the loop-closing behavior we care about.

Usage:
  python3 scripts/classify_multistep.py <session.jsonl>
  python3 scripts/classify_multistep.py --summary path/to/sessions.json
"""

import argparse
import json
import sys
from pathlib import Path

ACTION_TOOLS = {
    # writes to filesystem
    "write": "filesystem",
    "edit": "filesystem",
    "notebook_edit": "filesystem",
    # messages out
    "sessions_send": "message",
    "sessions_spawn": "subagent",
    "sessions_yield": "message",
    # memory
    "memory_set": "memory",
    "memory_write": "memory",
    "memory_delete": "memory",
    # plan
    "update_plan": "plan",
    # shell / external side-effects
    "exec": "shell",
    "process": "shell",
    "web_fetch": "shell",
}


def classify(session_jsonl: Path) -> dict:
    actions = 0
    destinations = set()
    thinking_blocks = 0
    plan_updates = 0
    any_tool_call = 0
    assistant_text_blocks = 0
    models_used = set()
    first_ts = None
    last_ts = None

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
            ts = r.get("timestamp")
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
                if ct == "toolCall":
                    any_tool_call += 1
                    name = c.get("name", "")
                    dest = ACTION_TOOLS.get(name)
                    if dest:
                        actions += 1
                        destinations.add(dest)
                    if name == "update_plan":
                        plan_updates += 1
                elif ct == "thinking":
                    thinking_blocks += 1
                elif ct == "text" and role == "assistant":
                    assistant_text_blocks += 1

    agent_chose = thinking_blocks >= 1 or plan_updates >= 1
    is_multi = (
        actions >= 2
        and len(destinations) >= 2
        and agent_chose
    )

    return {
        "path": str(session_jsonl),
        "is_multi_step": is_multi,
        "actions": actions,
        "destinations": sorted(destinations),
        "thinking_blocks": thinking_blocks,
        "plan_updates": plan_updates,
        "any_tool_call": any_tool_call,
        "assistant_text_blocks": assistant_text_blocks,
        "models_used": sorted(models_used),
        "first_ts": first_ts,
        "last_ts": last_ts,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session", help="Path to session JSONL file")
    args = p.parse_args()

    result = classify(Path(args.session))
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("is_multi_step") else 2)


if __name__ == "__main__":
    main()
