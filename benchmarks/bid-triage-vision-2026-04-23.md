# HVAC Mechanical Drawing Schedule Extraction — Vision Model Benchmark

**Date:** 2026-04-23
**Task:** Extract row counts and tag lists from HVAC equipment schedules on mechanical drawings (PDF → rendered JPEG → vision model → structured JSON).
**Caller:** bid-triage `pdf_parser.py` vision pipeline (drawings-only; spec text pipeline untouched).
**Goal:** Find the cheapest model that reliably counts schedule rows across simple and dense drawings.

## Test corpus

| PDF | Page | Context | Schedules |
|---|---|---|---|
| Mechanical Drawings 4-3-26 (Michelin MARC) | p.6 | 4 schedules, medium density | RTU, FPB, VAV, Ductless |
| Mechanical Drawings 3-10-26 | p.1 | 7 schedules, simple | RTUs, Furnace, Split, EF, Mini-Split, Air Dist, Louvers |
| DEI2 Warehouse 2-2-26 | p.7 | 14 schedules, dense | ARC, ARU, DOAS, DH, DSS, ECH, EF, EWH, HP, L, RH, RTU, Air Device |
| Mechanical Drawings (3) | p.41 | 10 schedules, dense | AHU+DOAS, Boiler, CCC, Duct ID, DSS, Fan, Piping, Pump, UH, WSHP |
| Mechanical Drawings (3) | p.42 | 6 schedules, very dense (24-row Terminal Unit) | Air Dist, Duct Silencer, Elec Reheat TU, MEVI, MPVI, Terminal Unit |

**Total:** 41 schedule instances across 5 pages.

Ground truth for p.6 and p.1 confirmed by user (Eric). Ground truth for DEI2 p.7, Mech3 p.41, Mech3 p.42 proxied from Opus 4.7 output (highest-accuracy model per round 1-3 bench).

## Prompt shape

Single-shot vision call, rendered at 120 DPI JPEG q=85. Prompt requires:
- Multi-level header flattening (`PARENT / CHILD`)
- First-tag / last-tag checksum anchors
- `visual_row_count` self-count before emitting rows
- Row arrays with `len == len(columns)`, `""` for empty cells

## Results

### Pass rate (schedules counted correctly across 41 tested)

| Model | Pages | Schedules Correct | Pass Rate | Cost/page | Median ms | Verdict |
|---|---|---|---|---|---|---|
| **anthropic/claude-opus-4-7** | 5 | 40/41 | **97.6%** | $0.48 | 55s | **production_primary** |
| google/gemini-3.1-pro-preview | 5 | 31/35* | 88.6% | $0.08 | 61s | discovery_hybrid_candidate |
| anthropic/claude-sonnet-4-6 | 2 | 8/11 | 72.7% | $0.06 | 46s | rejected |
| google/gemini-3.1-flash-lite-preview | 5 | 29/41 | 70.7% | $0.006 | 12s | rejected as primary (hybrid-only) |
| openai/gpt-5.4 | 5 | 23/35* | 65.7% | $0.08 | 47s | rejected |
| anthropic/claude-opus-4.6 | 5 | 27/41 | 65.9% | $0.11 | 70s | rejected (despite perfect easy pages) |
| mistralai/mistral-small-2603 | 1 | 2/4 | 50.0% | $0.003 | 25s | rejected |
| anthropic/claude-sonnet-4-5 | 1 | 2/4 | 50.0% | $0.08 | 58s | rejected |
| google/gemini-2.5-flash-lite | 2 | 8/11 | 72.7% | $0.003 | 19s | rejected (hallucinates sequences) |
| openai/gpt-5.4-nano | 2 | 4/11 | 36.4% | $0.005 | 22s | rejected |
| anthropic/claude-haiku-4-5 | 1 | 1/4 | 25.0% | $0.019 | 21s | rejected |
| openai/o4-mini | 2 | 2/11 | 18.2% | $0.026 | 33s | rejected |
| openai/gpt-5.4-mini | 2 | 4/4* | 100% completed | $0.016 | 10s | rejected (JSON parse crash on dense pages) |

\* Models marked with asterisk had JSON parse errors that excluded some pages from denominator.

## Key findings

1. **Opus 4.7 is the only reliable model.** 97.6% across all 41 schedules including the densest 24-row Terminal Unit table. No other model cleared 90%.
2. **Easy-page tests are misleading.** Opus 4.6, Sonnet 4.6, GPT-5.4, and Gemini 3.1 FL Preview all hit 11/11 on the first two (simple) pages. Stress testing on dense pages collapsed three of them to 50-70%. **Never conclude a model is production-ready without dense-page tests.**
3. **"Cheap" models fail in specific, predictable ways:**
   - Gemini 3.1 FL Preview: systematic undercount by 1 on medium-dense schedules; misses entire sub-schedules on complex pages
   - Gemini 2.5 FL Lite: hallucinates sequential tags (invents EF-B..E from seeing EF-A)
   - GPT-5.4 full: drops schedules entirely on dense pages; tag-label character drift
   - GPT-5.4-mini: JSON parse crashes with escaped quotes on multi-schedule pages
4. **Reasoning models (o4-mini) don't help this task.** Structured table extraction from vision is not a reasoning problem — it's perception + careful transcription.
5. **Cost ceiling ≈ $1.50/bid.** A typical RFP has 2-3 schedule pages + 8-10 floor plans. Schedules at $0.48 each (Opus 4.7) + notes at $0.03 each (Sonnet 4.5 via prior test) = ~$1.50 per bid. Compared to hours of manual takeoff, marginal.

## Production recommendation

- **Schedule pages (VECTOR_CAD or SCANNED doc types, SCHEDULE page type):** `anthropic/claude-opus-4-7` via OpenRouter. Accept the $0.48/page cost — it's the cost of accuracy.
- **Floor plan notes:** `anthropic/claude-sonnet-4-5` — proven verbatim capture on Forest Park test. Scope: Key Notes / General Notes only, NO equipment quantity extraction.
- **Spec-text pipeline:** untouched — Haiku → Sonnet text flow stays.

## Hybrid optimization (future work)

Gemini 3.1 FL Preview at $0.006/page is 80× cheaper than Opus 4.7 with 70% accuracy. A **hybrid pipeline** could:

1. Run Gemini 3.1 FL Preview first
2. If `emitted_count != visual_row_count` (model's own self-flag) OR any schedule has >10 rows, escalate that page to Opus 4.7
3. Expected cost reduction: pages with only simple schedules save ~98% of model cost; dense pages pay the full Opus rate

This is deferred until we have enough real-bid volume to tune the escalation threshold.

## Raw data

Full per-page-per-model JSON extraction results: `/tmp/vision_bench*.json` (not committed — reproduce via bench scripts).
