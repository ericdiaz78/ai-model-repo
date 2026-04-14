# Changelog

## [2026-04-14] — Validation + spend history sync hardening

### Fixed
- Restored `schema.json` provider enum coverage so `python3 scripts/update_schema.py validate` passes against the expanded OpenRouter dataset
- Normalized `code` / `coding` tag aliases in `scripts/evaluate.py` so low-cost code recommendations still filter correctly after large model ingests
- Updated evaluation tests to assert capability coverage instead of brittle exact-model IDs as the catalog evolves
- Ignored local sync cursor files (`.usage-sync-state.json`, `.direct-usage-state.json`) so runtime state stops polluting git status

### Added
- Tracked `spend_history.json` in-repo so the web UI trend endpoints have deployable history data instead of a local-only artifact

## [2026-04-13] — Auto-ingestion from OpenRouter

- New model ingested: `anthropic/claude-opus-4.6-fast` (anthropic) — $30.0/M in, $150.0/M out, ctx=1,000,000
- New model ingested: `google/gemma-4-26b-a4b-it` (google) — $0.12/M in, $0.4/M out, ctx=262,144
- New model ingested: `google/gemma-4-31b-it` (google) — $0.14/M in, $0.4/M out, ctx=262,144
- Updated `minimax/minimax-m2.7` — pricing.input_per_mtok: 0.1 → 0.3
- Updated `minimax/minimax-m2.7` — pricing.output_per_mtok: 0.5 → 1.2
- Updated `minimax/minimax-m2.7` — context_window: 1000000 → 196608
- New model ingested: `openai/gpt-5.4-nano` (openai) — $0.2/M in, $1.25/M out, ctx=400,000
- New model ingested: `openai/gpt-5.4-mini` (openai) — $0.75/M in, $4.5/M out, ctx=400,000
- New model ingested: `mistralai/mistral-small-2603` (mistral) — $0.15/M in, $0.6/M out, ctx=262,144
- New model ingested: `openai/gpt-5.4-pro` (openai) — $30.0/M in, $180.0/M out, ctx=1,050,000
- New model ingested: `openai/gpt-5.4` (openai) — $2.5/M in, $15.0/M out, ctx=1,050,000
- New model ingested: `openai/gpt-5.3-chat` (openai) — $1.75/M in, $14.0/M out, ctx=128,000
- New model ingested: `google/gemini-3.1-flash-lite-preview` (google) — $0.25/M in, $1.5/M out, ctx=1,048,576
- New model ingested: `google/gemini-3.1-flash-image-preview` (google) — $0.5/M in, $3.0/M out, ctx=65,536
- New model ingested: `google/gemini-3.1-pro-preview-customtools` (google) — $2.0/M in, $12.0/M out, ctx=1,048,576
- New model ingested: `openai/gpt-5.3-codex` (openai) — $1.75/M in, $14.0/M out, ctx=400,000
- New model ingested: `google/gemini-3.1-pro-preview` (google) — $2.0/M in, $12.0/M out, ctx=1,048,576
- Updated `anthropic/claude-sonnet-4-6` — context_window: 200000 → 1000000
- New model ingested: `minimax/minimax-m2.5` (minimax) — $0.118/M in, $0.99/M out, ctx=196,608
- New model ingested: `anthropic/claude-opus-4.6` (anthropic) — $5.0/M in, $25.0/M out, ctx=1,000,000
- New model ingested: `minimax/minimax-m2-her` (minimax) — $0.3/M in, $1.2/M out, ctx=65,536
- New model ingested: `openai/gpt-audio` (openai) — $2.5/M in, $10.0/M out, ctx=128,000
- New model ingested: `openai/gpt-audio-mini` (openai) — $0.6/M in, $2.4/M out, ctx=128,000
- New model ingested: `openai/gpt-5.2-codex` (openai) — $1.75/M in, $14.0/M out, ctx=400,000
- New model ingested: `minimax/minimax-m2.1` (minimax) — $0.29/M in, $0.95/M out, ctx=196,608
- New model ingested: `google/gemini-3-flash-preview` (google) — $0.5/M in, $3.0/M out, ctx=1,048,576
- New model ingested: `mistralai/mistral-small-creative` (mistral) — $0.1/M in, $0.3/M out, ctx=32,768
- New model ingested: `openai/gpt-5.2-chat` (openai) — $1.75/M in, $14.0/M out, ctx=128,000
- New model ingested: `openai/gpt-5.2-pro` (openai) — $21.0/M in, $168.0/M out, ctx=400,000
- New model ingested: `openai/gpt-5.2` (openai) — $1.75/M in, $14.0/M out, ctx=400,000
- New model ingested: `mistralai/devstral-2512` (mistral) — $0.4/M in, $2.0/M out, ctx=262,144
- New model ingested: `openai/gpt-5.1-codex-max` (openai) — $1.25/M in, $10.0/M out, ctx=400,000
- New model ingested: `mistralai/ministral-14b-2512` (mistral) — $0.2/M in, $0.2/M out, ctx=262,144
- New model ingested: `mistralai/ministral-8b-2512` (mistral) — $0.15/M in, $0.15/M out, ctx=262,144
- New model ingested: `mistralai/ministral-3b-2512` (mistral) — $0.1/M in, $0.1/M out, ctx=131,072
- New model ingested: `mistralai/mistral-large-2512` (mistral) — $0.5/M in, $1.5/M out, ctx=262,144
- New model ingested: `deepseek/deepseek-v3.2-speciale` (deepseek) — $0.4/M in, $1.2/M out, ctx=163,840
- New model ingested: `deepseek/deepseek-v3.2` (deepseek) — $0.26/M in, $0.38/M out, ctx=163,840
- New model ingested: `anthropic/claude-opus-4.5` (anthropic) — $5.0/M in, $25.0/M out, ctx=200,000
- New model ingested: `google/gemini-3-pro-image-preview` (google) — $2.0/M in, $12.0/M out, ctx=65,536
- New model ingested: `openai/gpt-5.1` (openai) — $1.25/M in, $10.0/M out, ctx=400,000
- New model ingested: `openai/gpt-5.1-chat` (openai) — $1.25/M in, $10.0/M out, ctx=128,000
- New model ingested: `openai/gpt-5.1-codex` (openai) — $1.25/M in, $10.0/M out, ctx=400,000
- New model ingested: `openai/gpt-5.1-codex-mini` (openai) — $0.25/M in, $2.0/M out, ctx=400,000
- New model ingested: `mistralai/voxtral-small-24b-2507` (mistral) — $0.1/M in, $0.3/M out, ctx=32,000
- New model ingested: `openai/gpt-oss-safeguard-20b` (openai) — $0.075/M in, $0.3/M out, ctx=131,072
- New model ingested: `minimax/minimax-m2` (minimax) — $0.255/M in, $1.0/M out, ctx=196,608
- New model ingested: `openai/gpt-5-image-mini` (openai) — $2.5/M in, $2.0/M out, ctx=400,000
- Updated `anthropic/claude-haiku-4-5` — pricing.input_per_mtok: 0.8 → 1.0
- Updated `anthropic/claude-haiku-4-5` — pricing.output_per_mtok: 4.0 → 5.0
- New model ingested: `openai/gpt-5-image` (openai) — $10.0/M in, $10.0/M out, ctx=400,000
- New model ingested: `openai/o3-deep-research` (openai) — $10.0/M in, $40.0/M out, ctx=200,000
- New model ingested: `openai/o4-mini-deep-research` (openai) — $2.0/M in, $8.0/M out, ctx=200,000
- New model ingested: `google/gemini-2.5-flash-image` (google) — $0.3/M in, $2.5/M out, ctx=32,768
- New model ingested: `openai/gpt-5-pro` (openai) — $15.0/M in, $120.0/M out, ctx=400,000
- New model ingested: `anthropic/claude-sonnet-4.5` (anthropic) — $3.0/M in, $15.0/M out, ctx=1,000,000
- New model ingested: `deepseek/deepseek-v3.2-exp` (deepseek) — $0.27/M in, $0.41/M out, ctx=163,840
- New model ingested: `google/gemini-2.5-flash-lite-preview-09-2025` (google) — $0.1/M in, $0.4/M out, ctx=1,048,576
- New model ingested: `openai/gpt-5-codex` (openai) — $1.25/M in, $10.0/M out, ctx=400,000
- New model ingested: `deepseek/deepseek-v3.1-terminus` (deepseek) — $0.21/M in, $0.79/M out, ctx=163,840
- New model ingested: `deepseek/deepseek-chat-v3.1` (deepseek) — $0.15/M in, $0.75/M out, ctx=32,768
- New model ingested: `openai/gpt-4o-audio-preview` (openai) — $2.5/M in, $10.0/M out, ctx=128,000
- New model ingested: `mistralai/mistral-medium-3.1` (mistral) — $0.4/M in, $2.0/M out, ctx=131,072
- New model ingested: `openai/gpt-5-chat` (openai) — $1.25/M in, $10.0/M out, ctx=128,000
- New model ingested: `openai/gpt-5` (openai) — $1.25/M in, $10.0/M out, ctx=400,000
- New model ingested: `openai/gpt-5-mini` (openai) — $0.25/M in, $2.0/M out, ctx=400,000
- New model ingested: `openai/gpt-5-nano` (openai) — $0.05/M in, $0.4/M out, ctx=400,000
- New model ingested: `openai/gpt-oss-120b` (openai) — $0.039/M in, $0.19/M out, ctx=131,072
- New model ingested: `openai/gpt-oss-20b` (openai) — $0.03/M in, $0.14/M out, ctx=131,072
- New model ingested: `anthropic/claude-opus-4.1` (anthropic) — $15.0/M in, $75.0/M out, ctx=200,000
- New model ingested: `mistralai/codestral-2508` (mistral) — $0.3/M in, $0.9/M out, ctx=256,000
- Updated `google/gemini-2.5-flash-lite` — context_window: 64000 → 1048576
- New model ingested: `mistralai/devstral-medium` (mistral) — $0.4/M in, $2.0/M out, ctx=131,072
- New model ingested: `mistralai/devstral-small` (mistral) — $0.1/M in, $0.3/M out, ctx=131,072
- New model ingested: `mistralai/mistral-small-3.2-24b-instruct` (mistral) — $0.075/M in, $0.2/M out, ctx=128,000
- New model ingested: `minimax/minimax-m1` (minimax) — $0.4/M in, $2.2/M out, ctx=1,000,000
- Updated `google/gemini-2.5-flash` — pricing.input_per_mtok: 0.15 → 0.3
- Updated `google/gemini-2.5-flash` — pricing.output_per_mtok: 0.6 → 2.5
- Updated `google/gemini-2.5-flash` — context_window: 1000000 → 1048576
- New model ingested: `google/gemini-2.5-pro` (google) — $1.25/M in, $10.0/M out, ctx=1,048,576
- New model ingested: `openai/o3-pro` (openai) — $20.0/M in, $80.0/M out, ctx=200,000
- New model ingested: `google/gemini-2.5-pro-preview` (google) — $1.25/M in, $10.0/M out, ctx=1,048,576
- New model ingested: `deepseek/deepseek-r1-0528` (deepseek) — $0.5/M in, $2.15/M out, ctx=163,840
- New model ingested: `anthropic/claude-opus-4` (anthropic) — $15.0/M in, $75.0/M out, ctx=200,000
- New model ingested: `anthropic/claude-sonnet-4` (anthropic) — $3.0/M in, $15.0/M out, ctx=1,000,000
- New model ingested: `google/gemma-3n-e4b-it` (google) — $0.02/M in, $0.04/M out, ctx=32,768
- New model ingested: `mistralai/mistral-medium-3` (mistral) — $0.4/M in, $2.0/M out, ctx=131,072
- New model ingested: `google/gemini-2.5-pro-preview-05-06` (google) — $1.25/M in, $10.0/M out, ctx=1,048,576
- New model ingested: `openai/o4-mini-high` (openai) — $1.1/M in, $4.4/M out, ctx=200,000
- New model ingested: `openai/o3` (openai) — $2.0/M in, $8.0/M out, ctx=200,000
- New model ingested: `openai/o4-mini` (openai) — $1.1/M in, $4.4/M out, ctx=200,000
- New model ingested: `openai/gpt-4.1` (openai) — $2.0/M in, $8.0/M out, ctx=1,047,576
- New model ingested: `openai/gpt-4.1-mini` (openai) — $0.4/M in, $1.6/M out, ctx=1,047,576
- New model ingested: `openai/gpt-4.1-nano` (openai) — $0.1/M in, $0.4/M out, ctx=1,047,576
- New model ingested: `deepseek/deepseek-chat-v3-0324` (deepseek) — $0.2/M in, $0.77/M out, ctx=163,840
- New model ingested: `openai/o1-pro` (openai) — $150.0/M in, $600.0/M out, ctx=200,000
- New model ingested: `mistralai/mistral-small-3.1-24b-instruct` (mistral) — $0.35/M in, $0.56/M out, ctx=128,000
- New model ingested: `google/gemma-3-4b-it` (google) — $0.04/M in, $0.08/M out, ctx=131,072
- New model ingested: `google/gemma-3-12b-it` (google) — $0.04/M in, $0.13/M out, ctx=131,072
- New model ingested: `openai/gpt-4o-mini-search-preview` (openai) — $0.15/M in, $0.6/M out, ctx=128,000
- New model ingested: `openai/gpt-4o-search-preview` (openai) — $2.5/M in, $10.0/M out, ctx=128,000
- New model ingested: `google/gemma-3-27b-it` (google) — $0.08/M in, $0.16/M out, ctx=131,072
- New model ingested: `google/gemini-2.0-flash-lite-001` (google) — $0.075/M in, $0.3/M out, ctx=1,048,576
- New model ingested: `anthropic/claude-3.7-sonnet` (anthropic) — $3.0/M in, $15.0/M out, ctx=200,000
- New model ingested: `anthropic/claude-3.7-sonnet:thinking` (anthropic) — $3.0/M in, $15.0/M out, ctx=200,000
- New model ingested: `mistralai/mistral-saba` (mistral) — $0.2/M in, $0.6/M out, ctx=32,768
- New model ingested: `openai/o3-mini-high` (openai) — $1.1/M in, $4.4/M out, ctx=200,000
- New model ingested: `google/gemini-2.0-flash-001` (google) — $0.1/M in, $0.4/M out, ctx=1,048,576
- New model ingested: `openai/o3-mini` (openai) — $1.1/M in, $4.4/M out, ctx=200,000
- New model ingested: `mistralai/mistral-small-24b-instruct-2501` (mistral) — $0.05/M in, $0.08/M out, ctx=32,768
- New model ingested: `deepseek/deepseek-r1-distill-qwen-32b` (deepseek) — $0.29/M in, $0.29/M out, ctx=32,768
- New model ingested: `deepseek/deepseek-r1-distill-llama-70b` (deepseek) — $0.7/M in, $0.8/M out, ctx=131,072
- New model ingested: `deepseek/deepseek-r1` (deepseek) — $0.7/M in, $2.5/M out, ctx=64,000
- New model ingested: `minimax/minimax-01` (minimax) — $0.2/M in, $1.1/M out, ctx=1,000,192
- Updated `deepseek/deepseek-chat` — pricing.input_per_mtok: 0.14 → 0.32
- Updated `deepseek/deepseek-chat` — pricing.output_per_mtok: 0.28 → 0.89
- Updated `deepseek/deepseek-chat` — context_window: 128000 → 163840
- New model ingested: `openai/o1` (openai) — $15.0/M in, $60.0/M out, ctx=200,000
- New model ingested: `openai/gpt-4o-2024-11-20` (openai) — $2.5/M in, $10.0/M out, ctx=128,000
- New model ingested: `mistralai/mistral-large-2411` (mistral) — $2.0/M in, $6.0/M out, ctx=131,072
- New model ingested: `mistralai/mistral-large-2407` (mistral) — $2.0/M in, $6.0/M out, ctx=131,072
- New model ingested: `mistralai/pixtral-large-2411` (mistral) — $2.0/M in, $6.0/M out, ctx=131,072
- New model ingested: `anthropic/claude-3.5-haiku` (anthropic) — $0.8/M in, $4.0/M out, ctx=200,000
- New model ingested: `openai/gpt-4o-2024-08-06` (openai) — $2.5/M in, $10.0/M out, ctx=128,000
- New model ingested: `mistralai/mistral-nemo` (mistral) — $0.02/M in, $0.04/M out, ctx=131,072
- New model ingested: `openai/gpt-4o-mini-2024-07-18` (openai) — $0.15/M in, $0.6/M out, ctx=128,000
- New model ingested: `openai/gpt-4o-mini` (openai) — $0.15/M in, $0.6/M out, ctx=128,000
- New model ingested: `google/gemma-2-27b-it` (google) — $0.65/M in, $0.65/M out, ctx=8,192
- New model ingested: `google/gemma-2-9b-it` (google) — $0.03/M in, $0.09/M out, ctx=8,192
- New model ingested: `openai/gpt-4o-2024-05-13` (openai) — $5.0/M in, $15.0/M out, ctx=128,000
- New model ingested: `openai/gpt-4o` (openai) — $2.5/M in, $10.0/M out, ctx=128,000
- New model ingested: `openai/gpt-4o:extended` (openai) — $6.0/M in, $18.0/M out, ctx=128,000
- New model ingested: `mistralai/mixtral-8x22b-instruct` (mistral) — $2.0/M in, $6.0/M out, ctx=65,536
- New model ingested: `openai/gpt-4-turbo` (openai) — $10.0/M in, $30.0/M out, ctx=128,000
- New model ingested: `anthropic/claude-3-haiku` (anthropic) — $0.25/M in, $1.25/M out, ctx=200,000
- New model ingested: `mistralai/mistral-large` (mistral) — $2.0/M in, $6.0/M out, ctx=128,000
- New model ingested: `openai/gpt-4-turbo-preview` (openai) — $10.0/M in, $30.0/M out, ctx=128,000
- New model ingested: `openai/gpt-3.5-turbo-0613` (openai) — $1.0/M in, $2.0/M out, ctx=4,095
- New model ingested: `mistralai/mixtral-8x7b-instruct` (mistral) — $0.54/M in, $0.54/M out, ctx=32,768
- New model ingested: `openai/gpt-4-1106-preview` (openai) — $10.0/M in, $30.0/M out, ctx=128,000
- New model ingested: `openai/gpt-3.5-turbo-instruct` (openai) — $1.5/M in, $2.0/M out, ctx=4,095
- New model ingested: `mistralai/mistral-7b-instruct-v0.1` (mistral) — $0.11/M in, $0.19/M out, ctx=2,824
- New model ingested: `openai/gpt-3.5-turbo-16k` (openai) — $3.0/M in, $4.0/M out, ctx=16,385
- New model ingested: `openai/gpt-4-0314` (openai) — $30.0/M in, $60.0/M out, ctx=8,191
- New model ingested: `openai/gpt-4` (openai) — $30.0/M in, $60.0/M out, ctx=8,191
- New model ingested: `openai/gpt-3.5-turbo` (openai) — $0.5/M in, $1.5/M out, ctx=16,385


