#!/usr/bin/env python3
"""
AI Model Knowledge Repository — Web UI
Flask app for browsing, querying, comparing, and ingesting AI models.
Run: python3 app.py
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

REPO_DIR = Path(__file__).parent
MODELS_FILE = REPO_DIR / "models.json"
GENERATED_FILE = REPO_DIR / "models.generated.json"
FEEDBACK_FILE = REPO_DIR / "feedback.json"
CHANGELOG_FILE = REPO_DIR / "CHANGELOG.md"
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
.compare-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 14px; }
.compare-col { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px; }
.compare-col h3 { font-size: 14px; font-weight: 700; color: var(--text); margin-bottom: 14px; }
.cmp-row { display: flex; justify-content: space-between; padding: 7px 0;
  border-bottom: 1px solid var(--border); font-size: 12px; gap: 8px; }
.cmp-row:last-child { border-bottom: none; }
.cmp-label { color: var(--muted); flex-shrink: 0; }
.cmp-val { color: var(--text); font-weight: 500; text-align: right; }
.cmp-val.win { color: var(--green); }
.rec-box { margin-top: 14px; padding: 14px 18px; border-radius: 10px;
  background: #052e16; border: 1px solid #166534; color: #4ade80; font-size: 14px; }
[data-theme="light"] .rec-box { background: #f0fdf4; border-color: #86efac; color: #15803d; }

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
  <div class="tab" onclick="showTab('changelog')">Changelog</div>
  <div class="tab" onclick="showTab('feedback')">Feedback</div>
  <div class="tab" onclick="showTab('ingest')">Ingest</div>
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
    <label style="font-size:12px;color:var(--muted);display:flex;align-items:center;gap:5px;cursor:pointer;white-space:nowrap">
      <input type="checkbox" id="hide-review" onchange="filterCatalog()" style="width:auto">
      Hide unreviewed
    </label>
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
  <p style="font-size:13px;color:var(--muted);margin-bottom:14px">Select models from the Catalog (checkboxes) or choose manually below.</p>
  <div class="row" style="margin-bottom:14px;flex-wrap:wrap">
    <select id="compare-a" style="flex:1;min-width:180px"><option value="">Model A…</option></select>
    <select id="compare-b" style="flex:1;min-width:180px"><option value="">Model B…</option></select>
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
  populateCompareSelects();
}

// ── Donut SVG ──────────────────────────────────────────────────────────
function donut(pct, color='#2563eb', size=44) {
  const r = 15.9155, c = 2 * Math.PI * r;
  const dash = (pct / 100) * c;
  return `<svg width="${size}" height="${size}" viewBox="0 0 36 36">
    <circle cx="18" cy="18" r="${r}" fill="none" stroke="var(--border)" stroke-width="3.5"/>
    <circle cx="18" cy="18" r="${r}" fill="none" stroke="${color}" stroke-width="3.5"
      stroke-dasharray="${dash} ${c}" stroke-dashoffset="${c * 0.25}" transform="rotate(-90 18 18)"
      stroke-linecap="round"/>
  </svg>`;
}

// ── Stats ──────────────────────────────────────────────────────────────
function renderStats() {
  const providers = [...new Set(allModels.map(m => m.provider))];
  const curated = allModels.filter(m => !m._meta?.needs_review);
  const withPricing = allModels.filter(m => (m.pricing?.input_per_mtok || 0) > 0);
  const cheapest = withPricing.reduce((a, b) =>
    (a.pricing?.input_per_mtok || 999) < (b.pricing?.input_per_mtok || 999) ? a : b, withPricing[0]);
  const curatedPct = Math.round((curated.length / allModels.length) * 100);

  const effScores = curated.map(m => computeEff(m));
  const avgEff = effScores.length ? Math.round(effScores.reduce((a,b)=>a+b,0)/effScores.length) : 0;

  document.getElementById('stat-row').innerHTML = `
    <div class="stat-card">
      <div class="donut-wrap">${donut(Math.min(100, allModels.length/3.5), '#2563eb')}</div>
      <div class="stat-info">
        <div class="stat-val">${allModels.length}</div>
        <div class="stat-label">Total Models</div>
        <div class="stat-sub">${providers.length} providers</div>
      </div>
    </div>
    <div class="stat-card">
      <div class="donut-wrap">${donut(curatedPct, '#34d399')}</div>
      <div class="stat-info">
        <div class="stat-val">${curated.length}</div>
        <div class="stat-label">Curated</div>
        <div class="stat-sub">${curatedPct}% reviewed</div>
      </div>
    </div>
    <div class="stat-card">
      <div class="donut-wrap">${donut(avgEff, '#fbbf24')}</div>
      <div class="stat-info">
        <div class="stat-val">${avgEff}</div>
        <div class="stat-label">Avg Efficiency</div>
        <div class="stat-sub">curated models only</div>
      </div>
    </div>
    <div class="stat-card">
      <div class="donut-wrap">${donut(100, '#34d399')}</div>
      <div class="stat-info">
        <div class="stat-val">$${cheapest?.pricing?.input_per_mtok ?? '?'}</div>
        <div class="stat-label">Cheapest Input</div>
        <div class="stat-sub">${cheapest?.model_name?.split(' ').slice(0,2).join(' ') ?? ''}</div>
      </div>
    </div>`;

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
  const hideReview = document.getElementById('hide-review').checked;
  let list = allModels.filter(m => {
    if (hideReview && m._meta?.needs_review) return false;
    if (prov && m.provider !== prov) return false;
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
    return `<div class="card ${comparing}" id="card-${CSS.escape(m.model_id)}">
      <div style="position:absolute;top:10px;right:10px">
        <label class="compare-cb" title="Add to compare">
          <input type="checkbox" ${checked} onchange="toggleCompare('${m.model_id}', this.checked)"> Compare
        </label>
      </div>
      <div class="card-top" style="padding-right:70px">
        <div class="card-title">
          <div class="card-name">${m.model_name}</div>
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
  const [a, b] = ids;
  const selA = document.getElementById('compare-a');
  const selB = document.getElementById('compare-b');
  selA.value = a; selB.value = b;
  showTab('compare');
  runCompare();
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
function populateCompareSelects() {
  ['compare-a','compare-b'].forEach(id => {
    const sel = document.getElementById(id);
    const curatedFirst = [...allModels].sort((a,b) => (a._meta?.needs_review?1:0) - (b._meta?.needs_review?1:0));
    curatedFirst.forEach(m => {
      const o = document.createElement('option'); o.value = m.model_id;
      o.textContent = m.model_name + (m._meta?.needs_review ? ' ⚠' : '');
      sel.appendChild(o);
    });
  });
}

async function runCompare() {
  const a = document.getElementById('compare-a').value;
  const b = document.getElementById('compare-b').value;
  const task = document.getElementById('compare-task').value;
  if (!a || !b) return;
  const out = document.getElementById('compare-results');
  out.innerHTML = '<div class="loading"><span class="spinner"></span>Comparing…</div>';
  const res = await fetch('/api/compare', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({model_a: a, model_b: b, task})});
  const data = await res.json();
  if (data.error) { out.innerHTML = `<div class="status err">✗ ${data.error}</div>`; return; }
  const ma = data.model_a, mb = data.model_b;
  const cheaperA = (ma.pricing?.input_per_mtok||999) <= (mb.pricing?.input_per_mtok||999);
  const ctxA = (ma.context_window||0) >= (mb.context_window||0);
  const effA = computeEff(ma), effB = computeEff(mb);
  const effWinA = effA >= effB;

  function fmtCtx(n) { return n ? (n>=1e6?(n/1e6).toFixed(1)+'M':Math.round(n/1000)+'k') : '?'; }

  out.innerHTML = `<div class="compare-grid">
    <div class="compare-col">
      <h3>${ma.model_name}</h3>
      <div class="cmp-row"><span class="cmp-label">Provider</span><span class="cmp-val">${ma.provider}</span></div>
      <div class="cmp-row"><span class="cmp-label">Input cost</span><span class="cmp-val ${cheaperA?'win':''}">$${ma.pricing?.input_per_mtok??'?'}/MTok</span></div>
      <div class="cmp-row"><span class="cmp-label">Output cost</span><span class="cmp-val">$${ma.pricing?.output_per_mtok??'?'}/MTok</span></div>
      <div class="cmp-row"><span class="cmp-label">Context</span><span class="cmp-val ${ctxA?'win':''}">${fmtCtx(ma.context_window)}</span></div>
      <div class="cmp-row"><span class="cmp-label">Efficiency</span><span class="cmp-val ${effWinA?'win':''}">${effA}/100</span></div>
      <div class="cmp-row"><span class="cmp-label">Strengths</span><span class="cmp-val">${(ma.strengths||[]).slice(0,3).join(', ')||'—'}</span></div>
      <div class="cmp-row"><span class="cmp-label">Tags</span><span class="cmp-val">${(ma.routing_tags||[]).join(', ')||'—'}</span></div>
    </div>
    <div class="compare-col">
      <h3>${mb.model_name}</h3>
      <div class="cmp-row"><span class="cmp-label">Provider</span><span class="cmp-val">${mb.provider}</span></div>
      <div class="cmp-row"><span class="cmp-label">Input cost</span><span class="cmp-val ${!cheaperA?'win':''}">$${mb.pricing?.input_per_mtok??'?'}/MTok</span></div>
      <div class="cmp-row"><span class="cmp-label">Output cost</span><span class="cmp-val">$${mb.pricing?.output_per_mtok??'?'}/MTok</span></div>
      <div class="cmp-row"><span class="cmp-label">Context</span><span class="cmp-val ${!ctxA?'win':''}">${fmtCtx(mb.context_window)}</span></div>
      <div class="cmp-row"><span class="cmp-label">Efficiency</span><span class="cmp-val ${!effWinA?'win':''}">${effB}/100</span></div>
      <div class="cmp-row"><span class="cmp-label">Strengths</span><span class="cmp-val">${(mb.strengths||[]).slice(0,3).join(', ')||'—'}</span></div>
      <div class="cmp-row"><span class="cmp-label">Tags</span><span class="cmp-val">${(mb.routing_tags||[]).join(', ')||'—'}</span></div>
    </div>
  </div>
  ${data.recommendation ? `<div class="rec-box">🏆 ${data.recommendation}</div>` : ''}`;
}

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

// ── Tabs ───────────────────────────────────────────────────────────────
const TAB_NAMES = ['catalog','query','compare','changelog','feedback','ingest'];
function showTab(name) {
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', TAB_NAMES[i]===name));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-'+name).classList.add('active');
  if (name === 'changelog') loadChangelog();
  if (name === 'feedback') loadFeedback();
}

loadModels();
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/models")
def api_models():
    return jsonify(load_models())


@app.route("/api/changelog")
def api_changelog():
    if not CHANGELOG_FILE.exists():
        return jsonify({"content": "No changelog found."})
    return jsonify({"content": CHANGELOG_FILE.read_text()})


@app.route("/api/feedback", methods=["GET", "POST"])
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


@app.route("/api/sync", methods=["POST"])
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
