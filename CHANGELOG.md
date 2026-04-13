# Changelog

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
