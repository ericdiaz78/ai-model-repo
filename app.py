#!/usr/bin/env python3
"""
AI Model Knowledge Repository — Web UI
Flask app for browsing, querying, comparing, and ingesting AI models.
Run: python3 app.py
"""

import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, session, redirect, url_for, abort
from functools import wraps

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    HAS_LIMITER = True
except ImportError:
    HAS_LIMITER = False

try:
    import pyotp
    import qrcode
    import qrcode.image.svg
    import io
    import base64
    HAS_TOTP = True
except ImportError:
    HAS_TOTP = False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("RAILWAY_ENVIRONMENT") is not None

if HAS_LIMITER:
    limiter = Limiter(get_remote_address, app=app, default_limits=["120 per minute"])
else:
    limiter = None

UI_PASSWORD_HASH = os.environ.get("UI_PASSWORD_HASH", "")
UI_PASSWORD = os.environ.get("UI_PASSWORD", "IntelligenceMap")
API_TOKEN = os.environ.get("API_TOKEN", "")
TOTP_SECRET = os.environ.get("TOTP_SECRET", "")
TOTP_REQUIRED = os.environ.get("TOTP_REQUIRED", "false").lower() in ("true", "1", "yes")
REPO_DIR = Path(__file__).parent
OPENCLAW_CONFIG = Path.home() / ".openclaw" / "openclaw.json"
PENDING_CHANGES_FILE = REPO_DIR / "pending_model_changes.json"
IS_REMOTE = not OPENCLAW_CONFIG.exists()
OPENCLAW_WEBHOOK_URL = os.environ.get("OPENCLAW_WEBHOOK_URL", "")
OPENCLAW_WEBHOOK_TOKEN = os.environ.get("OPENCLAW_WEBHOOK_TOKEN", "")
MODELS_FILE = REPO_DIR / "models.json"
GENERATED_FILE = REPO_DIR / "models.generated.json"
FEEDBACK_FILE = REPO_DIR / "feedback.json"
CHANGELOG_FILE = REPO_DIR / "CHANGELOG.md"
SPEND_HISTORY_FILE = REPO_DIR / "spend_history.json"
SCRIPTS_DIR = REPO_DIR / "scripts"


def load_models(include_generated=True):
    models = []
    if MODELS_FILE.exists():
        with open(MODELS_FILE) as f:
            models.extend(json.load(f))
    if include_generated and GENERATED_FILE.exists():
        with open(GENERATED_FILE) as f:
            data = json.load(f)
            if isinstance(data, list):
                models.extend(data)
    return models


def compute_efficiency(m):
    """
    Efficiency score 0-100 based on OUR data quality + cost-capability ratio.
    Not benchmarks — how well we know this model and what it costs.
    """
    meta = m.get("_meta") or {}
    confidence = meta.get("confidence", 0.5)
    needs_review = meta.get("needs_review", False)

    strengths = m.get("strengths") or []
    use_cases = m.get("ideal_use_cases") or []
    tags = m.get("routing_tags") or []
    notes = m.get("performance_notes") or ""

    # Capability score: how well-characterized is this model in OUR system
    capability = (
        len(strengths) * 2 +
        len(use_cases) * 1.5 +
        len([t for t in tags if t != "general"]) * 1 +
        (3 if len(notes) > 50 else 0) +
        confidence * 5
    )

    input_price = (m.get("pricing") or {}).get("input_per_mtok", 999)
    # Efficiency = capability per dollar (normalized)
    raw = capability / (input_price + 0.01)

    # Penalty for needs_review
    if needs_review:
        raw *= 0.4

    # Clamp to 0-100
    return min(100, round(raw * 2.5))


def score_for_query(m, task_words):
    tags = set(m.get("routing_tags") or [])
    strength_text = " ".join(m.get("strengths") or []).lower()
    use_case_text = " ".join(m.get("ideal_use_cases") or []).lower()
    perf_text = (m.get("performance_notes") or "").lower()
    name_text = (m.get("model_name") or "").lower()

    tag_match = sum(1 for w in task_words if w in tags)
    text_match = sum(1 for w in task_words
                     if w in strength_text or w in use_case_text or w in perf_text or w in name_text)

    input_cost = (m.get("pricing") or {}).get("input_per_mtok", 999)
    cost_score = 1 / (input_cost + 0.01)

    meta = m.get("_meta") or {}
    confidence = meta.get("confidence", 0.5)
    needs_review = meta.get("needs_review", False)
    review_penalty = 0.4 if needs_review else 1.0

    return (tag_match * 4 + text_match * 2 + cost_score * 0.05 + confidence * 2) * review_penalty


