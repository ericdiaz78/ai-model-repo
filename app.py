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
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

REPO_DIR = Path(__file__).parent
MODELS_FILE = REPO_DIR / "models.json"
GENERATED_FILE = REPO_DIR / "models.generated.json"
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


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Model Knowledge Repository</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; }
  header { background: #1a1d27; border-bottom: 1px solid #2d3148; padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 18px; font-weight: 600; color: #fff; }
  header .badge { background: #2563eb; color: #fff; font-size: 11px; padding: 2px 8px; border-radius: 999px; }
  .tabs { display: flex; gap: 0; background: #1a1d27; border-bottom: 1px solid #2d3148; padding: 0 24px; }
  .tab { padding: 12px 20px; cursor: pointer; font-size: 14px; color: #94a3b8; border-bottom: 2px solid transparent; transition: all 0.15s; }
  .tab.active { color: #fff; border-bottom-color: #2563eb; }
  .tab:hover:not(.active) { color: #cbd5e1; }
  .panel { display: none; padding: 24px; max-width: 1200px; margin: 0 auto; }
  .panel.active { display: block; }
  .search-row { display: flex; gap: 12px; margin-bottom: 20px; }
  input[type=text], textarea { background: #1a1d27; border: 1px solid #2d3148; border-radius: 8px; color: #e2e8f0; padding: 10px 14px; font-size: 14px; width: 100%; outline: none; }
  input[type=text]:focus, textarea:focus { border-color: #2563eb; }
  textarea { min-height: 80px; resize: vertical; }
  button { background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 10px 20px; font-size: 14px; cursor: pointer; font-weight: 500; transition: background 0.15s; white-space: nowrap; }
  button:hover { background: #1d4ed8; }
  button.secondary { background: #374151; }
  button.secondary:hover { background: #4b5563; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
  .card { background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px; padding: 18px; transition: border-color 0.15s; }
  .card:hover { border-color: #3b4270; }
  .card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
  .card-name { font-weight: 600; font-size: 15px; color: #fff; }
  .card-provider { font-size: 12px; color: #64748b; margin-top: 2px; }
  .cost-badge { background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 4px 10px; font-size: 12px; color: #94a3b8; text-align: right; }
  .cost-badge .cost-val { font-weight: 600; color: #34d399; font-size: 14px; display: block; }
  .tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
  .tag { background: #1e293b; border: 1px solid #334155; color: #93c5fd; font-size: 11px; padding: 2px 8px; border-radius: 999px; }
  .card-meta { font-size: 12px; color: #64748b; margin-top: 10px; line-height: 1.5; }
  .card-notes { font-size: 13px; color: #94a3b8; margin-top: 8px; line-height: 1.5; border-top: 1px solid #1e293b; padding-top: 8px; }
  .result-box { background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px; padding: 20px; margin-top: 16px; }
  .result-box h3 { font-size: 14px; color: #94a3b8; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.05em; }
  .result-item { padding: 12px 0; border-bottom: 1px solid #1e293b; }
  .result-item:last-child { border-bottom: none; }
  .result-rank { display: inline-block; background: #2563eb; color: #fff; font-size: 11px; font-weight: 700; width: 22px; height: 22px; line-height: 22px; text-align: center; border-radius: 50%; margin-right: 10px; }
  .result-name { font-weight: 600; color: #fff; }
  .result-reason { font-size: 13px; color: #94a3b8; margin-top: 4px; margin-left: 32px; }
  .compare-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
  .compare-col { background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px; padding: 20px; }
  .compare-col h3 { font-size: 15px; font-weight: 600; color: #fff; margin-bottom: 14px; }
  .compare-field { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #1e293b; font-size: 13px; }
  .compare-field:last-child { border-bottom: none; }
  .compare-label { color: #64748b; }
  .compare-value { color: #e2e8f0; font-weight: 500; text-align: right; max-width: 60%; }
  .winner { color: #34d399 !important; }
  .status { padding: 12px 16px; border-radius: 8px; font-size: 14px; margin-top: 12px; }
  .status.ok { background: #052e16; border: 1px solid #166534; color: #4ade80; }
  .status.err { background: #2d0a0a; border: 1px solid #7f1d1d; color: #f87171; }
  .context-bar { height: 4px; background: #1e293b; border-radius: 2px; margin-top: 8px; overflow: hidden; }
  .context-fill { height: 100%; background: #2563eb; border-radius: 2px; }
  select { background: #1a1d27; border: 1px solid #2d3148; border-radius: 8px; color: #e2e8f0; padding: 10px 14px; font-size: 14px; outline: none; }
  select:focus { border-color: #2563eb; }
  .empty { text-align: center; color: #475569; padding: 40px; font-size: 14px; }
  .stat-row { display: flex; gap: 16px; margin-bottom: 24px; }
  .stat { background: #1a1d27; border: 1px solid #2d3148; border-radius: 10px; padding: 16px 20px; flex: 1; }
  .stat-val { font-size: 28px; font-weight: 700; color: #fff; }
  .stat-label { font-size: 12px; color: #64748b; margin-top: 4px; }
  .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid #334155; border-top-color: #2563eb; border-radius: 50%; animation: spin 0.6s linear infinite; vertical-align: middle; margin-right: 8px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading { color: #64748b; font-size: 14px; padding: 20px 0; }
</style>
</head>
<body>
<header>
  <h1>⚡ AI Model Knowledge Repository</h1>
  <span class="badge" id="model-count">loading...</span>
</header>
<div class="tabs">
  <div class="tab active" onclick="showTab('catalog')">Catalog</div>
  <div class="tab" onclick="showTab('query')">Query</div>
  <div class="tab" onclick="showTab('compare')">Compare</div>
  <div class="tab" onclick="showTab('ingest')">Ingest</div>
</div>

<!-- CATALOG -->
<div class="panel active" id="panel-catalog">
  <div class="stat-row" id="stat-row"></div>
  <div class="search-row">
    <input type="text" id="catalog-search" placeholder="Filter by name, provider, tag..." oninput="filterCatalog()">
    <select id="catalog-filter" onchange="filterCatalog()">
      <option value="">All providers</option>
    </select>
  </div>
  <div class="grid" id="catalog-grid"><div class="loading"><span class="spinner"></span>Loading models...</div></div>
</div>

<!-- QUERY -->
<div class="panel" id="panel-query">
  <div class="search-row">
    <input type="text" id="query-input" placeholder="e.g. best model for coding with low cost" onkeydown="if(event.key==='Enter') runQuery()">
    <button onclick="runQuery()">Find Best Match</button>
  </div>
  <div id="query-results"></div>
</div>

<!-- COMPARE -->
<div class="panel" id="panel-compare">
  <div class="search-row">
    <select id="compare-a" style="flex:1"><option value="">Select model A...</option></select>
    <select id="compare-b" style="flex:1"><option value="">Select model B...</option></select>
    <select id="compare-task" style="flex:1">
      <option value="general">General</option>
      <option value="coding">Coding</option>
      <option value="reasoning">Reasoning</option>
      <option value="summarization">Summarization</option>
      <option value="agentic">Agentic</option>
    </select>
    <button onclick="runCompare()">Compare</button>
  </div>
  <div id="compare-results"></div>
</div>

<!-- INGEST -->
<div class="panel" id="panel-ingest">
  <p style="color:#94a3b8;font-size:14px;margin-bottom:16px;">Paste a model announcement, release note, or free text. The system will extract and save a structured model record.</p>
  <textarea id="ingest-text" placeholder="e.g. OpenAI released GPT-4.1 mini with 128k context, priced at $0.4 input $1.6 output per million tokens. Strong at code and cheap for automation."></textarea>
  <div style="margin-top:12px;display:flex;gap:12px;align-items:center">
    <input type="text" id="ingest-out" placeholder="Output file (default: models.generated.json)" style="flex:1">
    <button onclick="runIngest()">Ingest Model</button>
  </div>
  <div id="ingest-results"></div>
</div>

<script>
let allModels = [];

async function loadModels() {
  const res = await fetch('/api/models');
  allModels = await res.json();
  document.getElementById('model-count').textContent = allModels.length + ' models';
  renderStats();
  renderCatalog(allModels);
  populateSelects();
}

function renderStats() {
  const providers = [...new Set(allModels.map(m => m.provider))];
  const cheapest = allModels.reduce((a, b) => {
    const ca = a.pricing?.input_per_mtok || 999;
    const cb = b.pricing?.input_per_mtok || 999;
    return ca < cb ? a : b;
  }, allModels[0]);
  document.getElementById('stat-row').innerHTML = `
    <div class="stat"><div class="stat-val">${allModels.length}</div><div class="stat-label">Total models</div></div>
    <div class="stat"><div class="stat-val">${providers.length}</div><div class="stat-label">Providers</div></div>
    <div class="stat"><div class="stat-val">$${cheapest?.pricing?.input_per_mtok ?? '?'}</div><div class="stat-label">Cheapest input (per MTok) — ${cheapest?.model_name ?? ''}</div></div>
  `;
  const providerFilter = document.getElementById('catalog-filter');
  providers.sort().forEach(p => {
    const opt = document.createElement('option');
    opt.value = p; opt.textContent = p;
    providerFilter.appendChild(opt);
  });
}

function renderCatalog(models) {
  const grid = document.getElementById('catalog-grid');
  if (!models.length) { grid.innerHTML = '<div class="empty">No models match your filter.</div>'; return; }
  grid.innerHTML = models.map(m => {
    const tags = (m.routing_tags || []).map(t => `<span class="tag">${t}</span>`).join('');
    const inp = m.pricing?.input_per_mtok ?? '?';
    const out = m.pricing?.output_per_mtok ?? '?';
    const ctx = m.context_window ? (m.context_window >= 1000000 ? (m.context_window/1000000).toFixed(0)+'M' : (m.context_window/1000).toFixed(0)+'k') : '?';
    const ctxPct = Math.min(100, (m.context_window || 0) / 10000);
    return `<div class="card">
      <div class="card-header">
        <div><div class="card-name">${m.model_name}</div><div class="card-provider">${m.provider} · ${m.version || ''}</div></div>
        <div class="cost-badge"><span class="cost-val">$${inp}</span>per MTok in</div>
      </div>
      <div class="tags">${tags}</div>
      <div class="context-bar"><div class="context-fill" style="width:${ctxPct}%"></div></div>
      <div class="card-meta">Context: ${ctx} · Output: $${out}/MTok</div>
      <div class="card-notes">${m.performance_notes || ''}</div>
    </div>`;
  }).join('');
}

function filterCatalog() {
  const q = document.getElementById('catalog-search').value.toLowerCase();
  const prov = document.getElementById('catalog-filter').value;
  const filtered = allModels.filter(m => {
    const text = [m.model_name, m.provider, ...(m.routing_tags||[]), ...(m.strengths||[]), m.performance_notes||''].join(' ').toLowerCase();
    return (!q || text.includes(q)) && (!prov || m.provider === prov);
  });
  renderCatalog(filtered);
}

function populateSelects() {
  ['compare-a','compare-b'].forEach(id => {
    const sel = document.getElementById(id);
    allModels.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m.model_id; opt.textContent = m.model_name;
      sel.appendChild(opt);
    });
  });
}

async function runQuery() {
  const q = document.getElementById('query-input').value.trim();
  if (!q) return;
  document.getElementById('query-results').innerHTML = '<div class="loading"><span class="spinner"></span>Finding best match...</div>';
  const res = await fetch('/api/query', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({query: q}) });
  const data = await res.json();
  if (data.error) {
    document.getElementById('query-results').innerHTML = `<div class="status err">${data.error}</div>`;
    return;
  }
  const items = data.results || [];
  document.getElementById('query-results').innerHTML = `
    <div class="result-box">
      <h3>Results for "${q}"</h3>
      ${items.length ? items.map((r, i) => `
        <div class="result-item">
          <span class="result-rank">${i+1}</span><span class="result-name">${r.model_name}</span>
          <div class="result-reason">${r.reason || r.routing_tags?.join(', ') || ''}</div>
        </div>`).join('') : '<div class="empty">No results found.</div>'}
    </div>`;
}

async function runCompare() {
  const a = document.getElementById('compare-a').value;
  const b = document.getElementById('compare-b').value;
  const task = document.getElementById('compare-task').value;
  if (!a || !b) return;
  document.getElementById('compare-results').innerHTML = '<div class="loading"><span class="spinner"></span>Comparing...</div>';
  const res = await fetch('/api/compare', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({model_a: a, model_b: b, task}) });
  const data = await res.json();
  if (data.error) { document.getElementById('compare-results').innerHTML = `<div class="status err">${data.error}</div>`; return; }
  const ma = data.model_a, mb = data.model_b;
  const rec = data.recommendation;
  const cheaperA = (ma.pricing?.input_per_mtok||999) <= (mb.pricing?.input_per_mtok||999);
  const ctxA = ma.context_window >= mb.context_window;
  document.getElementById('compare-results').innerHTML = `
    <div class="compare-row">
      <div class="compare-col">
        <h3>${ma.model_name}</h3>
        <div class="compare-field"><span class="compare-label">Provider</span><span class="compare-value">${ma.provider}</span></div>
        <div class="compare-field"><span class="compare-label">Input cost</span><span class="compare-value ${cheaperA?'winner':''}">$${ma.pricing?.input_per_mtok??'?'}/MTok</span></div>
        <div class="compare-field"><span class="compare-label">Context</span><span class="compare-value ${ctxA?'winner':''}">${ma.context_window?(ma.context_window>=1e6?(ma.context_window/1e6).toFixed(0)+'M':(ma.context_window/1000).toFixed(0)+'k'):'?'}</span></div>
        <div class="compare-field"><span class="compare-label">Strengths</span><span class="compare-value">${(ma.strengths||[]).slice(0,3).join(', ')}</span></div>
      </div>
      <div class="compare-col">
        <h3>${mb.model_name}</h3>
        <div class="compare-field"><span class="compare-label">Provider</span><span class="compare-value">${mb.provider}</span></div>
        <div class="compare-field"><span class="compare-label">Input cost</span><span class="compare-value ${!cheaperA?'winner':''}">$${mb.pricing?.input_per_mtok??'?'}/MTok</span></div>
        <div class="compare-field"><span class="compare-label">Context</span><span class="compare-value ${!ctxA?'winner':''}">${mb.context_window?(mb.context_window>=1e6?(mb.context_window/1e6).toFixed(0)+'M':(mb.context_window/1000).toFixed(0)+'k'):'?'}</span></div>
        <div class="compare-field"><span class="compare-label">Strengths</span><span class="compare-value">${(mb.strengths||[]).slice(0,3).join(', ')}</span></div>
      </div>
    </div>
    ${rec ? `<div class="status ok" style="margin-top:16px">🏆 ${rec}</div>` : ''}`;
}

async function runIngest() {
  const text = document.getElementById('ingest-text').value.trim();
  if (!text) return;
  const out = document.getElementById('ingest-out').value.trim() || 'models.generated.json';
  document.getElementById('ingest-results').innerHTML = '<div class="loading"><span class="spinner"></span>Ingesting...</div>';
  const res = await fetch('/api/ingest', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({text, out}) });
  const data = await res.json();
  document.getElementById('ingest-results').innerHTML = data.ok
    ? `<div class="status ok">✓ ${data.message}</div>`
    : `<div class="status err">✗ ${data.error}</div>`;
  if (data.ok) loadModels();
}

function showTab(name) {
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', ['catalog','query','compare','ingest'][i]===name));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-'+name).classList.add('active');
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


@app.route("/api/query", methods=["POST"])
def api_query():
    data = request.get_json()
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "No query provided"}), 400
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "query.py"), query],
            capture_output=True, text=True, timeout=30, cwd=str(REPO_DIR)
        )
        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        results = []
        models = load_models()
        model_map = {m["model_id"]: m for m in models}
        for line in lines[:5]:
            # query.py output: "Model Name (model_id) — reason. Tags: [...]"
            for m in models:
                if m["model_name"] in line or m["model_id"] in line:
                    results.append({**m, "reason": line})
                    break
            else:
                results.append({"model_name": line, "reason": line})
        if not results and lines:
            results = [{"model_name": l, "reason": l} for l in lines]
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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

    # Score by task tags
    task_tags = {
        "coding": ["coding", "code", "specialist"],
        "reasoning": ["reasoning", "analysis", "balanced"],
        "summarization": ["summarization", "fast-response"],
        "agentic": ["agentic", "tool-use", "muscle"],
        "general": ["balanced", "reasoning"],
    }.get(task, ["balanced"])

    def score(m):
        tags = m.get("routing_tags", [])
        cost = m.get("pricing", {}).get("input_per_mtok", 999)
        tag_score = sum(1 for t in task_tags if t in tags)
        cost_score = 1 / (cost + 0.01)
        return tag_score * 2 + cost_score * 0.1

    winner = ma if score(ma) >= score(mb) else mb
    rec = f"For {task} tasks, {winner['model_name']} is the better fit based on tags and cost efficiency."
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
        return jsonify({"ok": True, "message": result.stdout.strip() or f"Model ingested to {out}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