All notable changes to the AI Model Knowledge Repository are documented here.

---

## [1.0.0] — 2026-04-13

### Added
- Flask web UI with dark theme — Catalog, Query, Compare, Ingest tabs
- `/api/models` — returns full model catalog (models.json + models.generated.json)
- `/api/query` — natural language model search via scripts/query.py
- `/api/compare` — side-by-side model comparison with task scoring and cost analysis
- `/api/ingest` — free-text model record ingestion via scripts/ingest.py
- Railway deployment config (Procfile, PORT env var support)
- Real production cost data from OpenRouter activity (8 models, per-call costs, routing tags)
- `openrouter_slug` field added to all model records
- Production performance notes from live agent observation

### Models Seeded
- Claude Sonnet 4.6 (Anthropic) — primary brains model
- MiniMax M2.7 — Amanda's primary agentic model
- Xiaomi MiMo v2 Pro — cheapest capable model
- GPT-5.4 Codex (OpenAI) — Alexander's primary, code specialist
- Gemini 2.5 Flash-Lite (Google) — cheapest cron model
- Gemini 2.5 Flash (Google) — mid-tier balanced
- DeepSeek Chat — budget coding
- Claude Haiku 4.5 (Anthropic) — fast lightweight Anthropic option

## 2026-04-13 — Routing Engine + Direct Provider Integration

