#!/usr/bin/env python3
"""
routing_engine.py — Decide whether to call a model via OpenRouter or direct provider API.

Given a model + task context, returns the optimal endpoint with cost estimate and reasoning.
Factors: direct pricing vs openrouter, batch eligibility, cache hit likelihood, free tiers.

Usage (CLI):
  python3 scripts/routing_engine.py --model anthropic/claude-sonnet-4-6 --task agentic --prompt-tokens 50000
  python3 scripts/routing_engine.py --model openai/gpt-4o --batch --prompt-tokens 10000

Usage (Python API):
  from scripts.routing_engine import recommend_route
  result = recommend_route("anthropic/claude-sonnet-4-6", prompt_tokens=50000, cacheable=True)

HTTP endpoint:
  GET /api/route?model=anthropic/claude-sonnet-4-6&prompt_tokens=50000&cacheable=1
  (mounted in app.py at /api/route)

Returns JSON:
  {
    "model_id": "anthropic/claude-sonnet-4-6",
    "recommended": "openrouter",        # or "direct", "batch-direct", "batch-openrouter", "free-tier"
    "endpoint": "https://openrouter.ai/api/v1/chat/completions",
    "estimated_cost_usd": 0.0015,
    "estimated_cost_alt_usd": 0.0018,   # what the other route would cost
    "savings_pct": 17,                  # % cheaper vs alt
    "reason": "Direct batch API saves 50% — large prompt qualifies for batch",
    "routing_tags": ["batch-eligible", "cache-friendly"],
    "confidence": 0.9
  }
"""

import argparse
import json
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
MODELS_FILE = REPO_DIR / "models.json"

# Thresholds
BATCH_MIN_TOKENS = 5_000       # prompts above this may qualify for batch
CACHE_MIN_TOKENS = 10_000      # prompts above this likely benefit from caching
DIRECT_SAVE_THRESHOLD = 5      # % cheaper before recommending direct (avoid churn for <5%)
FREE_TIER_MAX_RPM = 15         # Google AI Studio free tier limit

# Provider direct endpoints
DIRECT_ENDPOINTS = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "openai": "https://api.openai.com/v1/chat/completions",
    "google": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
}

BATCH_ENDPOINTS = {
    "anthropic": "https://api.anthropic.com/v1/messages/batches",
    "openai": "https://api.openai.com/v1/batches",
}

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def load_models():
    return json.loads(MODELS_FILE.read_text())


def find_model(model_id, models):
    for m in models:
        if m["model_id"] == model_id or m.get("openrouter_slug") == model_id:
            return m
    # Fuzzy: suffix match (e.g. "claude-sonnet-4-6" → "anthropic/claude-sonnet-4-6")
    for m in models:
        if m["model_id"].endswith("/" + model_id) or m["model_id"].endswith(model_id):
            return m
    return None


def estimate_cost(pricing_block, prompt_tokens, output_tokens, cacheable=False, cache_hit_ratio=0.0):
    """Estimate cost in USD from a pricing block."""
    if not pricing_block:
        return None
    inp = pricing_block.get("input_per_mtok", 0)
    out = pricing_block.get("output_per_mtok", 0)
    cache_read = pricing_block.get("cache_read_per_mtok", inp * 0.1)

    if cacheable and cache_hit_ratio > 0:
        cached_tokens = prompt_tokens * cache_hit_ratio
        uncached_tokens = prompt_tokens * (1 - cache_hit_ratio)
        input_cost = (uncached_tokens * inp + cached_tokens * cache_read) / 1e6
    else:
        input_cost = prompt_tokens * inp / 1e6

    output_cost = output_tokens * out / 1e6
    return round(input_cost + output_cost, 8)


def estimate_batch_cost(direct_pricing, prompt_tokens, output_tokens):
    """Estimate cost using batch API pricing."""
    if not direct_pricing:
        return None
    batch_inp = direct_pricing.get("batch_input_per_mtok")
    batch_out = direct_pricing.get("batch_output_per_mtok")
    if batch_inp is None or batch_out is None:
        return None
    return round(prompt_tokens * batch_inp / 1e6 + output_tokens * batch_out / 1e6, 8)


def get_provider(model_id):
    parts = model_id.split("/")
    if len(parts) >= 2:
        return parts[0]
    return None


