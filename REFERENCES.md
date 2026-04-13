# References

## Manual update flow

1. Add or ingest a model record into `models.json`
2. Validate it against `schema.json`
3. Review routing tags and pricing
4. Record source and confidence in `_meta`

## Querying

- `python3 scripts/query.py "best model for coding with low cost"`
- `python3 scripts/evaluate.py recommend --task "large-context reasoning" --required-tags reasoning --min-context-window 100000`

## Routing

- `python3 agents/router.py "fast summarization"`

## Validation

Use a JSON Schema validator or the future validation helper to verify `models.json` matches `schema.json`.