def explain_match(m, task_words):
    tags = set(m.get("routing_tags") or [])
    matched_tags = [w for w in task_words if w in tags]
    strengths = [s for s in (m.get("strengths") or []) if any(w in s.lower() for w in task_words)]
    inp = (m.get("pricing") or {}).get("input_per_mtok", "?")
    parts = []
    if matched_tags:
        parts.append(f"tags: {', '.join(matched_tags)}")
    if strengths:
        parts.append(f"strengths: {', '.join(strengths[:2])}")
    parts.append(f"${inp}/M input")
    return " · ".join(parts)


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#0f1117">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="manifest" href="/manifest.json">
<title>AI Model Repo</title>
<style>
:root {
  --bg: #0f1117; --surface: #1a1d27; --border: #2d3148;
  --text: #e2e8f0; --muted: #64748b; --sub: #94a3b8;
  --accent: #2563eb; --accent-hover: #1d4ed8;
  --green: #34d399; --red: #f87171; --amber: #fbbf24;
  --tag-bg: #1e293b; --tag-border: #334155; --tag-color: #93c5fd;
  --card-hover: #252840;
}
[data-theme="light"] {
  --bg: #f1f5f9; --surface: #ffffff; --border: #e2e8f0;
  --text: #0f172a; --muted: #94a3b8; --sub: #475569;
  --accent: #2563eb; --accent-hover: #1d4ed8;
  --green: #059669; --red: #dc2626; --amber: #d97706;
  --tag-bg: #eff6ff; --tag-border: #bfdbfe; --tag-color: #1d4ed8;
  --card-hover: #f8fafc;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg); color: var(--text); min-height: 100vh; transition: background 0.2s, color 0.2s; }
header { background: var(--surface); border-bottom: 1px solid var(--border);
  padding: 12px 24px; display: flex; align-items: center; gap: 12px; position: sticky; top: 0; z-index: 100; }
header h1 { font-size: 17px; font-weight: 700; color: var(--text); flex: 1; }
.badge { background: var(--accent); color: #fff; font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 600; }
.badge-amber { background: var(--amber); color: #000; }
.sync-btn { background: none; border: 1px solid var(--border); color: var(--sub); font-size: 12px;
  padding: 5px 12px; border-radius: 6px; cursor: pointer; }
.sync-btn:hover { border-color: var(--accent); color: var(--accent); }
.theme-btn { background: none; border: 1px solid var(--border); border-radius: 6px;
  padding: 5px 10px; cursor: pointer; font-size: 16px; line-height: 1; }
.tabs { display: flex; background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 24px; overflow-x: auto; }
.tab { padding: 11px 18px; cursor: pointer; font-size: 13px; font-weight: 500; color: var(--muted);
  border-bottom: 2px solid transparent; transition: all 0.15s; white-space: nowrap; }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab:hover:not(.active) { color: var(--sub); }
.panel { display: none; padding: 20px 24px; max-width: 1280px; margin: 0 auto; }
.panel.active { display: block; }
input[type=text], textarea, select {
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  color: var(--text); padding: 9px 13px; font-size: 13px; width: 100%; outline: none; transition: border-color 0.15s;
}
input[type=text]:focus, textarea:focus, select:focus { border-color: var(--accent); }
textarea { min-height: 90px; resize: vertical; font-family: inherit; }
button { background: var(--accent); color: #fff; border: none; border-radius: 8px;
  padding: 9px 18px; font-size: 13px; cursor: pointer; font-weight: 600; transition: background 0.15s; white-space: nowrap; }
button:hover { background: var(--accent-hover); }
button.ghost { background: none; border: 1px solid var(--border); color: var(--sub); font-weight: 500; }
button.ghost:hover { border-color: var(--accent); color: var(--accent); background: none; }
button.danger { background: #7f1d1d; }
button.danger:hover { background: #991b1b; }

/* STATS */
.stat-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }
.stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; display: flex; gap: 14px; align-items: center; }
.donut-wrap { flex-shrink: 0; }
.stat-info { min-width: 0; }
.stat-val { font-size: 22px; font-weight: 800; color: var(--text); line-height: 1; }
.stat-label { font-size: 11px; color: var(--muted); margin-top: 3px; }
.stat-sub { font-size: 10px; color: var(--muted); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* FILTERS */
.filter-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; align-items: center; }
.filter-bar input[type=text] { flex: 1; min-width: 200px; max-width: 340px; }
.filter-bar select { width: auto; min-width: 140px; }
.tag-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
.chip { background: var(--tag-bg); border: 1px solid var(--tag-border); color: var(--tag-color);
  font-size: 11px; padding: 3px 10px; border-radius: 999px; cursor: pointer; transition: all 0.15s; user-select: none; }
.chip.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.chip:hover:not(.active) { border-color: var(--accent); }

/* CARDS */
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px; transition: border-color 0.15s, background 0.15s; position: relative; }
.card:hover { border-color: #3b4270; background: var(--card-hover); }
.card.comparing { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.card-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; gap: 8px; }
.card-title { min-width: 0; }
.card-name { font-weight: 700; font-size: 14px; color: var(--text); line-height: 1.2; }
.card-provider { font-size: 11px; color: var(--muted); margin-top: 3px; }
.card-title-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.shelf-badge { font-size: 9px; font-weight: 700; padding: 2px 7px; border-radius: 999px; text-transform: uppercase; letter-spacing: 0.06em; flex-shrink: 0; }
.shelf-badge.active { background: #064e3b; border: 1px solid #065f46; color: #34d399; }
.shelf-badge.discovery { background: #1e1b4b; border: 1px solid #312e81; color: #a5b4fc; }
.card-right { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; flex-shrink: 0; }
.cost-pill { background: var(--tag-bg); border: 1px solid var(--tag-border); border-radius: 6px;
  padding: 3px 9px; font-size: 12px; color: var(--sub); text-align: right; }
.cost-pill strong { color: var(--green); font-size: 13px; display: block; line-height: 1.1; }
.eff-ring { display: flex; align-items: center; gap: 4px; }
.eff-label { font-size: 10px; color: var(--muted); }
.tags { display: flex; flex-wrap: wrap; gap: 4px; margin: 8px 0 6px; }
.tag { background: var(--tag-bg); border: 1px solid var(--tag-border); color: var(--tag-color);
  font-size: 10px; padding: 1px 7px; border-radius: 999px; }
.tag.needs-review { background: #2d1b00; border-color: #78350f; color: var(--amber); }
.ctx-bar { height: 3px; background: var(--border); border-radius: 2px; margin: 4px 0; overflow: hidden; }
.ctx-fill { height: 100%; background: var(--accent); border-radius: 2px; }
.card-meta { font-size: 11px; color: var(--muted); margin-top: 4px; }
.card-notes { font-size: 12px; color: var(--sub); margin-top: 8px; line-height: 1.5;
  border-top: 1px solid var(--border); padding-top: 8px;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.spend-bar { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); }
.spend-row { display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 3px; }
.spend-label { color: var(--muted); }
.spend-val { font-weight: 600; color: var(--amber); }
.spend-sub { color: var(--muted); font-size: 10px; }
.compare-cb-wrap { position: absolute; top: 12px; right: 12px; /* overridden by JS if needed */ }
.compare-cb { display: flex; align-items: center; gap: 5px; cursor: pointer; font-size: 11px; color: var(--muted); }
.compare-cb input { width: 14px; height: 14px; cursor: pointer; accent-color: var(--accent); }

/* COMPARE TRAY */
#compare-tray { position: fixed; bottom: 0; left: 0; right: 0; background: var(--surface);
  border-top: 2px solid var(--accent); padding: 12px 24px; display: flex; align-items: center;
  gap: 12px; z-index: 200; box-shadow: 0 -4px 20px rgba(0,0,0,0.3);
  transform: translateY(100%); transition: transform 0.25s ease; }
#compare-tray.visible { transform: translateY(0); }
#tray-models { display: flex; gap: 8px; flex: 1; flex-wrap: wrap; }
.tray-badge { background: var(--tag-bg); border: 1px solid var(--accent); color: var(--text);
  border-radius: 6px; padding: 5px 12px; font-size: 12px; display: flex; align-items: center; gap: 6px; }
.tray-badge button { background: none; border: none; color: var(--muted); font-size: 14px;
  padding: 0; cursor: pointer; line-height: 1; }
.tray-badge button:hover { color: var(--red); background: none; }

/* QUERY RESULTS */
.result-box { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 18px; margin-top: 14px; }
.result-box h3 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); margin-bottom: 12px; }
.result-item { padding: 10px 0; border-bottom: 1px solid var(--border); display: flex; align-items: flex-start; gap: 12px; }
.result-item:last-child { border-bottom: none; }
.result-rank { background: var(--accent); color: #fff; font-size: 10px; font-weight: 800;
  width: 20px; height: 20px; line-height: 20px; text-align: center; border-radius: 50%; flex-shrink: 0; margin-top: 1px; }
.result-body { flex: 1; min-width: 0; }
.result-name { font-weight: 700; font-size: 14px; color: var(--text); }
.result-reason { font-size: 12px; color: var(--sub); margin-top: 3px; }
.result-actions { display: flex; gap: 6px; margin-top: 6px; }
.result-actions button { font-size: 11px; padding: 3px 10px; border-radius: 6px; }
.feedback-btns { display: flex; gap: 4px; }
.fb-btn { background: none; border: 1px solid var(--border); border-radius: 6px;
  padding: 2px 8px; font-size: 12px; cursor: pointer; transition: all 0.15s; }
.fb-btn:hover { border-color: var(--accent); background: none; }
.fb-btn.up.voted { background: #052e16; border-color: var(--green); }
.fb-btn.down.voted { background: #2d0a0a; border-color: var(--red); }

/* COMPARE PANEL */
.compare-scroll { overflow-x: auto; margin-top: 14px; }
.compare-grid { display: grid; gap: 10px; min-width: 600px; }
.compare-col { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; min-width: 200px; }
.compare-col h3 { font-size: 13px; font-weight: 700; color: var(--text); margin-bottom: 12px; line-height: 1.3; }
.cmp-row { display: flex; justify-content: space-between; padding: 6px 0;
  border-bottom: 1px solid var(--border); font-size: 12px; gap: 8px; }
.cmp-row:last-child { border-bottom: none; }
.cmp-label { color: var(--muted); flex-shrink: 0; }
.cmp-val { color: var(--text); font-weight: 500; text-align: right; }
.cmp-val.win { color: var(--green); }
.rec-box { margin-top: 14px; padding: 14px 18px; border-radius: 10px;
  background: #052e16; border: 1px solid #166534; color: #4ade80; font-size: 14px; }
[data-theme="light"] .rec-box { background: #f0fdf4; border-color: #86efac; color: #15803d; }

/* MODEL DETAIL MODAL */
.modal-backdrop { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.65);
  z-index: 500; overflow-y: auto; padding: 24px; }
.modal-backdrop.open { display: flex; align-items: flex-start; justify-content: center; }
.modal { background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  width: 100%; max-width: 860px; padding: 28px; position: relative; margin: auto; }
.modal-close { position: absolute; top: 16px; right: 16px; background: none; border: 1px solid var(--border);
  color: var(--muted); font-size: 18px; width: 32px; height: 32px; border-radius: 50%;
  cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0; line-height: 1; }
.modal-close:hover { border-color: var(--red); color: var(--red); background: none; }
.modal-header { margin-bottom: 20px; padding-right: 40px; }
.modal-name { font-size: 22px; font-weight: 800; color: var(--text); }
.modal-sub { font-size: 13px; color: var(--muted); margin-top: 4px; }
.modal-donuts { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin-bottom: 20px; }
.modal-stat { background: var(--bg); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 14px; display: flex; gap: 10px; align-items: center; }
.modal-stat-info .stat-val { font-size: 18px; }
.modal-body-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
.modal-section { }
.modal-section-title { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); font-weight: 700; margin-bottom: 8px; }
.modal-notes { font-size: 13px; color: var(--sub); line-height: 1.6;
  overflow: visible; display: block;
  -webkit-line-clamp: unset; -webkit-box-orient: unset; }
.modal-list { list-style: none; }
.modal-list li { font-size: 12px; color: var(--sub); padding: 3px 0;
  border-bottom: 1px solid var(--border); display: flex; align-items: baseline; gap: 6px; }
.modal-list li:last-child { border-bottom: none; }
.modal-list li::before { content: "→"; color: var(--accent); font-size: 10px; flex-shrink: 0; }
.modal-list li.weak::before { content: "✗"; color: var(--red); }
.bench-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px; margin-bottom: 20px; }
.bench-card { background: var(--bg); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 14px; }
.bench-card-title { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); font-weight: 700; margin-bottom: 8px; display: flex;
  justify-content: space-between; align-items: baseline; gap: 8px; }
.bench-card-title .bench-asof { font-weight: 400; text-transform: none; letter-spacing: 0;
  font-size: 10px; color: var(--muted); }
.bench-row { display: flex; justify-content: space-between; align-items: baseline;
  font-size: 12px; padding: 3px 0; color: var(--sub);
  border-bottom: 1px solid var(--border); }
.bench-row:last-child { border-bottom: none; }
.bench-row .bench-val { font-weight: 600; color: var(--ink); font-variant-numeric: tabular-nums; }
.industry-note { background: var(--bg); border-left: 2px solid var(--accent);
  border-radius: 0 8px 8px 0; padding: 10px 14px; margin-bottom: 10px; }
.industry-note-quote { font-size: 13px; color: var(--sub); line-height: 1.55;
  font-style: italic; margin-bottom: 6px; }
.industry-note-cite { font-size: 11px; color: var(--muted); display: flex;
  justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.industry-note-cite a { color: var(--accent); text-decoration: none; }
.industry-note-cite a:hover { text-decoration: underline; }
.industry-note-tags { display: flex; gap: 4px; margin-top: 6px; flex-wrap: wrap; }
.industry-note-tag { font-size: 10px; padding: 1px 6px; border-radius: 4px;
  background: var(--surface); color: var(--muted); border: 1px solid var(--border); }
.bench-pending { font-size: 12px; color: var(--muted); font-style: italic;
  padding: 10px 14px; border: 1px dashed var(--border); border-radius: 8px; }
.chart-wrap { margin-top: 20px; }
.chart-title { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); font-weight: 700; margin-bottom: 10px; }
.chart-svg { width: 100%; overflow: visible; }
.chart-no-data { font-size: 12px; color: var(--muted); padding: 20px; text-align: center;
  border: 1px dashed var(--border); border-radius: 8px; }
.chart-legend { display: flex; gap: 16px; margin-top: 8px; flex-wrap: wrap; }
.chart-legend-item { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--muted); }
.chart-legend-dot { width: 10px; height: 3px; border-radius: 2px; }

/* CHANGELOG */
.changelog-body { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 24px; font-size: 13px; line-height: 1.7; color: var(--sub); max-height: 70vh; overflow-y: auto; }
.changelog-body h1, .changelog-body h2 { color: var(--text); margin: 16px 0 8px; }
.changelog-body h1 { font-size: 18px; margin-top: 0; }
.changelog-body h2 { font-size: 14px; font-weight: 700; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
.changelog-body h3 { font-size: 13px; font-weight: 600; color: var(--sub); margin: 10px 0 4px; }
.changelog-body ul { padding-left: 18px; }
.changelog-body li { margin: 3px 0; }
.changelog-body code { background: var(--tag-bg); border: 1px solid var(--border);
  padding: 1px 5px; border-radius: 4px; font-size: 12px; color: var(--tag-color); }
.changelog-body hr { border: none; border-top: 1px solid var(--border); margin: 16px 0; }

/* FEEDBACK */
.feedback-form { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
.feedback-form label { display: block; font-size: 12px; font-weight: 600;
  color: var(--sub); margin-bottom: 5px; margin-top: 14px; }
.feedback-form label:first-child { margin-top: 0; }
.feedback-history { margin-top: 20px; }
.fb-entry { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 16px; margin-bottom: 8px; }
.fb-entry-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.fb-entry-type { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; }
.fb-entry-type.bug { color: var(--red); }
.fb-entry-type.feature { color: var(--green); }
.fb-entry-type.note { color: var(--amber); }
.fb-entry-time { font-size: 11px; color: var(--muted); }
.fb-entry-text { font-size: 13px; color: var(--sub); }

/* MISC */
.status { padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-top: 12px; }
.status.ok { background: #052e16; border: 1px solid #166534; color: #4ade80; }
.status.err { background: #2d0a0a; border: 1px solid #7f1d1d; color: var(--red); }
[data-theme="light"] .status.ok { background: #f0fdf4; border-color: #86efac; color: #15803d; }
[data-theme="light"] .status.err { background: #fff1f2; border-color: #fecdd3; color: #be123c; }
.empty { text-align: center; color: var(--muted); padding: 40px; font-size: 13px; }
.row { display: flex; gap: 10px; align-items: center; }
.spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--border);
  border-top-color: var(--accent); border-radius: 50%; animation: spin 0.6s linear infinite; vertical-align: middle; margin-right: 6px; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading { color: var(--muted); font-size: 13px; padding: 20px 0; }
.section-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); margin-bottom: 12px; font-weight: 600; }
</style>
</head>
<body>
<header>
  <h1>⚡ AI Model Repo</h1>
  <span class="badge" id="model-count">loading…</span>
  <span class="badge badge-amber" id="review-count" style="display:none"></span>
  <button class="sync-btn" onclick="triggerSync()">↻ Sync OpenRouter</button>
  <button class="theme-btn" onclick="toggleTheme()" id="theme-icon">🌙</button>
</header>
<div class="tabs">
  <div class="tab active" onclick="showTab('catalog')">Catalog</div>
  <div class="tab" onclick="showTab('query')">Query</div>
  <div class="tab" onclick="showTab('compare')">Compare</div>
  <div class="tab" onclick="showTab('usage')">Usage</div>
  <div class="tab" onclick="showTab('changelog')">Changelog</div>
  <div class="tab" onclick="showTab('feedback')">Feedback</div>
  <div class="tab" onclick="showTab('ingest')">Ingest</div>
  <div class="tab" onclick="showTab('agents')">⚡ Agents</div>
</div>

<!-- CATALOG -->
<div class="panel active" id="panel-catalog">
  <div class="stat-row" id="stat-row"></div>
  <div class="filter-bar">
    <input type="text" id="catalog-search" placeholder="Search name, provider, tag, notes…" oninput="filterCatalog()">
    <select id="catalog-provider" onchange="filterCatalog()">
      <option value="">All providers</option>
    </select>
    <select id="catalog-sort" onchange="filterCatalog()">
      <option value="efficiency">Sort: Efficiency</option>
      <option value="cost_asc">Sort: Cheapest first</option>
      <option value="cost_desc">Sort: Priciest first</option>
      <option value="context">Sort: Context window</option>
      <option value="name">Sort: Name</option>
    </select>
    <select id="shelf-filter" onchange="filterCatalog()">
      <option value="">All shelves</option>
      <option value="active">Active only</option>
      <option value="discovery">Discovery only</option>
    </select>
    <label style="font-size:12px;color:var(--muted);display:flex;align-items:center;gap:5px;cursor:pointer;white-space:nowrap">
      <input type="checkbox" id="hide-review" onchange="filterCatalog()" style="width:auto">
      Hide unreviewed
    </label>
  </div>
  <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
    <span class="shelf-badge active">ACTIVE</span> <span style="font-size:12px;color:var(--muted)">· production-proven with our telemetry</span>
    <span class="shelf-badge discovery">DISCOVERY</span> <span style="font-size:12px;color:var(--muted)">· benchmarked, awaiting real-world test</span>
  </div>
  <div class="tag-chips" id="tag-chips"></div>
  <div class="grid" id="catalog-grid"><div class="loading"><span class="spinner"></span>Loading models…</div></div>
</div>

<!-- QUERY -->
<div class="panel" id="panel-query">
  <p style="font-size:13px;color:var(--muted);margin-bottom:14px">Ask in plain English. Results are ranked by tag match, strengths, and cost — with rationale shown.</p>
  <div class="row" style="margin-bottom:14px">
    <input type="text" id="query-input" placeholder="e.g. best model for agentic services with low cost" onkeydown="if(event.key==='Enter') runQuery()" style="flex:1">
    <button onclick="runQuery()">Find Best</button>
  </div>
  <div class="tag-chips" id="query-chips">
    <span style="font-size:11px;color:var(--muted);margin-right:4px">Quick:</span>
  </div>
  <div id="query-results"></div>
</div>

<!-- COMPARE -->
<div class="panel" id="panel-compare">
  <p style="font-size:13px;color:var(--muted);margin-bottom:14px">Select up to 5 models from the Catalog (checkboxes) or choose manually below.</p>
  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-bottom:14px">
    <div id="compare-selects" style="display:flex;gap:8px;flex-wrap:wrap;flex:1">
      <!-- Selects injected by JS -->
    </div>
    <button class="ghost" onclick="addCompareSelect()" id="compare-add-btn" style="font-size:12px;padding:7px 12px;white-space:nowrap">+ Add Model</button>
    <select id="compare-task" style="min-width:140px">
      <option value="general">General</option>
      <option value="coding">Coding</option>
      <option value="reasoning">Reasoning</option>
      <option value="agentic">Agentic</option>
      <option value="summarization">Summarization</option>
      <option value="low-cost">Cost-sensitive</option>
    </select>
    <button onclick="runCompare()">Compare →</button>
  </div>
  <div id="compare-results"></div>
</div>

<!-- CHANGELOG -->
<div class="panel" id="panel-changelog">
  <div class="changelog-body" id="changelog-body"><div class="loading"><span class="spinner"></span>Loading…</div></div>
</div>

<!-- FEEDBACK -->
<div class="panel" id="panel-feedback">
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start">
    <div class="feedback-form">
      <div class="section-title">Submit Feedback</div>
      <label>Type</label>
      <select id="fb-type">
        <option value="feature">Feature request</option>
        <option value="bug">Bug / wrong result</option>
        <option value="note">General note</option>
        <option value="model">Model data correction</option>
      </select>
      <label>Details</label>
      <textarea id="fb-text" placeholder="e.g. 'MiniMax should rank higher for agentic tasks — we use it in production daily and it outperforms Gemini Flash for tool use'"></textarea>
      <label>Priority</label>
      <select id="fb-priority">
        <option value="normal">Normal</option>
        <option value="high">High — blocking something</option>
        <option value="low">Low — nice to have</option>
      </select>
      <button onclick="submitFeedback()" style="margin-top:14px;width:100%">Submit Feedback</button>
      <div id="fb-status"></div>
    </div>
    <div>
      <div class="section-title">Recent Feedback</div>
      <div id="fb-history"><div class="loading"><span class="spinner"></span>Loading…</div></div>
    </div>
  </div>
</div>

<!-- USAGE -->
<div class="panel" id="panel-usage">
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start">
    <div>
      <div class="section-title">Import Spend Data</div>
      <div class="feedback-form">
        <label>Provider Activity CSV</label>
        <p style="font-size:12px;color:var(--muted);margin-bottom:10px">
          Auto-detects format. Drop any of:
          <strong>OpenRouter</strong> (openrouter.ai/activity → Export CSV) ·
          <strong>Anthropic</strong> (console.anthropic.com/settings/usage → Export) ·
          <strong>OpenAI</strong> (platform.openai.com/usage → Export)<br>
          Backfills daily trend chart history from your full export history.
        </p>
        <div id="csv-drop" style="border:2px dashed var(--border);border-radius:8px;padding:32px;text-align:center;cursor:pointer;transition:border-color 0.15s"
          ondragover="event.preventDefault();this.style.borderColor='var(--accent)'"
          ondragleave="this.style.borderColor='var(--border)'"
          ondrop="handleCsvDrop(event)"
          onclick="document.getElementById('csv-file').click()">
          <div style="font-size:28px;margin-bottom:8px">📊</div>
          <div style="font-size:13px;color:var(--sub)">Drop CSV here or click to browse</div>
          <div style="font-size:11px;color:var(--muted);margin-top:4px">openrouter_activity_*.csv</div>
        </div>
        <input type="file" id="csv-file" accept=".csv" style="display:none" onchange="handleCsvFile(this.files[0])">
        <div id="csv-preview" style="margin-top:12px"></div>
        <div style="display:flex;gap:8px;margin-top:12px">
          <button onclick="uploadCsv()" id="csv-upload-btn" style="flex:1;display:none">Import Spend Data</button>
          <button class="ghost" onclick="clearCsvUpload()" id="csv-clear-btn" style="display:none">Clear</button>
        </div>
        <div id="csv-status"></div>
      </div>
    </div>
    <div>
      <div class="section-title">Spend by Model</div>
      <div id="spend-chart"><div class="loading"><span class="spinner"></span>Loading…</div></div>
    </div>
  </div>
  <div style="margin-top:20px">
    <div class="section-title">All Models with Spend Data</div>
    <div id="spend-table"></div>
  </div>
</div>

<!-- INGEST -->
<div class="panel" id="panel-ingest">
  <p style="font-size:13px;color:var(--muted);margin-bottom:14px">Paste a model announcement, release note, or description. System extracts a structured record.</p>
  <textarea id="ingest-text" placeholder="e.g. Mistral released Devstral-Small at $0.1/M input, specialized for code generation with 131k context…"></textarea>
  <div class="row" style="margin-top:10px">
    <input type="text" id="ingest-out" placeholder="Output: models.generated.json" style="flex:1">
    <button onclick="runIngest()">Ingest Model</button>
  </div>
  <div id="ingest-results"></div>
</div>

<!-- AGENTS -->
<div class="panel" id="panel-agents">
  <div class="section-title">Agent Model Assignment</div>
  <p style="font-size:13px;color:var(--muted);margin-bottom:16px">Change agent primary models directly. Backs up config before every change. Gateway restart required to take effect.</p>
  <div id="agents-grid" style="display:grid;gap:12px;max-width:800px"></div>
  <div id="agents-status" style="margin-top:12px"></div>
  <div class="section-title" style="margin-top:28px">Model Change History</div>
  <div id="agents-history" style="font-size:12px"></div>
</div>

<!-- MODEL DETAIL MODAL -->
<div class="modal-backdrop" id="model-modal" onclick="handleModalBackdropClick(event)">
  <div class="modal" id="modal-inner">
    <button class="modal-close" onclick="closeModal()">✕</button>
    <div class="modal-header">
      <div class="modal-name" id="modal-name"></div>
      <div class="modal-sub" id="modal-sub"></div>
    </div>
    <div class="modal-donuts" id="modal-donuts"></div>
    <div class="modal-body-grid" id="modal-body"></div>
    <div class="chart-wrap" id="modal-charts"></div>
  </div>
</div>

<!-- COMPARE TRAY -->
<div id="compare-tray">
  <span style="font-size:12px;font-weight:600;color:var(--muted);white-space:nowrap">Compare:</span>
  <div id="tray-models"></div>
  <button class="ghost" onclick="clearCompare()">✕ Clear</button>
  <button onclick="fireCompare()">Compare →</button>
</div>

<script>
// ── Theme ──────────────────────────────────────────────────────────────
const prefersDark = window.matchMedia('(prefers-color-scheme: dark)');
let currentTheme = localStorage.getItem('theme') || (prefersDark.matches ? 'dark' : 'light');
function applyTheme(t) {
  currentTheme = t;
  document.documentElement.setAttribute('data-theme', t === 'light' ? 'light' : '');
  document.getElementById('theme-icon').textContent = t === 'light' ? '☀️' : '🌙';
  localStorage.setItem('theme', t);
}
function toggleTheme() { applyTheme(currentTheme === 'dark' ? 'light' : 'dark'); }
prefersDark.addEventListener('change', e => { if (!localStorage.getItem('theme')) applyTheme(e.matches ? 'dark' : 'light'); });
applyTheme(currentTheme);

// ── State ──────────────────────────────────────────────────────────────
let allModels = [];
let compareSet = new Set(); // model_ids selected for compare
let activeTagFilter = null;

// ── Init ───────────────────────────────────────────────────────────────
async function loadModels() {
  const res = await fetch('/api/models');
  allModels = await res.json();
  const needsReview = allModels.filter(m => m._meta?.needs_review).length;
  document.getElementById('model-count').textContent = allModels.length + ' models';
  if (needsReview > 0) {
    const rb = document.getElementById('review-count');
    rb.textContent = needsReview + ' need review';
    rb.style.display = '';
  }
  renderStats();
  renderTagChips();
  renderCatalog(filterModels());
}

// ── Donut SVG — only for genuine 0-100 values ─────────────────────────
// Rule: use donut only when value is naturally 0-100 (score, %, confidence).
// For counts/dollars/prices with no defined ceiling, use plainStat instead.
function donut(pct, color='#2563eb', size=44) {
  const r = 15.9155, c = 2 * Math.PI * r;
  const dash = (Math.min(100, Math.max(0, pct)) / 100) * c;
  return `<svg width="${size}" height="${size}" viewBox="0 0 36 36">
    <circle cx="18" cy="18" r="${r}" fill="none" stroke="var(--border)" stroke-width="3.5"/>
    <circle cx="18" cy="18" r="${r}" fill="none" stroke="${color}" stroke-width="3.5"
      stroke-dasharray="${dash} ${c}" stroke-dashoffset="${c * 0.25}" transform="rotate(-90 18 18)"
      stroke-linecap="round"/>
  </svg>`;
}

// ── Plain Stat — for values without a natural 0-100% ceiling ──────────
// Renders a colored top-border tile instead of a misleading ring.
function plainStat(value, label, sub='', color='#2563eb') {
  return `<div class="stat-card plain-stat" style="border-top:3px solid ${color};padding-top:13px">
    <div class="stat-info">
      <div class="stat-val">${value}</div>
      <div class="stat-label">${label}</div>
      ${sub ? `<div class="stat-sub">${sub}</div>` : ''}
    </div>
  </div>`;
}

// Same but for the modal grid (slightly different container)
function modalPlainStat(value, label, sub='', color='#2563eb') {
  return `<div class="modal-stat plain-stat" style="border-top:3px solid ${color};padding-top:11px;align-items:flex-start">
    <div class="stat-info modal-stat-info">
      <div class="stat-val">${value}</div>
      <div class="stat-label">${label}</div>
      ${sub ? `<div class="stat-sub">${sub}</div>` : ''}
    </div>
  </div>`;
}

function modalDonutStat(pct, color, value, label, sub='') {
  return `<div class="modal-stat">
    <div class="donut-wrap">${donut(pct, color, 44)}</div>
    <div class="stat-info modal-stat-info">
      <div class="stat-val">${value}</div>
      <div class="stat-label">${label}</div>
      ${sub ? `<div class="stat-sub">${sub}</div>` : ''}
    </div>
  </div>`;
}

// ── Stats ──────────────────────────────────────────────────────────────
function renderStats() {
  const providers = [...new Set(allModels.map(m => m.provider))];
  const curated = allModels.filter(m => !m._meta?.needs_review);
  const activeCount = allModels.filter(m => m._meta?.shelf === 'active').length;
  const discoveryCount = allModels.filter(m => m._meta?.shelf === 'discovery').length;
  const withPricing = allModels.filter(m => (m.pricing?.input_per_mtok || 0) > 0);
  const cheapest = withPricing.reduce((a, b) =>
    (a.pricing?.input_per_mtok || 999) < (b.pricing?.input_per_mtok || 999) ? a : b, withPricing[0]);
  const curatedPct = Math.round((curated.length / allModels.length) * 100);

  const effScores = curated.map(m => computeEff(m));
  const avgEff = effScores.length ? Math.round(effScores.reduce((a,b)=>a+b,0)/effScores.length) : 0;

  // Spend totals
  const withSpend = allModels.filter(m => m.spend?.total_cost_usd > 0);
  const totalSpend = withSpend.reduce((s, m) => s + (m.spend?.total_cost_usd || 0), 0);
  const topSpender = withSpend.sort((a,b) => (b.spend?.total_cost_usd||0) - (a.spend?.total_cost_usd||0))[0];
  const spendPct = topSpender && totalSpend > 0 ? Math.round((topSpender.spend.total_cost_usd / totalSpend) * 100) : 0;

  document.getElementById('stat-row').innerHTML = [
    // Count: total models in catalog
    plainStat(allModels.length, 'Total Models', `${providers.length} providers`, '#2563eb'),
    // Active shelf count
    plainStat(activeCount, 'Active Models', 'in production', '#34d399'),
    // Discovery shelf count
    plainStat(discoveryCount, 'Discovery Shelf', 'benchmarked, awaiting test', '#a5b4fc'),
    // Avg efficiency: 0-100 score → donut
    `<div class="stat-card">
      <div class="donut-wrap">${donut(avgEff, '#fbbf24')}</div>
      <div class="stat-info">
        <div class="stat-val">${avgEff}<span style="font-size:13px;font-weight:400;color:var(--muted)">/100</span></div>
        <div class="stat-label">Avg Efficiency</div>
        <div class="stat-sub">capability ÷ cost score</div>
      </div>
    </div>`,
    // Cheapest input: dollar amount, no ceiling → plain
    plainStat(
      `$${cheapest?.pricing?.input_per_mtok ?? '?'}<span style="font-size:11px;font-weight:400;color:var(--muted)">/M</span>`,
      'Cheapest Input',
      cheapest?.model_name?.split(' ').slice(0,3).join(' ') ?? '',
      '#34d399'
    ),
    // Total spend: dollar amount, no ceiling → plain
    totalSpend > 0 ? plainStat(
      `$${totalSpend.toFixed(2)}`,
      'Total Spend',
      topSpender ? `${topSpender.model_name?.split(' ').slice(0,2).join(' ')} leads` : '',
      '#f87171'
    ) : '',
  ].join('');

  // Populate provider filter
  const pf = document.getElementById('catalog-provider');
  providers.sort().forEach(p => {
    const o = document.createElement('option'); o.value = p; o.textContent = p; pf.appendChild(o);
  });
}

// ── Efficiency (client-side mirror of server logic) ────────────────────
function computeEff(m) {
  const meta = m._meta || {};
  const confidence = meta.confidence || 0.5;
  const needsReview = meta.needs_review || false;
  const strengths = (m.strengths || []).length;
  const useCases = (m.ideal_use_cases || []).length;
  const tags = (m.routing_tags || []).filter(t => t !== 'general').length;
  const notes = (m.performance_notes || '').length > 50 ? 3 : 0;
  const capability = strengths * 2 + useCases * 1.5 + tags + notes + confidence * 5;
  const price = (m.pricing?.input_per_mtok || 999);
  let raw = capability / (price + 0.01);
  if (needsReview) raw *= 0.4;
  return Math.min(100, Math.round(raw * 2.5));
}

function effColor(score) {
  if (score >= 70) return '#34d399';
  if (score >= 40) return '#fbbf24';
  return '#64748b';
}

// ── Tag Chips ──────────────────────────────────────────────────────────
function renderTagChips() {
  const tagCounts = {};
  allModels.forEach(m => (m.routing_tags || []).forEach(t => tagCounts[t] = (tagCounts[t]||0)+1));
  const topTags = Object.entries(tagCounts).sort((a,b)=>b[1]-a[1]).slice(0,12).map(([t])=>t);
  const wrap = document.getElementById('tag-chips');
  wrap.innerHTML = topTags.map(t =>
    `<span class="chip ${activeTagFilter===t?'active':''}" onclick="toggleTagFilter('${t}')">${t}</span>`
  ).join('');

  // Query quick chips
  const qc = document.getElementById('query-chips');
  const quickTags = ['agentic', 'coding', 'reasoning', 'low-cost', 'fast-response', 'vision'];
  qc.innerHTML = '<span style="font-size:11px;color:var(--muted);margin-right:4px">Quick:</span>' +
    quickTags.map(t => `<span class="chip" onclick="setQuery('${t}')">${t}</span>`).join('');
}

function toggleTagFilter(tag) {
  activeTagFilter = activeTagFilter === tag ? null : tag;
  document.querySelectorAll('#tag-chips .chip').forEach(c =>
    c.classList.toggle('active', c.textContent === activeTagFilter));
  renderCatalog(filterModels());
}

// ── Catalog filter/sort ────────────────────────────────────────────────
function filterModels() {
  const q = document.getElementById('catalog-search').value.toLowerCase();
  const prov = document.getElementById('catalog-provider').value;
  const shelf = document.getElementById('shelf-filter').value;
  const hideReview = document.getElementById('hide-review').checked;
  let list = allModels.filter(m => {
    if (hideReview && m._meta?.needs_review) return false;
    if (prov && m.provider !== prov) return false;
    if (shelf && m._meta?.shelf !== shelf) return false;
    if (activeTagFilter && !(m.routing_tags || []).includes(activeTagFilter)) return false;
    if (q) {
      const text = [m.model_name, m.provider, ...(m.routing_tags||[]),
        ...(m.strengths||[]), m.performance_notes||'', m.model_id].join(' ').toLowerCase();
      if (!text.includes(q)) return false;
    }
    return true;
  });
  const sort = document.getElementById('catalog-sort').value;
  list.sort((a,b) => {
    if (sort === 'cost_asc') return (a.pricing?.input_per_mtok||999) - (b.pricing?.input_per_mtok||999);
    if (sort === 'cost_desc') return (b.pricing?.input_per_mtok||0) - (a.pricing?.input_per_mtok||0);
    if (sort === 'context') return (b.context_window||0) - (a.context_window||0);
    if (sort === 'name') return (a.model_name||'').localeCompare(b.model_name||'');
    return computeEff(b) - computeEff(a); // default: efficiency
  });
  return list;
}

function filterCatalog() { renderCatalog(filterModels()); }

function ctxLabel(n) {
  if (!n) return '?';
  return n >= 1000000 ? (n/1000000).toFixed(1)+'M' : Math.round(n/1000)+'k';
}

function renderCatalog(models) {
  const grid = document.getElementById('catalog-grid');
  if (!models.length) { grid.innerHTML = '<div class="empty">No models match your filters.</div>'; return; }
  grid.innerHTML = models.map(m => {
    const eff = computeEff(m);
    const inp = m.pricing?.input_per_mtok ?? '?';
    const out = m.pricing?.output_per_mtok ?? '?';
    const ctx = ctxLabel(m.context_window);
    const ctxPct = Math.min(100, (m.context_window || 0) / 12000);
    const needsReview = m._meta?.needs_review;
    const tags = [...(m.routing_tags||[])].map(t =>
      `<span class="tag">${t}</span>`).join('') +
      (needsReview ? '<span class="tag needs-review">needs review</span>' : '');
    const checked = compareSet.has(m.model_id) ? 'checked' : '';
    const comparing = compareSet.has(m.model_id) ? 'comparing' : '';
    return `<div class="card ${comparing}" id="card-${CSS.escape(m.model_id)}" onclick="handleCardClick(event,'${m.model_id}')" style="cursor:pointer">
      <div style="position:absolute;top:10px;right:10px">
        <label class="compare-cb" title="Add to compare" onclick="event.stopPropagation()">
          <input type="checkbox" ${checked} onchange="toggleCompare('${m.model_id}', this.checked)"> Compare
        </label>
      </div>
      <div class="card-top" style="padding-right:70px">
        <div class="card-title">
          <div class="card-title-row">
            <div class="card-name">${m.model_name}</div>
            ${m._meta?.shelf ? `<span class="shelf-badge ${m._meta.shelf}">${m._meta.shelf}</span>` : ''}
          </div>
          <div class="card-provider">${m.provider}${m.version ? ' · v'+m.version : ''}</div>
        </div>
        <div class="card-right">
          <div class="cost-pill"><strong>$${inp}</strong>per MTok in</div>
          <div class="eff-ring">
            ${donut(eff, effColor(eff), 28)}
            <span class="eff-label">${eff} eff</span>
          </div>
        </div>
      </div>
      <div class="tags">${tags}</div>
      <div class="ctx-bar"><div class="ctx-fill" style="width:${ctxPct}%"></div></div>
      <div class="card-meta">ctx ${ctx} · out $${out}/MTok${m.release_date ? ' · ' + m.release_date : ''}</div>
      ${m.performance_notes ? `<div class="card-notes">${m.performance_notes}</div>` : ''}
      ${m.spend?.total_cost_usd > 0 ? `
      <div class="spend-bar">
        <div class="spend-row">
          <span class="spend-label">Total spend (OpenRouter)</span>
          <span class="spend-val">$${m.spend.total_cost_usd.toFixed(4)}</span>
        </div>
        <div class="spend-row">
          <span class="spend-label">${m.spend.call_count.toLocaleString()} calls · avg $${m.spend.avg_cost_per_call_usd.toFixed(5)}/call</span>
          <span class="spend-sub">${m.spend.total_input_mtok.toFixed(2)}M in · ${m.spend.total_output_mtok.toFixed(2)}M out${m.spend.total_cache_read_mtok > 0 ? ` · ${m.spend.total_cache_read_mtok.toFixed(2)}M cached` : ''}</span>
        </div>
      </div>` : ''}
      ${m.direct_pricing ? `
      <div class="spend-bar" style="border-top-style:${m.direct_pricing.direct_available ? 'solid' : 'dashed'}">
        <div class="spend-row">
          <span class="spend-label" style="color:${m.direct_pricing.direct_available ? 'var(--green)' : 'var(--muted)'}">
            ${m.direct_pricing.direct_available ? '⚡ Direct API available' : '⛔ OpenRouter only'}
          </span>
        </div>
        ${m.direct_pricing.batch_input_per_mtok ? `
        <div class="spend-row">
          <span class="spend-label">Batch API (50% off)</span>
          <span class="spend-val" style="color:var(--green)">$${m.direct_pricing.batch_input_per_mtok}/M in</span>
        </div>` : ''}
        ${m.direct_pricing.cache_read_per_mtok ? `
        <div class="spend-row">
          <span class="spend-label">Cache reads (direct)</span>
          <span class="spend-val" style="color:var(--green)">$${m.direct_pricing.cache_read_per_mtok}/M</span>
        </div>` : ''}
      </div>` : ''}
    </div>`;
  }).join('');
}

// ── Compare tray ───────────────────────────────────────────────────────
function toggleCompare(id, checked) {
  if (checked) {
    compareSet.add(id);
  } else {
    compareSet.delete(id);
  }
  updateTray();
  const card = document.getElementById('card-' + CSS.escape(id));
  if (card) card.classList.toggle('comparing', checked);
}

function updateTray() {
  const tray = document.getElementById('compare-tray');
  const models = document.getElementById('tray-models');
  if (compareSet.size === 0) { tray.classList.remove('visible'); return; }
  tray.classList.add('visible');
  const names = [...compareSet].map(id => {
    const m = allModels.find(x => x.model_id === id);
    return `<div class="tray-badge">${m?.model_name || id}
      <button onclick="toggleCompare('${id}', false); document.querySelector('#card-${CSS.escape(id)} input[type=checkbox]').checked=false">×</button>
    </div>`;
  });
  models.innerHTML = names.join('');
}

function clearCompare() {
  compareSet.forEach(id => {
    const card = document.getElementById('card-' + CSS.escape(id));
    if (card) { const cb = card.querySelector('input[type=checkbox]'); if(cb) cb.checked = false; card.classList.remove('comparing'); }
  });
  compareSet.clear();
  updateTray();
}

function fireCompare() {
  const ids = [...compareSet];
  if (ids.length < 2) { alert('Select at least 2 models to compare.'); return; }
  syncCompareSetsToSelects(ids);
  showTab('compare');
  runCompare();
}

function syncCompareSetsToSelects(ids) {
  const wrap = document.getElementById('compare-selects');
  // Ensure enough selects exist
  while (wrap.querySelectorAll('select').length < ids.length) addCompareSelect();
  const sels = wrap.querySelectorAll('select');
  ids.forEach((id, i) => { if (sels[i]) sels[i].value = id; });
}

// ── Query ──────────────────────────────────────────────────────────────
function setQuery(tag) {
  document.getElementById('query-input').value = tag;
  runQuery();
}

async function runQuery() {
  const q = document.getElementById('query-input').value.trim();
  if (!q) return;
  const out = document.getElementById('query-results');
  out.innerHTML = '<div class="loading"><span class="spinner"></span>Searching…</div>';

  // Parse budget hint from query ("under $1", "< $2", "cheap")
  let budget = null;
  const budgetMatch = q.match(/under\s*\$?([\d.]+)|<\s*\$?([\d.]+)/i);
  if (budgetMatch) budget = parseFloat(budgetMatch[1] || budgetMatch[2]);
  if (/\b(cheap|budget|free|low.cost)\b/i.test(q)) budget = budget || 1.0;

  // Build task word list from query
  const stopwords = new Set(['best', 'model', 'for', 'with', 'and', 'the', 'a', 'an', 'that', 'is', 'are', 'at', 'under', 'cost']);
  const taskWords = q.toLowerCase().split(/\W+/).filter(w => w.length > 2 && !stopwords.has(w));

  // Client-side scoring (same logic as /api/recommend)
  let candidates = [...allModels];
  if (budget !== null) candidates = candidates.filter(m => (m.pricing?.input_per_mtok || 999) <= budget);

  const scored = candidates.map(m => ({
    model: m,
    score: scoreModel(m, taskWords),
    explain: explainModel(m, taskWords)
  })).sort((a,b) => b.score - a.score).slice(0, 6);

  out.innerHTML = `<div class="result-box">
    <h3>Results for "${q}"${budget ? ` · budget ≤ $${budget}/MTok` : ''}</h3>
    ${scored.map((r, i) => {
      const m = r.model;
      const inp = m.pricing?.input_per_mtok ?? '?';
      const eff = computeEff(m);
      return `<div class="result-item">
        <div class="result-rank">${i+1}</div>
        <div class="result-body">
          <div class="result-name">${m.model_name} <span style="font-size:11px;color:var(--muted)">${m.provider}</span></div>
          <div class="result-reason">$${inp}/MTok · eff ${eff} · ${r.explain}</div>
          <div class="result-actions">
            <button class="ghost" style="font-size:11px;padding:3px 10px" onclick="addToCompare('${m.model_id}')">+ Compare</button>
            <div class="feedback-btns">
              <span class="fb-btn up" onclick="voteFb(this,'up','${m.model_id}','${q.replace(/'/g,"\\'")}')">👍</span>
              <span class="fb-btn down" onclick="voteFb(this,'down','${m.model_id}','${q.replace(/'/g,"\\'")}')">👎</span>
            </div>
          </div>
        </div>
      </div>`;
    }).join('')}
  </div>`;
}

function scoreModel(m, taskWords) {
  const tags = new Set(m.routing_tags || []);
  const strengthText = (m.strengths || []).join(' ').toLowerCase();
  const useCaseText = (m.ideal_use_cases || []).join(' ').toLowerCase();
  const perfText = (m.performance_notes || '').toLowerCase();
  const tagMatch = taskWords.filter(w => tags.has(w)).length;
  const textMatch = taskWords.filter(w => strengthText.includes(w) || useCaseText.includes(w) || perfText.includes(w)).length;
  const price = m.pricing?.input_per_mtok || 999;
  const costScore = 1 / (price + 0.01);
  const confidence = m._meta?.confidence || 0.5;
  const reviewPenalty = m._meta?.needs_review ? 0.4 : 1.0;
  return (tagMatch * 4 + textMatch * 2 + costScore * 0.05 + confidence * 2) * reviewPenalty;
}

function explainModel(m, taskWords) {
  const tags = new Set(m.routing_tags || []);
  const matchedTags = taskWords.filter(w => tags.has(w));
  const strengths = (m.strengths || []).filter(s => taskWords.some(w => s.toLowerCase().includes(w)));
  const parts = [];
  if (matchedTags.length) parts.push('tags: ' + matchedTags.join(', '));
  if (strengths.length) parts.push('strengths: ' + strengths.slice(0,2).join(', '));
  if (!parts.length) parts.push('best available match');
  return parts.join(' · ');
}

function addToCompare(id) {
  compareSet.add(id);
  updateTray();
  const card = document.getElementById('card-' + CSS.escape(id));
  if (card) { const cb = card.querySelector('input[type=checkbox]'); if(cb) cb.checked = true; card.classList.add('comparing'); }
}

async function voteFb(el, vote, modelId, query) {
  el.classList.add('voted');
  await fetch('/api/feedback', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ type: 'query_vote', vote, model_id: modelId, query, priority: 'low' })
  });
}