def recommend_route(
    model_id,
    prompt_tokens=1000,
    output_tokens=500,
    cacheable=False,
    cache_hit_ratio=0.3,
    batch=False,
    real_time=True,
    task=None,
):
    """
    Core routing logic. Returns a dict with recommendation and cost estimates.

    Args:
        model_id: model identifier (openrouter slug or model_id)
        prompt_tokens: estimated input token count
        output_tokens: estimated output token count
        cacheable: whether the system prompt is large and consistent (cache candidate)
        cache_hit_ratio: fraction of prompt tokens expected to be cache hits (0.0–1.0)
        batch: whether real-time response is NOT required (can use batch API)
        real_time: if False, batch is preferred when available
        task: optional task description (used for routing_tag matching, not yet scored)
    """
    models = load_models()
    m = find_model(model_id, models)

    if not m:
        return {
            "model_id": model_id,
            "recommended": "openrouter",
            "endpoint": OPENROUTER_ENDPOINT,
            "reason": "Model not found in catalog — defaulting to OpenRouter",
            "confidence": 0.3,
        }

    provider = get_provider(m["model_id"])
    pricing = m.get("pricing") or {}
    direct_pricing = m.get("direct_pricing") or {}
    direct_available = direct_pricing.get("direct_available", False)
    routing_tags = m.get("routing_tags", [])

    # ── Cost estimates ──────────────────────────────────────────────────────────

    cost_or = estimate_cost(pricing, prompt_tokens, output_tokens, cacheable, cache_hit_ratio)
    cost_direct = None
    cost_batch_direct = None
    cost_direct_cached = None

    if direct_available and direct_pricing:
        # Adjust for cache reads
        dp_with_cache = dict(direct_pricing)
        cost_direct = estimate_cost(dp_with_cache, prompt_tokens, output_tokens, False, 0)
        cost_direct_cached = estimate_cost(dp_with_cache, prompt_tokens, output_tokens, cacheable, cache_hit_ratio)
        cost_batch_direct = estimate_batch_cost(direct_pricing, prompt_tokens, output_tokens)

    # ── Google free tier check ───────────────────────────────────────────────────
    if provider == "google" and direct_pricing.get("notes", "").lower().find("free") >= 0:
        # Low-volume usage may qualify for free tier
        if prompt_tokens < 50_000 and not batch:
            return {
                "model_id": m["model_id"],
                "recommended": "free-tier",
                "endpoint": DIRECT_ENDPOINTS.get("google", "").replace("{model}", m["model_id"].split("/")[-1]),
                "estimated_cost_usd": 0.0,
                "estimated_cost_alt_usd": cost_or,
                "savings_pct": 100,
                "reason": "Google AI Studio free tier available (≤15 RPM). Use direct with GOOGLE_AI_KEY.",
                "routing_tags": ["free-tier", "rate-limited"],
                "confidence": 0.7,
                "direct_pricing": direct_pricing,
            }

    # ── Batch API recommendation ─────────────────────────────────────────────────
    if (batch or not real_time) and cost_batch_direct is not None and provider in BATCH_ENDPOINTS:
        savings_vs_or = 0
        if cost_or and cost_or > 0:
            savings_vs_or = round((1 - cost_batch_direct / cost_or) * 100, 1)

        if savings_vs_or >= DIRECT_SAVE_THRESHOLD:
            return {
                "model_id": m["model_id"],
                "recommended": "batch-direct",
                "endpoint": BATCH_ENDPOINTS[provider],
                "estimated_cost_usd": cost_batch_direct,
                "estimated_cost_alt_usd": cost_or,
                "savings_pct": savings_vs_or,
                "reason": f"Batch API saves {savings_vs_or}% vs OpenRouter. No real-time needed.",
                "routing_tags": ["batch-eligible"] + routing_tags,
                "confidence": 0.92,
                "direct_pricing": direct_pricing,
            }

    # ── Cache-boosted direct recommendation ─────────────────────────────────────
    if cacheable and prompt_tokens >= CACHE_MIN_TOKENS and cost_direct_cached is not None:
        savings_vs_or = 0
        if cost_or and cost_or > 0:
            savings_vs_or = round((1 - cost_direct_cached / cost_or) * 100, 1)

        if savings_vs_or >= DIRECT_SAVE_THRESHOLD:
            return {
                "model_id": m["model_id"],
                "recommended": "direct",
                "endpoint": direct_pricing.get("api_url") or DIRECT_ENDPOINTS.get(provider, OPENROUTER_ENDPOINT),
                "estimated_cost_usd": cost_direct_cached,
                "estimated_cost_alt_usd": cost_or,
                "savings_pct": savings_vs_or,
                "reason": f"Direct + cache saves {savings_vs_or}% ({prompt_tokens:,} token prompt, {int(cache_hit_ratio*100)}% cache hit assumed).",
                "routing_tags": ["cache-friendly"] + routing_tags,
                "confidence": 0.85,
                "direct_pricing": direct_pricing,
            }

    # ── Plain direct recommendation ──────────────────────────────────────────────
    if direct_available and cost_direct is not None and cost_or is not None:
        savings_vs_or = round((1 - cost_direct / cost_or) * 100, 1) if cost_or > 0 else 0

        if savings_vs_or >= DIRECT_SAVE_THRESHOLD:
            return {
                "model_id": m["model_id"],
                "recommended": "direct",
                "endpoint": direct_pricing.get("api_url") or DIRECT_ENDPOINTS.get(provider, OPENROUTER_ENDPOINT),
                "estimated_cost_usd": cost_direct,
                "estimated_cost_alt_usd": cost_or,
                "savings_pct": savings_vs_or,
                "reason": f"Direct API is {savings_vs_or}% cheaper than OpenRouter for this model.",
                "routing_tags": routing_tags,
                "confidence": 0.88,
                "direct_pricing": direct_pricing,
            }

    # ── Default: OpenRouter ──────────────────────────────────────────────────────
    reason_parts = []
    if not direct_available:
        reason_parts.append("direct API not available for this model")
    elif cost_direct is not None and cost_or is not None:
        diff_pct = round((cost_direct / cost_or - 1) * 100, 1) if cost_or > 0 else 0
        if diff_pct > 0:
            reason_parts.append(f"OpenRouter is {diff_pct}% cheaper than direct")
        else:
            reason_parts.append(f"direct saves <{DIRECT_SAVE_THRESHOLD}% — not worth the routing complexity")
    else:
        reason_parts.append("no direct pricing data — using OpenRouter")

    return {
        "model_id": m["model_id"],
        "recommended": "openrouter",
        "endpoint": OPENROUTER_ENDPOINT,
        "estimated_cost_usd": cost_or,
        "estimated_cost_alt_usd": cost_direct,
        "savings_pct": 0,
        "reason": "; ".join(reason_parts) if reason_parts else "OpenRouter default",
        "routing_tags": routing_tags,
        "confidence": 0.8 if direct_pricing else 0.5,
        "direct_pricing": direct_pricing or None,
    }