### Added
- `scripts/routing_engine.py` — decision engine: openrouter vs direct vs batch vs free-tier
  - Returns endpoint, estimated cost, savings %, confidence, and routing_tags
  - Batch path: 50% off Anthropic/OpenAI (triggers when `--batch` flag or `real_time=False`)
  - Cache path: uses direct native caching when `--cacheable` + `prompt_tokens > 10k`
  - Google free tier detection
  - CLI: `python3 scripts/routing_engine.py --model X --prompt-tokens N [--batch] [--cacheable]`
- `GET /api/route` — HTTP wrapper on routing engine for agent use
  - Params: `model`, `prompt_tokens`, `output_tokens`, `cacheable`, `batch`, `task`
- `scripts/fetch_direct_usage.py` — multi-provider direct API usage fetcher
  - Anthropic: `/v1/organizations/usage` (needs `ANTHROPIC_ADMIN_KEY`)
  - OpenAI: `/v1/organization/usage/completions` (needs `OPENAI_ADMIN_KEY` w/ `api.usage.read`)
  - Google: placeholder key validator (no usage API from AI Studio yet)
  - Graceful fallback with provisioning instructions when keys missing
- Daily cron job (6am ET): `ai-model-repo-direct-usage-sync` runs `fetch_direct_usage.py` via Alexander

