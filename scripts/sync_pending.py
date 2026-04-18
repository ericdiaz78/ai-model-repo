#!/usr/bin/env python3
"""
sync_pending.py — Polls Railway for pending model changes and applies locally.

Run periodically (cron or manual):
    python3 scripts/sync_pending.py

Requires:
    REPO_API_URL  — Railway app URL (e.g. https://ai-model-repo-production-385b.up.railway.app)
    REPO_API_TOKEN — API token matching Railway's API_TOKEN env var
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_API_URL = os.environ.get("REPO_API_URL", "https://ai-model-repo-production-385b.up.railway.app")
REPO_API_TOKEN = os.environ.get("REPO_API_TOKEN", "")
OPENCLAW_CONFIG = Path.home() / ".openclaw" / "openclaw.json"

try:
    import requests
except ImportError:
    print("ERROR: requests not installed", file=sys.stderr)
    sys.exit(1)


def fetch_pending() -> list[dict]:
    resp = requests.get(
        f"{REPO_API_URL}/api/pending-changes",
        headers={"X-API-Token": REPO_API_TOKEN},
        timeout=15,
    )
    resp.raise_for_status()
    return [c for c in resp.json() if c.get("status") == "pending"]


def ack_change(change_id: str):
    resp = requests.post(
        f"{REPO_API_URL}/api/pending-changes/{change_id}/ack",
        headers={"X-API-Token": REPO_API_TOKEN},
        timeout=15,
    )
    resp.raise_for_status()


def apply_change(change: dict) -> bool:
    agent_id = change["agent"]
    new_primary = change["new_primary"]
    new_fallbacks = change.get("new_fallbacks")

    backup = OPENCLAW_CONFIG.parent / f"openclaw.json.bak.{int(time.time())}"
    shutil.copy2(OPENCLAW_CONFIG, backup)

    with open(OPENCLAW_CONFIG) as f:
        cfg = json.load(f)

    agents = cfg.get("agents", {}).get("list", [])
    target = None
    for a in agents:
        if a.get("id", a.get("agentId", "")) == agent_id:
            target = a
            break

    if not target:
        print(f"  ERROR: agent '{agent_id}' not found in config", file=sys.stderr)
        return False

    old_model = target.get("model", {})
    old_primary = old_model.get("primary", "?") if isinstance(old_model, dict) else str(old_model)

    if isinstance(old_model, dict):
        target["model"]["primary"] = new_primary
        if new_fallbacks is not None:
            target["model"]["fallbacks"] = new_fallbacks
    else:
        target["model"] = {"primary": new_primary, "fallbacks": new_fallbacks or []}

    with open(OPENCLAW_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)

    json.load(open(OPENCLAW_CONFIG))

    print(f"  Applied: {agent_id} {old_primary} → {new_primary}")
    return True


def restart_gateway():
    result = subprocess.run(
        ["systemctl", "--user", "restart", "openclaw-gateway"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0:
        print("  Gateway restarted")
    else:
        print(f"  Gateway restart failed: {result.stderr}", file=sys.stderr)


def main():
    if not REPO_API_TOKEN:
        print("ERROR: REPO_API_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    pending = fetch_pending()
    if not pending:
        print("No pending changes.")
        return

    print(f"Found {len(pending)} pending change(s):")
    applied_any = False
    for change in pending:
        print(f"\n  [{change['id']}] {change['agent']} → {change['new_primary']}")
        if apply_change(change):
            ack_change(change["id"])
            applied_any = True
        else:
            print(f"  Skipped (error)")

    if applied_any:
        restart_gateway()
        print("\nDone. Changes applied and gateway restarted.")
    else:
        print("\nNo changes applied.")


if __name__ == "__main__":
    main()