// ── Compare ────────────────────────────────────────────────────────────
const COMPARE_COLORS = ['#2563eb','#34d399','#f59e0b','#f87171','#a78bfa'];
let compareSelectCount = 0;

function buildSelectOptions() {
  const curatedFirst = [...allModels].sort((a,b) => (a._meta?.needs_review?1:0) - (b._meta?.needs_review?1:0));
  return '<option value="">— pick model —</option>' +
    curatedFirst.map(m => `<option value="${m.model_id}">${m.model_name}${m._meta?.needs_review?' ⚠':''}</option>`).join('');
}

function addCompareSelect(val='') {
  const wrap = document.getElementById('compare-selects');
  if (wrap.querySelectorAll('select').length >= 5) return;
  compareSelectCount++;
  const idx = wrap.querySelectorAll('select').length;
  const div = document.createElement('div');
  div.style.cssText = 'display:flex;align-items:center;gap:4px';
  div.innerHTML = `
    <span style="width:10px;height:10px;border-radius:50%;background:${COMPARE_COLORS[idx]};flex-shrink:0"></span>
    <select style="min-width:160px;flex:1" class="cmp-sel">${buildSelectOptions()}</select>
    <button class="ghost" onclick="this.parentElement.remove();checkAddBtn()" style="padding:5px 8px;font-size:12px;border-radius:6px">✕</button>`;
  wrap.appendChild(div);
  if (val) div.querySelector('select').value = val;
  checkAddBtn();
}