### Changed
- `openclaw.json env`: Added `ANTHROPIC_ADMIN_KEY`, `OPENAI_ADMIN_KEY`, `GOOGLE_AI_KEY` placeholders — fill these in to enable direct provider cost tracking

### Next
- Provision admin keys (Eric action): console.anthropic.com → Admin Key, platform.openai.com → Usage: Read key
- Wire agents to call `/api/route` before each model call for automated routing decisions

## 2026-04-13 — Model Detail Modal + Trend Charts + 5-Model Compare

### Added
- **Model detail modal**: Click any model card to open a full dashboard overlay
  - Stat donuts: Efficiency, Input $/MTok, Context window, Total spend, API calls, Confidence
  - Full performance notes, strengths (→), weaknesses (✗), use cases, direct pricing detail
  - SVG line charts: Daily cost (USD) and daily token volume, both with 7-day rolling average
  - 90-day rolling window; gracefully shows "building history" when < 2 data points
  - Close: Esc key, ✕ button, or click backdrop
- **Daily spend history** (`spend_history.json`): `fetch_openrouter_usage.py` now writes per-day breakpoints on every sync
- **`GET /api/spend-history`**: Returns full daily history for all models
- **5-model compare**: Replace A/B selects with dynamic add/remove (up to 5)
  - Each model color-coded (blue/green/amber/red/purple)
  - Horizontal-scroll grid highlights the winner per metric in green
  - Trend overlay chart when ≥2 compared models have daily history

### Changed
- Compare grid is now horizontal-scroll for wide comparisons
- Compare tray updated to support up to 5 selections
- Card click opens model detail (checkbox click still compares; both don't interfere)

### Notes
- Charts use pure SVG — no Chart.js or CDN dependency
- Daily data accumulates from this point forward; historical data estimated from aggregate totals
