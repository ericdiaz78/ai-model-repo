# AI Model Knowledge Repository

Lightweight model reference and routing helper for OpenClaw.

## Quick start

- Validate data against `schema.json` with `python3 scripts/update_schema.py validate`
- Query models with `python3 scripts/query.py "best model for coding with low cost"`
- Compare models with `python3 scripts/evaluate.py compare --task "reasoning" --models anthropic/claude-sonnet-4-6 openai/gpt-4o`
- Route a task with `python3 agents/router.py "fast low-cost summarization"`
- Add a provider enum with `python3 scripts/update_schema.py add-provider mistral`
- Ingest free text into a dataset file with `python3 scripts/ingest.py --out models.generated.json "OpenAI GPT-4.1 mini cheap code model with 128k context and $0.4 $1.6 pricing"`
- Query a generated dataset with `python3 scripts/query.py --models models.generated.json "cheap code model"`

## Files

- `models.json` — model dataset
- `schema.json` — JSON schema for validation
- `scripts/ingest.py` — release-note/text ingestion helper
- `scripts/evaluate.py` — compare and recommend models
- `scripts/query.py` — natural-language query helper
- `scripts/update_schema.py` — schema validator and provider enum helper
- `agents/router.py` — routing wrapper for OpenClaw use
- `examples/query_examples.json` — example queries
- `tests/test_eval.py` — smoke tests
- `REFERENCES.md` — maintenance notes

## Status

Initial scaffold created during Alexander heartbeat on 2026-04-09.
Validation coverage added for seeded data and schema/provider checks.
Ingestion/query milestone shipped on 2026-04-12: `scripts/ingest.py` can now upsert normalized model records into a dataset file, and `scripts/query.py` can query either the seed dataset or a generated dataset file.