function checkAddBtn() {
  const cnt = document.getElementById('compare-selects').querySelectorAll('select').length;
  document.getElementById('compare-add-btn').style.display = cnt >= 5 ? 'none' : '';
}

function populateCompareSelects() {
  // Start with 2 default selects
  addCompareSelect(); addCompareSelect();
}

async function runCompare() {
  const sels = [...document.querySelectorAll('#compare-selects .cmp-sel')];
  const ids = sels.map(s => s.value).filter(Boolean);
  if (ids.length < 2) {
    document.getElementById('compare-results').innerHTML = '<div class="status err">Select at least 2 models.</div>';
    return;
  }
  const task = document.getElementById('compare-task').value;
  const out = document.getElementById('compare-results');
  out.innerHTML = '<div class="loading"><span class="spinner"></span>Comparing…</div>';

  // Fetch all models data
  const models = ids.map(id => allModels.find(m => m.model_id === id)).filter(Boolean);
  if (models.length < 2) { out.innerHTML = '<div class="status err">Could not find selected models.</div>'; return; }

  // Fetch spend history for all selected models
  let history = {};
  try {
    const hr = await fetch('/api/spend-history');
    history = await hr.json();
  } catch(e) {}

  const effs = models.map(m => computeEff(m));
  const minInp = Math.min(...models.map(m => m.pricing?.input_per_mtok ?? 999));
  const maxCtx = Math.max(...models.map(m => m.context_window ?? 0));
  const maxEff = Math.max(...effs);

  function fmtCtx(n) { return n ? (n>=1e6?(n/1e6).toFixed(1)+'M':Math.round(n/1000)+'k') : '?'; }

  const cols = models.map((m, i) => {
    const eff = effs[i];
    const inp = m.pricing?.input_per_mtok ?? null;
    const color = COMPARE_COLORS[i];
    const isMinInp = inp !== null && inp <= minInp;
    const isMaxCtx = (m.context_window||0) >= maxCtx;
    const isMaxEff = eff >= maxEff;
    return `<div class="compare-col" style="border-top:3px solid ${color}">
      <h3><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};margin-right:6px"></span>${m.model_name}</h3>
      <div class="cmp-row"><span class="cmp-label">Provider</span><span class="cmp-val">${m.provider}</span></div>
      <div class="cmp-row"><span class="cmp-label">Input</span><span class="cmp-val ${isMinInp?'win':''}">$${inp??'?'}/M</span></div>
      <div class="cmp-row"><span class="cmp-label">Output</span><span class="cmp-val">$${m.pricing?.output_per_mtok??'?'}/M</span></div>
      <div class="cmp-row"><span class="cmp-label">Context</span><span class="cmp-val ${isMaxCtx?'win':''}">${fmtCtx(m.context_window)}</span></div>
      <div class="cmp-row"><span class="cmp-label">Efficiency</span><span class="cmp-val ${isMaxEff?'win':''}">${eff}/100</span></div>
      <div class="cmp-row"><span class="cmp-label">Tags</span><span class="cmp-val" style="font-size:10px">${(m.routing_tags||[]).slice(0,3).join(', ')||'—'}</span></div>
      ${m.spend?.total_cost_usd > 0 ? `
      <div class="cmp-row"><span class="cmp-label">Spent</span><span class="cmp-val" style="color:var(--amber)">$${m.spend.total_cost_usd.toFixed(2)}</span></div>
      <div class="cmp-row"><span class="cmp-label">Calls</span><span class="cmp-val">${m.spend.call_count.toLocaleString()}</span></div>
      <div class="cmp-row"><span class="cmp-label">Avg/call</span><span class="cmp-val">$${m.spend.avg_cost_per_call_usd.toFixed(5)}</span></div>` : `
      <div class="cmp-row"><span class="cmp-label">Spent</span><span class="cmp-val" style="color:var(--muted)">no data</span></div>`}
      ${m.direct_pricing?.direct_available ? `
      <div class="cmp-row"><span class="cmp-label">Direct API</span><span class="cmp-val" style="color:var(--green)">⚡ Yes</span></div>` : ''}
      ${m.direct_pricing?.batch_input_per_mtok ? `
      <div class="cmp-row"><span class="cmp-label">Batch</span><span class="cmp-val" style="color:var(--green)">$${m.direct_pricing.batch_input_per_mtok}/M</span></div>` : ''}
    </div>`;
  });

  const gridCols = `repeat(${models.length}, minmax(180px, 1fr))`;
  const winner = models[effs.indexOf(maxEff)];

  // Build trend charts for models that have history
  const hasHistory = models.some(m => (history[m.model_id]||[]).length > 1 || (history[m.openrouter_slug]||[]).length > 1);
  let trendsHtml = '';
  if (hasHistory) {
    const allDates = new Set();
    models.forEach(m => {
      const h = history[m.model_id] || history[m.openrouter_slug] || [];
      h.forEach(d => allDates.add(d.date));
    });
    const dates = [...allDates].sort();
    const seriesCost = models.map((m,i) => ({
      label: m.model_name, color: COMPARE_COLORS[i],
      data: history[m.model_id] || history[m.openrouter_slug] || []
    }));
    trendsHtml = `<div style="margin-top:20px">
      <div class="section-title">Daily Cost Trend — All Models</div>
      ${lineChart(dates, seriesCost, d => d.cost_usd, 700, 180, v => '$'+v.toFixed(2))}
      <div class="chart-legend">${seriesCost.map(s =>
        `<div class="chart-legend-item"><div class="chart-legend-dot" style="background:${s.color}"></div>${s.label}</div>`).join('')}
      </div>
    </div>`;
  }

  out.innerHTML = `
    <div class="compare-scroll">
      <div class="compare-grid" style="grid-template-columns:${gridCols}">${cols.join('')}</div>
    </div>
    <div class="rec-box" style="margin-top:14px">🏆 Best overall: <strong>${winner.model_name}</strong> (efficiency ${maxEff}/100${minInp < 999 ? ', $'+minInp+'/M input' : ''})</div>
    ${trendsHtml}`;
}

