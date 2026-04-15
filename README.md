# AI Model Knowledge Repository

Curated model reference and routing helper for the OPIX/EMD OpenClaw infrastructure.

## Catalog Structure

```
models/
  active.json     — 8 models, proven in production, our telemetry
  discovery.json   — 15 candidates, benchmarked, awaiting test
  archive.json     — 118 auto-ingested models, not currently relevant
models.json       — active + discovery combined (what the tools query by default)
```

**Active catalog** — models with real production data: call counts, costs, latency, observed failure modes. These are what we route to today.

**Discovery shelf** — benchmarked candidates that fit our stack but haven't been tested in our environment. We try them when the right task comes up or run them on low-stakes jobs first. If they prove out over 2–3 weeks, they move to the active catalog.

**Archive** — the 100+ auto-ingested models from OpenRouter that don't yet have profiles. Not deleted, just not in the active view.

## Benchmark Sources

Before adding a model to the discovery shelf, validate against:
- *LMSYS Chatbot Arena* — human ELO rankings, real side-by-side
- *Artificial Analysis* — independent throughput/latency benchmarks
- *OpenRouter* — actual failure rates, latency p50/p95
- *r/LocalLLaMA* — uncensored real-world performance notes

YouTube reviews worth watching: Mitchell Clark, Matthew Berman, AI Explained.

## Quick Start

```bash
# Query the active + discovery catalog
python3 scripts/query.py "best model for coding with low cost"
python3 scripts/query.py "reasoning task with budget constraint"

# Compare two models for a task
python3 scripts/evaluate.py compare --task reasoning --models anthropic/claude-sonnet-4-6 openai/gpt-5.4-pro

# Route a task (returns model + endpoint recommendation)
python3 agents/router.py "fast low-cost summarization"

# Check endpoint economics (direct vs OpenRouter vs batch)
python3 scripts/routing_engine.py --model anthropic/claude-sonnet-4-6 --task agentic --prompt-tokens 50000

# Validate schema
python3 scripts/update_schema.py validate

# Ingest a new model from free text
python3 scripts/ingest.py --out models/discovery.json "OpenAI o3-mini reasoning model 2025"
```

## Security

Each model has security notes in `_meta.security`:
- `api_path` — direct, openrouter, or both
- `data_retention` — what the provider stores
- `prompt_injection_resistance` — high/medium/low
- `notes` — relevant exposure flags

## Adding Models

1. Research benchmark data from the sources above
2. Add to `models/discovery.json` with `benchmarks` and `security` fields filled
3. Set `_meta.needs_review = false` once reviewed
4. Move to `models/active.json` after 2–3 weeks of successful production use
5. Document promotion in CHANGELOG.md with `_meta.promoted_date`

## Files

- `models.json` — active + discovery catalog
- `models/active.json` — production-proven models
- `models/discovery.json` — candidates awaiting production test
- `models/archive.json` — auto-ingested models, not currently relevant
- `models/original_full.json` — pre-restructure full catalog (2026-04-15 snapshot)
- `schema.json` — JSON schema with shelf/security/benchmark extensions
- `scripts/query.py` — natural language model query
- `scripts/evaluate.py` — compare and recommend models
- `scripts/routing_engine.py` — endpoint routing (direct vs OpenRouter vs batch)
- `agents/router.py` — OpenClaw routing wrapper
- `scripts/ingest.py` — free-text model ingestion helper
- `scripts/update_schema.py` — schema validator

## Maintenance

- Run `python3 scripts/update_schema.py validate` after any manual edits
- Sync spend data: `python3 scripts/import_spend.py` (requires OPENROUTER_API_KEY)
- Auto-ingestion is disabled — new models are added manually via the discovery shelf process above