def main():
    parser = argparse.ArgumentParser(description="AI model routing engine")
    parser.add_argument("--model", required=True, help="Model ID or slug")
    parser.add_argument("--prompt-tokens", type=int, default=1000, help="Estimated input token count")
    parser.add_argument("--output-tokens", type=int, default=500, help="Estimated output token count")
    parser.add_argument("--cacheable", action="store_true", help="System prompt is large and consistent")
    parser.add_argument("--cache-hit-ratio", type=float, default=0.3, help="Fraction of prompt tokens expected cached (0.0-1.0)")
    parser.add_argument("--batch", action="store_true", help="Real-time response not required (batch eligible)")
    parser.add_argument("--task", help="Task description (for context)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    result = recommend_route(
        model_id=args.model,
        prompt_tokens=args.prompt_tokens,
        output_tokens=args.output_tokens,
        cacheable=args.cacheable,
        cache_hit_ratio=args.cache_hit_ratio,
        batch=args.batch,
        real_time=not args.batch,
        task=args.task,
    )

    if args.json or not sys.stdout.isatty():
        print(json.dumps(result, indent=2))
        return

    # Human-readable output
    rec = result["recommended"].upper()
    cost = result.get("estimated_cost_usd")
    alt = result.get("estimated_cost_alt_usd")
    savings = result.get("savings_pct", 0)

    print(f"\nModel:       {result['model_id']}")
    print(f"Recommended: {rec}  (confidence: {result.get('confidence', 0)*100:.0f}%)")
    print(f"Endpoint:    {result['endpoint']}")
    if cost is not None:
        print(f"Est. cost:   ${cost:.6f}  |  Alt: ${alt:.6f}" if alt else f"Est. cost:   ${cost:.6f}")
    if savings:
        print(f"Savings:     {savings}% cheaper")
    print(f"Reason:      {result['reason']}")
    if result.get("routing_tags"):
        print(f"Tags:        {', '.join(result['routing_tags'])}")


if __name__ == "__main__":
    main()