// ── SVG Line Chart ────────────────────────────────────────────────────
function lineChart(dates, series, accessor, w=680, h=160, fmtY=v=>v.toFixed(2)) {
  if (!dates.length) return '<div class="chart-no-data">No daily data yet — accumulates with each hourly sync.</div>';
  const pad = {t:10, r:10, b:30, l:54};
  const cw = w - pad.l - pad.r, ch = h - pad.t - pad.b;

  // Compute rolling 90-day window
  const cutoff = dates.length > 90 ? dates[dates.length - 90] : dates[0];
  const visDates = dates.filter(d => d >= cutoff);

  // For each series, build value lookup and apply 7-day rolling average
  function rollingAvg(vals, k=7) {
    return vals.map((v, i) => {
      const slice = vals.slice(Math.max(0, i-k+1), i+1).filter(x => x != null);
      return slice.length ? slice.reduce((a,b)=>a+b,0)/slice.length : 0;
    });
  }

  const allAvged = series.map(s => {
    // Per-series accessor overrides the shared one; allows mixed metrics on one chart
    const acc = s.accessor || accessor;
    if (!acc) return visDates.map(() => 0);
    const lookup = Object.fromEntries((s.data||[]).map(d => [d.date, acc(d)||0]));
    const raw = visDates.map(d => lookup[d] ?? 0);
    return rollingAvg(raw);
  });

  const allVals = allAvged.flat().filter(v => v > 0);
  if (!allVals.length) return '<div class="chart-no-data">No spend data in this range yet.</div>';
  const maxV = Math.max(...allVals) * 1.1 || 1;

  function px(i, v) {
    const x = pad.l + (i / Math.max(visDates.length-1,1)) * cw;
    const y = pad.t + ch - (v / maxV) * ch;
    return [x, y];
  }

  // Axis labels
  const yTicks = 4;
  const yLabels = Array.from({length:yTicks+1}, (_,i) => {
    const v = (maxV * i/yTicks);
    const y = pad.t + ch - (v/maxV)*ch;
    return `<text x="${pad.l-6}" y="${y+4}" text-anchor="end" font-size="9" fill="var(--muted)">${fmtY(v)}</text>
      <line x1="${pad.l}" y1="${y}" x2="${pad.l+cw}" y2="${y}" stroke="var(--border)" stroke-width="0.5"/>`;
  }).join('');

  // X axis: show ~5 date labels
  const xStep = Math.max(1, Math.floor(visDates.length/5));
  const xLabels = visDates.map((d, i) => {
    if (i % xStep !== 0 && i !== visDates.length-1) return '';
    const [x] = px(i, 0);
    return `<text x="${x}" y="${pad.t+ch+18}" text-anchor="middle" font-size="9" fill="var(--muted)">${d.slice(5)}</text>`;
  }).join('');

  // Path + area per series
  const paths = series.map((s, si) => {
    const avged = allAvged[si];
    const pts = avged.map((v, i) => px(i, v));
    if (!pts.length) return '';
    const d = pts.map(([x,y],i) => (i===0?'M':'L')+x.toFixed(1)+' '+y.toFixed(1)).join(' ');
    const areaBottom = pad.t + ch;
    const area = pts.map(([x,y],i) => (i===0?'M':'L')+x.toFixed(1)+' '+y.toFixed(1)).join(' ')
      + ` L${pts[pts.length-1][0].toFixed(1)} ${areaBottom} L${pts[0][0].toFixed(1)} ${areaBottom} Z`;
    return `<path d="${area}" fill="${s.color}" fill-opacity="0.08"/>
      <path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
      ${pts.map(([x,y],i) => i===pts.length-1 ? `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" fill="${s.color}"/>` : '').join('')}`;
  }).join('');

  return `<svg class="chart-svg" viewBox="0 0 ${w} ${h}" style="max-height:${h}px">
    ${yLabels}${xLabels}
    <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${pad.t+ch}" stroke="var(--border)" stroke-width="1"/>
    ${paths}
  </svg>`;
}

// ── Model Detail Modal ────────────────────────────────────────────────
let spendHistory = null;

async function getHistory() {
  if (spendHistory) return spendHistory;
  try {
    const r = await fetch('/api/spend-history');
    spendHistory = await r.json();
  } catch(e) { spendHistory = {}; }
  return spendHistory;
}

function handleCardClick(e, modelId) {
  // Don't open if clicking the checkbox label
  if (e.target.closest('.compare-cb')) return;
  openModelDetail(modelId);
}

async function openModelDetail(modelId) {
  const m = allModels.find(x => x.model_id === modelId);
  if (!m) return;
  const modal = document.getElementById('model-modal');
  const eff = computeEff(m);
  const inp = m.pricing?.input_per_mtok ?? null;
  const ctx = m.context_window;
  const spend = m.spend;

  // Header
  document.getElementById('modal-name').textContent = m.model_name;
  document.getElementById('modal-sub').textContent =
    [m.provider, m.version ? 'v'+m.version : null, m.release_date].filter(Boolean).join(' · ');

  // Donuts
  const ctxPct = Math.min(100, (ctx||0)/12000);
  // Donut rule: only use ring when value is a genuine 0-100 score or %.
  // Prices, counts, context size have no natural ceiling — use plain stat tile.
  const ctxLabel = ctx ? (ctx>=1e6?(ctx/1e6).toFixed(1)+'M':Math.round(ctx/1000)+'k') : '?';
  const avgCostPerCall = spend?.call_count > 0
    ? '$' + (spend.total_cost_usd / spend.call_count).toFixed(5) + '/call' : '';
  document.getElementById('modal-donuts').innerHTML = [
    // Efficiency 0-100 → donut ✓
    modalDonutStat(eff, effColor(eff), `${eff}<span style="font-size:12px;font-weight:400;color:var(--muted)">/100</span>`, 'Efficiency', 'capability ÷ cost'),
    // Input price: $ amount, no ceiling → plain
    modalPlainStat(inp != null ? `$${inp}/M` : '?', 'Input Price', m.pricing?.output_per_mtok != null ? `$${m.pricing.output_per_mtok}/M out` : '', '#34d399'),
    // Context: token count, no ceiling → plain
    modalPlainStat(ctxLabel, 'Context Window', '', '#2563eb'),
    // Spend: dollar amount → plain
    spend?.total_cost_usd > 0
      ? modalPlainStat(`$${spend.total_cost_usd.toFixed(2)}`, 'Total Spend', avgCostPerCall, '#f87171')
      : '',
    // Call count: no ceiling → plain
    spend?.call_count > 0
      ? modalPlainStat(spend.call_count.toLocaleString(), 'API Calls', spend.period_start ? `${spend.period_start} → ${spend.period_end}` : '', '#fbbf24')
      : '',
    // Confidence 0-100% → donut ✓
    m._meta?.confidence
      ? modalDonutStat(m._meta.confidence * 100, '#a78bfa', `${Math.round(m._meta.confidence * 100)}%`, 'Data Confidence', '')
      : '',
  ].join('');

  // Body: notes + strengths/weaknesses
  const strengths = m.strengths || [];
  const weaknesses = m.weaknesses || [];
  const useCases = m.ideal_use_cases || [];
  const notes = m.performance_notes || '';
  const directP = m.direct_pricing;
  const meta = m._meta || {};
  const benchmarks = meta.benchmarks || {};
  const industryNotes = meta.industry_notes || [];

  // Benchmark formatting. Each source gets a card with its own fields.
  const BENCH_LABELS = {
    artificial_analysis: {
      title: 'Artificial Analysis',
      fields: {
        intelligence_index: { label: 'Intelligence Index', fmt: v => `${v} / 100` },
        output_tps: { label: 'Output Speed', fmt: v => `${v} tok/s` },
        ttft_s: { label: 'Time to First Token', fmt: v => `${v}s` }
      }
    },
    livebench: {
      title: 'LiveBench (decontaminated)',
      fields: {
        reasoning: { label: 'Reasoning', fmt: v => `${v}` },
        coding: { label: 'Coding', fmt: v => `${v}` },
        mathematics: { label: 'Mathematics', fmt: v => `${v}` },
        data_analysis: { label: 'Data Analysis', fmt: v => `${v}` },
        language: { label: 'Language', fmt: v => `${v}` },
        instruction_following: { label: 'Instruction Following', fmt: v => `${v}` },
        global_average: { label: 'Global Average', fmt: v => `${v}` }
      }
    },
    gaia: {
      title: 'GAIA (agentic multi-step)',
      fields: {
        level_1: { label: 'Level 1', fmt: v => `${Math.round(v*100)}%` },
        level_2: { label: 'Level 2', fmt: v => `${Math.round(v*100)}%` },
        level_3: { label: 'Level 3', fmt: v => `${Math.round(v*100)}%` },
        average: { label: 'Average', fmt: v => `${Math.round(v*100)}%` }
      }
    },
    tau_bench: {
      title: 'TAU-bench (tool use)',
      fields: {
        retail: { label: 'Retail', fmt: v => `${Math.round(v*100)}%` },
        airline: { label: 'Airline', fmt: v => `${Math.round(v*100)}%` }
      }
    },
    lmsys_arena_elo: {
      title: 'LMSYS Arena',
      fields: {
        score: { label: 'ELO', fmt: v => `${v}` },
        rank: { label: 'Rank', fmt: v => `#${v}` }
      }
    },
    aider: {
      title: 'Aider (code edit)',
      fields: {
        edit_pct: { label: 'Edit Accuracy', fmt: v => `${Math.round(v*100)}%` },
        refactor_pct: { label: 'Refactor', fmt: v => `${Math.round(v*100)}%` }
      }
    },
    swe_bench: {
      title: 'SWE-bench',
      fields: {
        verified_pct: { label: 'Verified', fmt: v => `${Math.round(v*100)}%` }
      }
    },
    openrouter_stats: {
      title: 'OpenRouter (production)',
      fields: {
        latency_p50_ms: { label: 'Latency p50', fmt: v => `${v}ms` },
        latency_p95_ms: { label: 'Latency p95', fmt: v => `${v}ms` },
        throughput_tps: { label: 'Throughput', fmt: v => `${v} tok/s` },
        error_rate_pct: { label: 'Error rate', fmt: v => `${v}%` }
      }
    }
  };

  const renderBenchCard = (sourceKey) => {
    const src = benchmarks[sourceKey];
    const def = BENCH_LABELS[sourceKey];
    if (!src || !def) return '';
    const rows = Object.entries(def.fields)
      .filter(([k,_]) => src[k] != null)
      .map(([k, cfg]) => `<div class="bench-row"><span>${cfg.label}</span><span class="bench-val">${cfg.fmt(src[k])}</span></div>`)
      .join('');
    if (!rows) return '';
    const asof = src.as_of ? `<span class="bench-asof">${src.as_of}</span>` : '';
    return `<div class="bench-card">
      <div class="bench-card-title"><span>${def.title}</span>${asof}</div>
      ${rows}
    </div>`;
  };

  const benchCards = Object.keys(BENCH_LABELS).map(renderBenchCard).filter(Boolean).join('');
  const hasAnyBench = benchCards.length > 0;

  const renderIndustryNote = (n) => {
    const tags = (n.tags || []).map(t => `<span class="industry-note-tag">${t}</span>`).join('');
    const cite = n.url
      ? `<a href="${n.url}" target="_blank" rel="noopener">${n.source}</a>`
      : n.source;
    const asof = n.as_of ? `<span>${n.as_of}</span>` : '';
    return `<div class="industry-note">
      <div class="industry-note-quote">"${(n.note||'').replace(/"/g,'&quot;')}"</div>
      <div class="industry-note-cite"><span>— ${cite}</span>${asof}</div>
      ${tags ? `<div class="industry-note-tags">${tags}</div>` : ''}
    </div>`;
  };
  document.getElementById('modal-body').innerHTML = `
    ${notes ? `<div class="modal-section" style="grid-column:1/-1">
      <div class="modal-section-title">Performance Notes</div>
      <div class="modal-notes">${notes}</div>
    </div>` : ''}
    ${strengths.length ? `<div class="modal-section">
      <div class="modal-section-title">Strengths</div>
      <ul class="modal-list">${strengths.map(s=>`<li>${s}</li>`).join('')}</ul>
    </div>` : ''}
    ${weaknesses.length ? `<div class="modal-section">
      <div class="modal-section-title">Weaknesses</div>
      <ul class="modal-list">${weaknesses.map(s=>`<li class="weak">${s}</li>`).join('')}</ul>
    </div>` : ''}
    ${useCases.length ? `<div class="modal-section">
      <div class="modal-section-title">Ideal Use Cases</div>
      <ul class="modal-list">${useCases.map(s=>`<li>${s}</li>`).join('')}</ul>
    </div>` : ''}
    ${directP ? `<div class="modal-section">
      <div class="modal-section-title">Direct API</div>
      <ul class="modal-list">
        ${directP.direct_available ? '<li>Direct API available</li>' : '<li class="weak">OpenRouter only</li>'}
        ${directP.batch_input_per_mtok ? `<li>Batch: $${directP.batch_input_per_mtok}/M in</li>` : ''}
        ${directP.cache_read_per_mtok ? `<li>Cache read: $${directP.cache_read_per_mtok}/M</li>` : ''}
        ${directP.notes ? `<li>${directP.notes}</li>` : ''}
      </ul>
    </div>` : ''}
    ${spend?.total_cost_usd > 0 ? `<div class="modal-section">
      <div class="modal-section-title">Spend Summary</div>
      <ul class="modal-list">
        <li>Total: $${spend.total_cost_usd.toFixed(4)}</li>
        <li>${spend.call_count.toLocaleString()} calls · $${spend.avg_cost_per_call_usd.toFixed(5)}/call</li>
        <li>Input: ${spend.total_input_mtok.toFixed(2)}M tok</li>
        <li>Output: ${spend.total_output_mtok.toFixed(2)}M tok</li>
        ${spend.total_cache_read_mtok > 0 ? `<li>Cached: ${spend.total_cache_read_mtok.toFixed(2)}M tok</li>` : ''}
        ${spend.period_start ? `<li>${spend.period_start} → ${spend.period_end}</li>` : ''}
      </ul>
    </div>` : ''}
    ${hasAnyBench || industryNotes.length > 0 ? `<div class="modal-section" style="grid-column:1/-1">
      <div class="modal-section-title">Industry Benchmarks</div>
      ${hasAnyBench
        ? `<div class="bench-grid">${benchCards}</div>`
        : `<div class="bench-pending">No benchmark data yet — run <code>scripts/enrich_benchmarks.py</code> to pull from LiveBench / Artificial Analysis / GAIA / Aider. (Stubs pending source URLs.)</div>`}
    </div>` : ''}
    ${industryNotes.length > 0 ? `<div class="modal-section" style="grid-column:1/-1">
      <div class="modal-section-title">Industry Notes</div>
      ${industryNotes.map(renderIndustryNote).join('')}
    </div>` : ''}`;

  // Charts (async)
  const chartsEl = document.getElementById('modal-charts');
  chartsEl.innerHTML = '<div class="loading"><span class="spinner"></span>Loading trend data…</div>';
  modal.classList.add('open');
  document.body.style.overflow = 'hidden';

  const hist = await getHistory();
  const modelHist = hist[m.model_id] || hist[m.openrouter_slug] || [];

  if (modelHist.length < 2) {
    chartsEl.innerHTML = `<div class="chart-no-data" style="margin-top:16px">
      Daily trend data is accumulating — check back after a few more hourly syncs.<br>
      <span style="font-size:11px;color:var(--muted)">(${modelHist.length} day${modelHist.length===1?'':'s'} of data so far)</span>
    </div>`;
    return;
  }

  const dates = modelHist.map(d => d.date);

  // Each series carries its own accessor — no shared null accessor needed
  const costSeries = [{label:'Cost', color:'#f87171', data:modelHist, accessor: d => d.cost_usd}];
  const tokenSeries = [
    {label:'Input', color:'#2563eb', data:modelHist, accessor: d => (d.input_tokens||0)/1e6},
    {label:'Output', color:'#34d399', data:modelHist, accessor: d => (d.output_tokens||0)/1e6},
  ];

  chartsEl.innerHTML = `
    <div style="display:grid;gap:24px;margin-top:20px">
      <div>
        <div class="chart-title">Daily Cost (USD) — 7-day rolling avg</div>
        ${lineChart(dates, costSeries, null, 780, 160, v=>'$'+v.toFixed(3))}
      </div>
      <div>
        <div class="chart-title">Daily Token Volume (Millions) — 7-day rolling avg</div>
        ${lineChart(dates, tokenSeries, null, 780, 180, v=>v.toFixed(2)+'M')}
        <div class="chart-legend" style="margin-top:6px">
          <div class="chart-legend-item"><div class="chart-legend-dot" style="background:#2563eb"></div>Input</div>
          <div class="chart-legend-item"><div class="chart-legend-dot" style="background:#34d399"></div>Output</div>
        </div>
      </div>
    </div>`;
}

function closeModal() {
  document.getElementById('model-modal').classList.remove('open');
  document.body.style.overflow = '';
}

function handleModalBackdropClick(e) {
  if (e.target === document.getElementById('model-modal')) closeModal();
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

// ── Changelog ──────────────────────────────────────────────────────────
async function loadChangelog() {
  const res = await fetch('/api/changelog');
  const data = await res.json();
  const body = document.getElementById('changelog-body');
  // Simple markdown → HTML (headings, lists, code, hr)
  let html = data.content
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/^#{1}\s+(.+)$/gm, '<h1>$1</h1>')
    .replace(/^#{2}\s+(.+)$/gm, '<h2>$1</h2>')
    .replace(/^#{3}\s+(.+)$/gm, '<h3>$1</h3>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^---$/gm, '<hr>')
    .replace(/^\*\s+(.+)$/gm, '<li>$1</li>')
    .replace(/^-\s+(.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, s => `<ul>${s}</ul>`)
    .replace(/\n\n/g, '</p><p>')
    .replace(/^(?!<[hul]|<hr|<li|<\/)/gm, '');
  body.innerHTML = html;
}

// ── Feedback ───────────────────────────────────────────────────────────
async function loadFeedback() {
  const res = await fetch('/api/feedback');
  const data = await res.json();
  const el = document.getElementById('fb-history');
  if (!data.entries || !data.entries.length) {
    el.innerHTML = '<div class="empty">No feedback yet.</div>'; return;
  }
  el.innerHTML = data.entries.slice().reverse().slice(0,10).map(e => `
    <div class="fb-entry">
      <div class="fb-entry-header">
        <span class="fb-entry-type ${e.type}">${e.type}</span>
        <span class="fb-entry-time">${e.ts ? new Date(e.ts).toLocaleDateString() : ''}</span>
      </div>
      <div class="fb-entry-text">${e.text || e.query || ''}</div>
    </div>`).join('');
}

async function submitFeedback() {
  const text = document.getElementById('fb-text').value.trim();
  if (!text) return;
  const payload = {
    type: document.getElementById('fb-type').value,
    priority: document.getElementById('fb-priority').value,
    text
  };
  const res = await fetch('/api/feedback', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  const data = await res.json();
  document.getElementById('fb-status').innerHTML = data.ok
    ? '<div class="status ok">✓ Feedback saved</div>'
    : `<div class="status err">✗ ${data.error}</div>`;
  if (data.ok) { document.getElementById('fb-text').value = ''; loadFeedback(); }
}

// ── Sync ───────────────────────────────────────────────────────────────
async function triggerSync() {
  const btn = document.querySelector('.sync-btn');
  btn.textContent = '↻ Syncing…';
  btn.disabled = true;
  const res = await fetch('/api/sync', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({apply: true})});
  const data = await res.json();
  btn.textContent = data.ok ? '✓ Synced' : '✗ Failed';
  btn.disabled = false;
  if (data.ok) { await loadModels(); }
  setTimeout(() => { btn.textContent = '↻ Sync OpenRouter'; }, 3000);
}

// ── Ingest ─────────────────────────────────────────────────────────────
async function runIngest() {
  const text = document.getElementById('ingest-text').value.trim();
  if (!text) return;
  const out = document.getElementById('ingest-out').value.trim() || 'models.generated.json';
  document.getElementById('ingest-results').innerHTML = '<div class="loading"><span class="spinner"></span>Ingesting…</div>';
  const res = await fetch('/api/ingest', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text, out})});
  const data = await res.json();
  document.getElementById('ingest-results').innerHTML = data.ok
    ? `<div class="status ok">✓ ${data.message}</div>`
    : `<div class="status err">✗ ${data.error}</div>`;
  if (data.ok) loadModels();
}

// ── Usage Tab ──────────────────────────────────────────────────────────
let pendingCsvFile = null;

function handleCsvDrop(e) {
  e.preventDefault();
  document.getElementById('csv-drop').style.borderColor = 'var(--border)';
  const file = e.dataTransfer.files[0];
  if (file) handleCsvFile(file);
}

function handleCsvFile(file) {
  if (!file || !file.name.endsWith('.csv')) {
    document.getElementById('csv-preview').innerHTML = '<div class="status err">Please select a .csv file</div>';
    return;
  }
  pendingCsvFile = file;
  document.getElementById('csv-drop').style.borderColor = 'var(--green)';
  document.getElementById('csv-preview').innerHTML =
    `<div class="status ok">✓ ${file.name} (${(file.size/1024).toFixed(1)} KB) — ready to import</div>`;
  document.getElementById('csv-upload-btn').style.display = '';
  document.getElementById('csv-clear-btn').style.display = '';
}

function clearCsvUpload() {
  pendingCsvFile = null;
  document.getElementById('csv-drop').style.borderColor = 'var(--border)';
  document.getElementById('csv-preview').innerHTML = '';
  document.getElementById('csv-upload-btn').style.display = 'none';
  document.getElementById('csv-clear-btn').style.display = 'none';
  document.getElementById('csv-status').innerHTML = '';
  document.getElementById('csv-file').value = '';
}

async function uploadCsv() {
  if (!pendingCsvFile) return;
  const btn = document.getElementById('csv-upload-btn');
  btn.textContent = 'Importing…'; btn.disabled = true;
  const form = new FormData();
  form.append('file', pendingCsvFile);
  const res = await fetch('/api/import-spend', { method: 'POST', body: form });
  const data = await res.json();
  btn.textContent = 'Import Spend Data'; btn.disabled = false;
  if (data.ok) {
    document.getElementById('csv-status').innerHTML =
      `<div class="status ok">✓ ${data.message}</div>`;
    clearCsvUpload();
    spendHistory = null; // invalidate cache so modal re-fetches updated history
    await loadModels();
    renderSpendChart();
    renderSpendTable();
  } else {
    document.getElementById('csv-status').innerHTML =
      `<div class="status err">✗ ${data.error}</div>`;
  }
}

function renderSpendChart() {
  const withSpend = allModels.filter(m => (m.spend?.total_cost_usd || 0) > 0)
    .sort((a,b) => (b.spend.total_cost_usd||0) - (a.spend.total_cost_usd||0));
  const el = document.getElementById('spend-chart');
  if (!withSpend.length) {
    el.innerHTML = '<div class="empty" style="padding:20px">No spend data yet.<br>Import your OpenRouter CSV to see costs here.</div>';
    return;
  }
  const total = withSpend.reduce((s,m) => s + m.spend.total_cost_usd, 0);
  const bars = withSpend.slice(0, 10).map(m => {
    const pct = (m.spend.total_cost_usd / total * 100).toFixed(1);
    const barW = Math.max(4, Math.round(m.spend.total_cost_usd / withSpend[0].spend.total_cost_usd * 100));
    return `<div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px">
        <span style="color:var(--text);font-weight:600">${m.model_name}</span>
        <span style="color:var(--amber);font-weight:700">$${m.spend.total_cost_usd.toFixed(4)} (${pct}%)</span>
      </div>
      <div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden">
        <div style="height:100%;width:${barW}%;background:var(--amber);border-radius:3px"></div>
      </div>
      <div style="font-size:10px;color:var(--muted);margin-top:2px">
        ${m.spend.call_count.toLocaleString()} calls · $${m.spend.avg_cost_per_call_usd.toFixed(5)}/call ·
        ${m.spend.total_input_mtok.toFixed(2)}M in · ${m.spend.total_output_mtok.toFixed(2)}M out
        ${m.spend.total_cache_read_mtok > 0 ? ` · ${m.spend.total_cache_read_mtok.toFixed(2)}M cached` : ''}
      </div>
    </div>`;
  }).join('');
  el.innerHTML = `
    <div style="font-size:11px;color:var(--muted);margin-bottom:12px">
      Total: <strong style="color:var(--amber)">$${total.toFixed(4)}</strong> across ${withSpend.length} models
      ${withSpend[0]?.spend?.period_start ? ` · ${withSpend[0].spend.period_start} → ${withSpend[0].spend.period_end}` : ''}
    </div>
    ${bars}`;
}

function renderSpendTable() {
  const withSpend = allModels.filter(m => (m.spend?.total_cost_usd || 0) > 0)
    .sort((a,b) => (b.spend.total_cost_usd||0) - (a.spend.total_cost_usd||0));
  const el = document.getElementById('spend-table');
  if (!withSpend.length) { el.innerHTML = ''; return; }
  const rows = withSpend.map(m => {
    const dp = m.direct_pricing;
    const savingsFlag = dp?.batch_input_per_mtok
      ? `<span style="color:var(--green);font-size:11px">⚡ Batch API available</span>`
      : dp?.direct_available === false
      ? `<span style="color:var(--muted);font-size:11px">OpenRouter only</span>`
      : '';
    return `<tr>
      <td style="font-weight:600;color:var(--text)">${m.model_name}</td>
      <td style="color:var(--muted)">${m.provider}</td>
      <td style="color:var(--amber);font-weight:700">$${m.spend.total_cost_usd.toFixed(4)}</td>
      <td>${m.spend.call_count.toLocaleString()}</td>
      <td>$${m.spend.avg_cost_per_call_usd.toFixed(5)}</td>
      <td>${m.spend.total_input_mtok.toFixed(2)}M</td>
      <td>${m.spend.total_output_mtok.toFixed(2)}M</td>
      <td>${m.spend.total_cache_read_mtok > 0 ? m.spend.total_cache_read_mtok.toFixed(2)+'M' : '—'}</td>
      <td>${savingsFlag}</td>
    </tr>`;
  }).join('');
  el.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:12px">
    <thead><tr style="border-bottom:1px solid var(--border);color:var(--muted)">
      <th style="text-align:left;padding:8px 6px">Model</th>
      <th style="text-align:left;padding:8px 6px">Provider</th>
      <th style="text-align:left;padding:8px 6px">Total Cost</th>
      <th style="text-align:left;padding:8px 6px">Calls</th>
      <th style="text-align:left;padding:8px 6px">Avg/Call</th>
      <th style="text-align:left;padding:8px 6px">Input</th>
      <th style="text-align:left;padding:8px 6px">Output</th>
      <th style="text-align:left;padding:8px 6px">Cached</th>
      <th style="text-align:left;padding:8px 6px">Opportunity</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

// ── Tabs ───────────────────────────────────────────────────────────────
const TAB_NAMES = ['catalog','query','compare','usage','changelog','feedback','ingest','agents'];
function showTab(name) {
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', TAB_NAMES[i]===name));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-'+name).classList.add('active');
  localStorage.setItem('activeTab', name);
  if (name === 'changelog') loadChangelog();
  if (name === 'feedback') loadFeedback();
  if (name === 'usage') { renderSpendChart(); renderSpendTable(); }
  if (name === 'agents') loadAgents();
}

// ── Agents ──────────────────────────────────────────────────────────────
let agentModels = [];
async function loadAgents() {
  const [agentsRes, modelsData] = await Promise.all([
    fetch('/api/agents').then(r => r.json()),
    allModels.length ? Promise.resolve(allModels) : fetch('/api/models').then(r => r.json())
  ]);
  agentModels = agentsRes;
  const modelIds = modelsData.map(m => m.model_id).sort();
  const grid = document.getElementById('agents-grid');
  grid.innerHTML = agentsRes.map(a => {
    const opts = modelIds.map(id =>
      `<option value="${id}" ${id === a.primary ? 'selected' : ''}>${id}</option>`
    ).join('');
    const pendingBadge = a.pending_model ? `<span style="font-size:10px;color:var(--amber);background:#2d2006;padding:2px 6px;border-radius:4px;margin-left:4px">⏳ pending: ${a.pending_model}</span>` : '';
    const currentModel = a.pending_model || a.primary;
    return `<div style="background:var(--surface);border:1px solid ${a.pending_model ? 'var(--amber)' : 'var(--border)'};border-radius:10px;padding:16px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap">
        <span style="font-weight:600;font-size:14px">${a.name || a.agentId}</span>
        <span style="font-size:11px;color:var(--muted);background:var(--tag-bg);padding:2px 8px;border-radius:4px">${a.agentId}</span>
        ${pendingBadge}
      </div>
      <div style="font-size:11px;color:var(--muted);margin-bottom:6px">Primary Model</div>
      <div style="display:flex;gap:8px;align-items:center">
        <select id="model-sel-${a.agentId}" style="flex:1;padding:8px 10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px">
          ${opts}
        </select>
        <button onclick="setAgentModel('${a.agentId}')" style="padding:8px 16px;background:var(--accent);color:#fff;border:none;border-radius:6px;font-size:12px;font-weight:500;cursor:pointer;white-space:nowrap">Apply</button>
      </div>
      <div style="font-size:11px;color:var(--muted);margin-top:8px">Fallbacks: ${(a.fallbacks||[]).length ? a.fallbacks.join(', ') : 'none'}</div>
    </div>`;
  }).join('');
  loadAgentHistory();
}

async function setAgentModel(agentId) {
  const sel = document.getElementById('model-sel-' + agentId);
  const newModel = sel.value;
  const status = document.getElementById('agents-status');
  status.innerHTML = '<span style="color:var(--amber)">Applying...</span>';
  const res = await fetch('/api/agents/' + agentId + '/model', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({primary: newModel, restart_gateway: true})
  });
  const data = await res.json();
  if (data.ok) {
    if (data.mode === 'queued') {
      status.innerHTML = `<span style="color:var(--amber)">⏳ ${agentId}: ${data.old_primary} → ${data.new_primary} — queued, sync triggered</span>`;
    } else {
      status.innerHTML = `<span style="color:var(--green)">✓ ${agentId}: ${data.old_primary} → ${data.new_primary}${data.restarted ? ' (gateway restarted)' : ' (restart needed)'}</span>`;
    }
    loadAgents();
  } else {
    status.innerHTML = `<span style="color:var(--red)">✗ ${data.error}</span>`;
  }
}

async function loadAgentHistory() {
  const res = await fetch('/api/agents/all/model/history');
  const entries = await res.json();
  const el = document.getElementById('agents-history');
  if (!entries.length) { el.innerHTML = '<div style="color:var(--muted);padding:8px">No changes yet.</div>'; return; }
  el.innerHTML = `<table style="width:100%;border-collapse:collapse;margin-top:8px">
    <tr style="border-bottom:1px solid var(--border)">
      <th style="text-align:left;padding:6px;color:var(--muted);font-weight:500">Time</th>
      <th style="text-align:left;padding:6px;color:var(--muted);font-weight:500">Agent</th>
      <th style="text-align:left;padding:6px;color:var(--muted);font-weight:500">From</th>
      <th style="text-align:left;padding:6px;color:var(--muted);font-weight:500">To</th>
    </tr>
    ${entries.slice().reverse().slice(0,20).map(e => `<tr style="border-bottom:1px solid var(--border)">
      <td style="padding:6px;font-size:11px">${new Date(e.timestamp).toLocaleString()}</td>
      <td style="padding:6px"><span style="background:var(--tag-bg);padding:2px 6px;border-radius:4px;font-size:11px">${e.agent}</span></td>
      <td style="padding:6px;font-size:11px;color:var(--muted)">${e.old_primary}</td>
      <td style="padding:6px;font-size:11px;color:var(--green)">${e.new_primary}</td>
    </tr>`).join('')}
  </table>`;
}

loadModels().then(() => {
  populateCompareSelects();
  const savedTab = localStorage.getItem('activeTab');
  if (savedTab && TAB_NAMES.includes(savedTab)) showTab(savedTab);
});
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');
</script>
</body>
</html>"""


LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Model Repo — Login</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #0f1117; color: #e2e8f0; min-height: 100vh;
  display: flex; align-items: center; justify-content: center; }
.card { background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px;
  padding: 40px; width: 100%; max-width: 380px; }
h1 { font-size: 1.25rem; font-weight: 600; margin-bottom: 6px; color: #e2e8f0; }
p { font-size: 0.85rem; color: #64748b; margin-bottom: 28px; }
label { font-size: 0.8rem; color: #94a3b8; display: block; margin-bottom: 6px; }
input[type=password] { width: 100%; padding: 10px 14px; background: #0f1117;
  border: 1px solid #2d3148; border-radius: 8px; color: #e2e8f0;
  font-size: 0.95rem; outline: none; transition: border-color 0.15s; }
input[type=password]:focus { border-color: #2563eb; }
button { width: 100%; margin-top: 16px; padding: 11px;
  background: #2563eb; color: #fff; border: none; border-radius: 8px;
  font-size: 0.95rem; font-weight: 500; cursor: pointer; transition: background 0.15s; }
button:hover { background: #1d4ed8; }
.error { margin-top: 14px; font-size: 0.82rem; color: #f87171; text-align: center; }
.logo { font-size: 1.8rem; margin-bottom: 16px; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">🧠</div>
  <h1>AI Model Repository</h1>
  <p>Intelligence mapping for the agent stack</p>
  <form method="POST" action="/login">
    <label>Access key</label>
    <input type="password" name="password" autofocus placeholder="••••••••••••••">
    {% if totp_required %}
    <label style="margin-top:16px">2FA Code</label>
    <input type="text" name="totp_code" placeholder="6-digit code" maxlength="6" pattern="[0-9]{6}"
      style="width:100%;padding:10px 14px;background:#0f1117;border:1px solid #2d3148;border-radius:8px;color:#e2e8f0;font-size:1.1rem;letter-spacing:6px;text-align:center">
    {% endif %}
    <button type="submit">Enter</button>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
  </form>
</div>
</body>
</html>"""


def _check_password(candidate: str) -> bool:
    if UI_PASSWORD_HASH:
        candidate_hash = hashlib.sha256(candidate.encode()).hexdigest()
        return hmac.compare_digest(candidate_hash, UI_PASSWORD_HASH)
    return hmac.compare_digest(candidate, UI_PASSWORD)


def _check_api_token() -> bool:
    if not API_TOKEN:
        return False
    token = request.headers.get("X-API-Token", "") or request.args.get("api_token", "")
    return hmac.compare_digest(token, API_TOKEN)


_login_attempts: dict[str, list[float]] = {}
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 300


def _is_locked_out(ip: str) -> bool:
    attempts = _login_attempts.get(ip, [])
    recent = [t for t in attempts if time.time() - t < LOCKOUT_SECONDS]
    _login_attempts[ip] = recent
    return len(recent) >= MAX_LOGIN_ATTEMPTS


def _record_failed_attempt(ip: str):
    _login_attempts.setdefault(ip, []).append(time.time())


def require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if _check_api_token():
            return f(*args, **kwargs)
        if not session.get("authed"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    ip = request.remote_addr or "unknown"
    if _is_locked_out(ip):
        error = "Too many attempts. Try again in 5 minutes."
        return render_template_string(LOGIN_HTML, error=error, totp_required=TOTP_REQUIRED), 429
    if request.method == "POST":
        time.sleep(0.5)
        pw_ok = _check_password(request.form.get("password", ""))
        totp_ok = True
        if TOTP_REQUIRED and HAS_TOTP and TOTP_SECRET:
            totp_code = request.form.get("totp_code", "").strip()
            totp = pyotp.TOTP(TOTP_SECRET)
            totp_ok = totp.verify(totp_code, valid_window=1)
        if pw_ok and totp_ok:
            session["authed"] = True
            session["login_ip"] = ip
            session["login_at"] = datetime.now(timezone.utc).isoformat()
            _login_attempts.pop(ip, None)
            return redirect(url_for("index"))
        _record_failed_attempt(ip)
        if not pw_ok:
            error = "Invalid access key"
        else:
            error = "Invalid 2FA code"
    return render_template_string(LOGIN_HTML, error=error, totp_required=TOTP_REQUIRED)


@app.route("/setup-2fa")
def setup_2fa():
    if not HAS_TOTP:
        return "pyotp not installed", 500
    if TOTP_SECRET:
        secret = TOTP_SECRET
    else:
        secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name="eric@openclaw", issuer_name="AI Model Repo")
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgImage)
    buf = io.BytesIO()
    img.save(buf)
    svg_data = buf.getvalue().decode()
    return render_template_string(SETUP_2FA_HTML, secret=secret, svg=svg_data, uri=uri)


SETUP_2FA_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Setup 2FA</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #0f1117; color: #e2e8f0;
  min-height: 100vh; display: flex; align-items: center; justify-content: center; }
.card { background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px; padding: 40px; max-width: 420px; text-align: center; }
h1 { font-size: 1.2rem; margin-bottom: 16px; }
p { font-size: 0.85rem; color: #94a3b8; margin-bottom: 16px; }
.secret { font-family: monospace; background: #0f1117; padding: 10px; border-radius: 6px; font-size: 14px;
  letter-spacing: 2px; color: #34d399; margin: 12px 0; word-break: break-all; }
svg { max-width: 200px; margin: 16px auto; display: block; }
</style></head><body>
<div class="card">
<h1>Setup Two-Factor Authentication</h1>
<p>Scan this QR code with Google Authenticator, Authy, or any TOTP app:</p>
{{ svg | safe }}
<p style="margin-top:16px">Or enter this secret manually:</p>
<div class="secret">{{ secret }}</div>
<p style="margin-top:20px;font-size:12px;color:#64748b">
  Then set these Railway env vars:<br>
  <code>TOTP_SECRET={{ secret }}</code><br>
  <code>TOTP_REQUIRED=true</code>
</p>
</div></body></html>"""


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@require_login
def index():
    return render_template_string(HTML)


@app.route("/health")
def health():
    models_count = 0
    if MODELS_FILE.exists():
        try:
            models_count = len(json.loads(MODELS_FILE.read_text()))
        except Exception:
            return jsonify({"ok": False, "error": "models.json unreadable"}), 500
    return jsonify({
        "ok": True,
        "service": "ai-model-repo",
        "models_count": models_count,
        "generated_exists": GENERATED_FILE.exists(),
        "feedback_exists": FEEDBACK_FILE.exists(),
    })


@app.route("/api/models")
@require_login
def api_models():
    return jsonify(load_models())


@app.route("/api/changelog")
@require_login
def api_changelog():
    if not CHANGELOG_FILE.exists():
        return jsonify({"content": "No changelog found."})
    return jsonify({"content": CHANGELOG_FILE.read_text()})


@app.route("/api/feedback", methods=["GET", "POST"])
@require_login
def api_feedback():
    entries = []
    if FEEDBACK_FILE.exists():
        try:
            entries = json.loads(FEEDBACK_FILE.read_text())
        except Exception:
            entries = []

    if request.method == "GET":
        return jsonify({"entries": entries})

    data = request.get_json()
    entry = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "type": data.get("type", "note"),
        "priority": data.get("priority", "normal"),
        "text": data.get("text", ""),
        "query": data.get("query", ""),
        "vote": data.get("vote", ""),
        "model_id": data.get("model_id", ""),
    }
    entries.append(entry)
    FEEDBACK_FILE.write_text(json.dumps(entries, indent=2))
    return jsonify({"ok": True})


@app.route("/api/query", methods=["POST"])
@require_login
def api_query():
    data = request.get_json()
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "No query provided"}), 400
    # Route to recommend logic directly (better than subprocess)
    stopwords = {"best", "model", "for", "with", "and", "the", "a", "an", "that", "is", "are"}
    task_words = [w for w in query.lower().split() if len(w) > 2 and w not in stopwords]
    models = load_models()

    def score(m):
        tags = set(m.get("routing_tags") or [])
        s_text = " ".join(m.get("strengths") or []).lower()
        uc_text = " ".join(m.get("ideal_use_cases") or []).lower()
        tag_match = sum(1 for w in task_words if w in tags)
        text_match = sum(1 for w in task_words if w in s_text or w in uc_text)
        cost = (m.get("pricing") or {}).get("input_per_mtok", 999)
        confidence = (m.get("_meta") or {}).get("confidence", 0.5)
        penalty = 0.4 if (m.get("_meta") or {}).get("needs_review") else 1.0
        return (tag_match * 4 + text_match * 2 + 1/(cost+0.01)*0.05 + confidence*2) * penalty

    ranked = sorted(models, key=score, reverse=True)[:6]
    return jsonify({"results": ranked})


@app.route("/api/compare", methods=["POST"])
@require_login
def api_compare():
    data = request.get_json()
    a_id = data.get("model_a", "")
    b_id = data.get("model_b", "")
    task = data.get("task", "general")
    models = load_models()
    model_map = {m["model_id"]: m for m in models}
    ma = model_map.get(a_id)
    mb = model_map.get(b_id)
    if not ma or not mb:
        return jsonify({"error": f"Model not found: {a_id or b_id}"}), 404

    task_tags = {
        "coding": ["coding", "code", "specialist", "builds"],
        "reasoning": ["reasoning", "analysis", "balanced", "brains"],
        "summarization": ["summarization", "fast-response"],
        "agentic": ["agentic", "tool-use", "muscle", "email"],
        "low-cost": ["low-cost", "cron", "high-volume"],
        "general": ["balanced", "reasoning"],
    }.get(task, ["balanced"])

    def score(m):
        tags = m.get("routing_tags", [])
        cost = (m.get("pricing") or {}).get("input_per_mtok", 999)
        tag_score = sum(1 for t in task_tags if t in tags)
        cost_score = 1 / (cost + 0.01)
        confidence = (m.get("_meta") or {}).get("confidence", 0.5)
        return tag_score * 3 + cost_score * 0.1 + confidence * 2

    winner = ma if score(ma) >= score(mb) else mb
    loser = mb if winner is ma else ma
    rec = (f"For {task} tasks: {winner['model_name']} wins — "
           f"better tag alignment{' and lower cost' if (winner.get('pricing',{}).get('input_per_mtok',999) < loser.get('pricing',{}).get('input_per_mtok',999)) else ''}.")
    return jsonify({"model_a": ma, "model_b": mb, "recommendation": rec})


@app.route("/api/ingest", methods=["POST"])
@require_login
def api_ingest():
    data = request.get_json()
    text = data.get("text", "").strip()
    out = data.get("out", "models.generated.json")
    if not text:
        return jsonify({"ok": False, "error": "No text provided"}), 400
    try:
        out_path = REPO_DIR / out
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "ingest.py"), "--out", str(out_path), text],
            capture_output=True, text=True, timeout=60, cwd=str(REPO_DIR)
        )
        if result.returncode != 0:
            return jsonify({"ok": False, "error": result.stderr[:500] or result.stdout[:500]})
        return jsonify({"ok": True, "message": result.stdout.strip() or f"Ingested to {out}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/recommend", methods=["GET"])
@require_login
def api_recommend():
    task = request.args.get("task", "").lower().strip()
    budget = request.args.get("budget", type=float)
    min_context = request.args.get("context", 0, type=int)
    top_n = request.args.get("top", 5, type=int)
    models = load_models()
    if min_context:
        models = [m for m in models if (m.get("context_window") or 0) >= min_context]
    if budget is not None:
        models = [m for m in models if (m.get("pricing") or {}).get("input_per_mtok", 999) <= budget]

    task_words = set(task.split()) if task else set()

    def score(m):
        tags = set(m.get("routing_tags") or [])
        s_text = " ".join(m.get("strengths") or []).lower()
        uc_text = " ".join(m.get("ideal_use_cases") or []).lower()
        tag_match = len(tags & task_words)
        text_match = sum(1 for w in task_words if w in s_text or w in uc_text)
        cost = (m.get("pricing") or {}).get("input_per_mtok", 999)
        confidence = (m.get("_meta") or {}).get("confidence", 0.5)
        penalty = 0.5 if (m.get("_meta") or {}).get("needs_review") else 1.0
        return (tag_match * 3 + text_match * 2 + 1/(cost+0.01)*0.1 + confidence) * penalty

    ranked = sorted(models, key=score, reverse=True)[:top_n]
    results = []
    for m in ranked:
        p = m.get("pricing") or {}
        results.append({
            "model_id": m["model_id"], "model_name": m.get("model_name"),
            "provider": m.get("provider"), "openrouter_slug": m.get("openrouter_slug"),
            "input_per_mtok": p.get("input_per_mtok"), "output_per_mtok": p.get("output_per_mtok"),
            "context_window": m.get("context_window"), "routing_tags": m.get("routing_tags", []),
            "strengths": m.get("strengths", []), "ideal_use_cases": m.get("ideal_use_cases", []),
            "performance_notes": m.get("performance_notes", ""),
            "confidence": (m.get("_meta") or {}).get("confidence", 0.5),
            "needs_review": (m.get("_meta") or {}).get("needs_review", False),
        })
    return jsonify({"ok": True, "task": task, "count": len(results), "models": results})


@app.route("/api/import-spend", methods=["POST"])
@require_login
def api_import_spend():
    """
    Upload a provider activity CSV (OpenRouter, Anthropic, or OpenAI).
    Auto-detects format. Writes totals to models.json AND daily breakpoints
    to spend_history.json — backfilling trend chart history from the export.
    """
    import tempfile

    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename or not f.filename.endswith(".csv"):
        return jsonify({"ok": False, "error": "File must be a .csv"}), 400

    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
            f.save(tmp)
            tmp_path = tmp.name

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "import_spend.py"), tmp_path, "--apply"],
            capture_output=True, text=True, timeout=60, cwd=str(REPO_DIR)
        )
        Path(tmp_path).unlink(missing_ok=True)

        if result.returncode != 0:
            return jsonify({"ok": False, "error": result.stderr[:500] or result.stdout[:500]})

        lines = result.stdout.strip().splitlines()
        models_line = next((l for l in lines if "models updated" in l or "models.json" in l), "")
        history_line = next((l for l in lines if "spend_history" in l or "model-day" in l), "")
        msg = " · ".join(filter(None, [models_line.strip(), history_line.strip()])) or "Import complete"
        return jsonify({"ok": True, "message": msg, "output": result.stdout[:1200]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/sync", methods=["POST"])
@require_login
def api_sync():
    data = request.get_json(silent=True) or {}
    apply_changes = data.get("apply", True)
    provider_filter = data.get("filter", "")
    cmd = [sys.executable, str(SCRIPTS_DIR / "ingest_openrouter.py")]
    if apply_changes:
        cmd += ["--apply", "--quiet"]
    if provider_filter:
        cmd += ["--filter", provider_filter]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90, cwd=str(REPO_DIR))
        return jsonify({"ok": result.returncode == 0, "output": result.stdout.strip() or result.stderr.strip()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/spend-history")
@require_login
def api_spend_history():
    if not SPEND_HISTORY_FILE.exists():
        return jsonify({})
    try:
        return jsonify(json.loads(SPEND_HISTORY_FILE.read_text()))
    except Exception:
        return jsonify({})


@app.route("/api/route", methods=["GET"])
@require_login
def api_route():
    """
    Routing decision endpoint — returns optimal endpoint for a given model + context.
    Used by agents to decide openrouter vs direct vs batch.

    GET /api/route?model=anthropic/claude-sonnet-4-6&prompt_tokens=50000&cacheable=1&batch=0
    """
    model_id = request.args.get("model", "")
    if not model_id:
        return jsonify({"error": "model parameter required"}), 400

    prompt_tokens = int(request.args.get("prompt_tokens", 1000))
    output_tokens = int(request.args.get("output_tokens", 500))
    cacheable = request.args.get("cacheable", "0") in ("1", "true", "yes")
    cache_hit_ratio = float(request.args.get("cache_hit_ratio", 0.3))
    batch = request.args.get("batch", "0") in ("1", "true", "yes")
    task = request.args.get("task", None)

    try:
        # Import inline to avoid module-level import issues with path
        import importlib.util
        spec = importlib.util.spec_from_file_location("routing_engine", SCRIPTS_DIR / "routing_engine.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.recommend_route(
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            cacheable=cacheable,
            cache_hit_ratio=cache_hit_ratio,
            batch=batch,
            real_time=not batch,
            task=task,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Agent Model Management ──────────────────────────────────────────────────

def _load_openclaw_config() -> dict:
    if not OPENCLAW_CONFIG.exists():
        return {}
    with open(OPENCLAW_CONFIG) as f:
        return json.load(f)


def _save_openclaw_config(cfg: dict):
    backup = OPENCLAW_CONFIG.parent / f"openclaw.json.bak.{int(time.time())}"
    shutil.copy2(OPENCLAW_CONFIG, backup)
    with open(OPENCLAW_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)
    json.load(open(OPENCLAW_CONFIG))


def _get_agents_with_models() -> list[dict]:
    cfg = _load_openclaw_config()
    agents = cfg.get("agents", {}).get("list", [])
    result = []
    for a in agents:
        model_cfg = a.get("model", {})
        agent_id = a.get("id", a.get("agentId", ""))
        result.append({
            "agentId": agent_id,
            "name": a.get("name", agent_id),
            "primary": model_cfg.get("primary", "default") if isinstance(model_cfg, dict) else str(model_cfg),
            "fallbacks": model_cfg.get("fallbacks", []) if isinstance(model_cfg, dict) else [],
        })
    return result


def _load_pending_changes() -> list[dict]:
    if PENDING_CHANGES_FILE.exists():
        try:
            return json.loads(PENDING_CHANGES_FILE.read_text())
        except Exception:
            pass
    return []


def _save_pending_changes(changes: list[dict]):
    PENDING_CHANGES_FILE.write_text(json.dumps(changes, indent=2))


def _trigger_sync_webhook():
    if not OPENCLAW_WEBHOOK_URL or not OPENCLAW_WEBHOOK_TOKEN:
        print("Webhook skipped: OPENCLAW_WEBHOOK_URL or TOKEN not set", file=sys.stderr, flush=True)
        return
    import urllib.request
    import urllib.error
    import ssl
    body = json.dumps({
        "message": "Model change queued in AI Model Repo. Run immediately: python3 /home/ericd/.openclaw/workspace-alexander/ai-model-repo/scripts/sync_pending.py",
        "agentId": "build",
        "name": "model-sync",
        "model": "anthropic/claude-sonnet-4-6",
        "timeoutSeconds": 120,
    }).encode()
    req = urllib.request.Request(
        f"{OPENCLAW_WEBHOOK_URL}/hooks/agent",
        data=body,
        headers={
            "Authorization": f"Bearer {OPENCLAW_WEBHOOK_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    ctx = ssl.create_default_context()
    try:
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        print(f"Webhook triggered: {resp.status} {resp.read().decode()}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"Webhook failed: {e}", file=sys.stderr, flush=True)
        try:
            ctx = ssl._create_unverified_context()
            resp = urllib.request.urlopen(req, timeout=10, context=ctx)
            print(f"Webhook triggered (unverified SSL): {resp.status}", file=sys.stderr, flush=True)
        except Exception as e2:
            print(f"Webhook retry failed: {e2}", file=sys.stderr, flush=True)


def _get_agents_from_pending() -> list[dict]:
    """On Railway (no local config), read agent list from env or pending changes."""
    agents_json = os.environ.get("AGENTS_CONFIG", "")
    if agents_json:
        try:
            return json.loads(agents_json)
        except Exception:
            pass
    return []


@app.route("/api/agents", methods=["GET"])
@require_login
def api_agents():
    if not IS_REMOTE:
        return jsonify(_get_agents_with_models())
    agents = _get_agents_from_pending()
    pending = _load_pending_changes()
    for a in agents:
        for p in pending:
            if p.get("agent") == a.get("agentId") and p.get("status") == "pending":
                a["pending_model"] = p.get("new_primary")
    return jsonify(agents)


@app.route("/api/agents/<agent_id>/model", methods=["PUT"])
@require_login
def api_set_agent_model(agent_id):
    data = request.get_json()
    if not data or "primary" not in data:
        return jsonify({"error": "primary field required"}), 400

    new_primary = data["primary"].strip()
    new_fallbacks = data.get("fallbacks")

    known_models = {m["model_id"] for m in load_models()}
    bare_id = new_primary.split("/", 1)[-1] if "/" in new_primary else new_primary
    if new_primary not in known_models and bare_id not in known_models:
        candidates = [m for m in known_models if bare_id in m]
        if not candidates:
            return jsonify({"error": f"model '{new_primary}' not in catalog", "known": sorted(known_models)}), 400

    if IS_REMOTE:
        agents = _get_agents_from_pending()
        old_primary = "unknown"
        for a in agents:
            if a.get("agentId") == agent_id:
                old_primary = a.get("primary", "unknown")
                break
        pending = _load_pending_changes()
        change = {
            "id": secrets.token_hex(8),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent_id,
            "old_primary": old_primary,
            "new_primary": new_primary,
            "new_fallbacks": new_fallbacks,
            "status": "pending",
            "changed_by": "ai-model-repo-ui",
        }
        pending.append(change)
        _save_pending_changes(pending)
        log_file = REPO_DIR / "model_changes.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps({
                "timestamp": change["timestamp"],
                "agent": agent_id,
                "old_primary": old_primary,
                "new_primary": new_primary,
                "changed_by": "ai-model-repo-ui",
            }) + "\n")
        _trigger_sync_webhook()
        return jsonify({
            "ok": True,
            "mode": "queued",
            "agent": agent_id,
            "old_primary": old_primary,
            "new_primary": new_primary,
            "change_id": change["id"],
            "message": "Change queued. Sync triggered via webhook.",
        })

    cfg = _load_openclaw_config()
    agents = cfg.get("agents", {}).get("list", [])
    target = None
    for a in agents:
        if a.get("id", a.get("agentId", "")) == agent_id:
            target = a
            break
    if not target:
        return jsonify({"error": f"agent '{agent_id}' not found"}), 404

    old_model = target.get("model", {})
    old_primary = old_model.get("primary", "unknown") if isinstance(old_model, dict) else str(old_model)

    if isinstance(old_model, dict):
        target["model"]["primary"] = new_primary
        if new_fallbacks is not None:
            target["model"]["fallbacks"] = new_fallbacks
    else:
        target["model"] = {"primary": new_primary, "fallbacks": new_fallbacks or []}

    _save_openclaw_config(cfg)

    change_log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent_id,
        "old_primary": old_primary,
        "new_primary": new_primary,
        "changed_by": "ai-model-repo-ui",
    }
    log_file = REPO_DIR / "model_changes.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(change_log) + "\n")

    needs_restart = data.get("restart_gateway", False)
    restarted = False
    if needs_restart:
        try:
            subprocess.run(["systemctl", "--user", "restart", "openclaw-gateway"],
                           capture_output=True, text=True, timeout=10)
            restarted = True
        except Exception:
            pass

    return jsonify({
        "ok": True,
        "mode": "applied",
        "agent": agent_id,
        "old_primary": old_primary,
        "new_primary": new_primary,
        "restarted": restarted,
    })


@app.route("/api/pending-changes", methods=["GET"])
def api_pending_changes():
    if not _check_api_token():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(_load_pending_changes())


@app.route("/api/pending-changes/<change_id>/ack", methods=["POST"])
def api_ack_change(change_id):
    if not _check_api_token():
        return jsonify({"error": "unauthorized"}), 401
    pending = _load_pending_changes()
    found = False
    for p in pending:
        if p.get("id") == change_id:
            p["status"] = "applied"
            p["applied_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break
    if not found:
        return jsonify({"error": "change not found"}), 404
    _save_pending_changes(pending)
    return jsonify({"ok": True})


@app.route("/api/test-webhook", methods=["POST"])
def api_test_webhook():
    if not _check_api_token():
        return jsonify({"error": "unauthorized"}), 401
    import urllib.request
    import ssl
    url = OPENCLAW_WEBHOOK_URL
    token = OPENCLAW_WEBHOOK_TOKEN
    if not url or not token:
        return jsonify({"error": "OPENCLAW_WEBHOOK_URL or TOKEN not set", "url": url, "token_set": bool(token)}), 400
    body = json.dumps({"text": "webhook diagnostic test", "mode": "next-heartbeat"}).encode()
    req = urllib.request.Request(
        f"{url}/hooks/wake",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        ctx = ssl.create_default_context()
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        return jsonify({"ok": True, "status": resp.status, "body": resp.read().decode()})
    except Exception as e:
        try:
            ctx = ssl._create_unverified_context()
            resp = urllib.request.urlopen(req, timeout=10, context=ctx)
            return jsonify({"ok": True, "ssl": "unverified", "status": resp.status, "body": resp.read().decode()})
        except Exception as e2:
            return jsonify({"error": str(e), "retry_error": str(e2)}), 502


@app.route("/api/agents/<agent_id>/model/history", methods=["GET"])
@require_login
def api_agent_model_history(agent_id):
    log_file = REPO_DIR / "model_changes.jsonl"
    if not log_file.exists():
        return jsonify([])
    entries = []
    for line in log_file.read_text().strip().split("\n"):
        if not line:
            continue
        entry = json.loads(line)
        if entry.get("agent") == agent_id or agent_id == "all":
            entries.append(entry)
    return jsonify(entries[-50:])


@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "AI Model Repo",
        "short_name": "ModelRepo",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f1117",
        "theme_color": "#0f1117",
        "description": "AI Model Knowledge Repository — manage models, agents, and benchmarks",
        "icons": [
            {"src": "/icon-192.svg", "sizes": "192x192", "type": "image/svg+xml"},
            {"src": "/icon-512.svg", "sizes": "512x512", "type": "image/svg+xml"},
        ],
    })


@app.route("/icon-192.svg")
@app.route("/icon-512.svg")
def app_icon():
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="96" fill="#0f1117"/>
<text x="256" y="320" text-anchor="middle" font-size="280" font-family="sans-serif">⚡</text>
</svg>'''
    return svg, 200, {"Content-Type": "image/svg+xml"}


@app.route("/sw.js")
def service_worker():
    sw = """self.addEventListener('fetch', function(e) {});"""
    return sw, 200, {"Content-Type": "application/javascript"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
