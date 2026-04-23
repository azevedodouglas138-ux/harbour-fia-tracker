"""
research_budget.py — Cost tracking, daily cap enforcement, and usage queries
for Claude API calls.

Budget model:
  - Daily cap (USD), configurable via env CLAUDE_DAILY_CAP_USD (default $0.50).
  - Reset at UTC midnight.
  - Each call logs token counts + computed cost to `claude_usage` table.
  - `check_budget()` raises BudgetExceededError if today's cumulative spend
    reached the cap.
"""

import logging
import os
from datetime import datetime

import research_db as _rdb

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pricing (USD per million tokens) — jan/2026
# Update if Anthropic changes pricing.
# ---------------------------------------------------------------------------

PRICING = {
    "claude-haiku-4-5-20251001": {
        "input":       1.00,
        "output":      5.00,
        "cache_read":  0.10,
        "cache_write": 1.25,
    },
    "claude-sonnet-4-6": {
        "input":       3.00,
        "output":     15.00,
        "cache_read":  0.30,
        "cache_write": 3.75,
    },
}

DEFAULT_DAILY_CAP_USD = 0.50


class BudgetExceededError(Exception):
    """Raised when today's cumulative Claude spend reaches the configured cap."""
    pass


# ---------------------------------------------------------------------------
# Cost computation
# ---------------------------------------------------------------------------

def calc_cost(model, input_tokens, cache_read_tokens,
              cache_creation_tokens, output_tokens):
    """Compute USD cost for a single call given token counts.

    Note: Anthropic billing treats cache_read and cache_creation as separate
    categories; the remaining uncached input is billed at the standard rate.
    """
    p = PRICING.get(model)
    if p is None:
        logger.warning("Unknown model %s — cost will be 0", model)
        return 0.0

    input_tokens = int(input_tokens or 0)
    cache_read_tokens = int(cache_read_tokens or 0)
    cache_creation_tokens = int(cache_creation_tokens or 0)
    output_tokens = int(output_tokens or 0)

    # The SDK already reports uncached input_tokens separately from cache_*
    # in Anthropic's Usage object — so input_tokens is the uncached portion.
    # Preserve defensive subtraction in case that ever changes.
    uncached_input = max(0, input_tokens - cache_read_tokens - cache_creation_tokens)

    cost = (
          uncached_input * p["input"]
        + cache_read_tokens * p["cache_read"]
        + cache_creation_tokens * p["cache_write"]
        + output_tokens * p["output"]
    ) / 1_000_000.0

    return round(cost, 6)


# ---------------------------------------------------------------------------
# Logging & cap checks
# ---------------------------------------------------------------------------

def log_usage(user, operation, model, usage_obj):
    """Persist a single call's usage to the DB. Returns the computed cost.

    `usage_obj` is expected to be an anthropic.types.Usage-like object with
    attributes: input_tokens, output_tokens, cache_read_input_tokens,
    cache_creation_input_tokens (last two may be missing in older SDKs).
    """
    input_t  = getattr(usage_obj, "input_tokens", 0) or 0
    output_t = getattr(usage_obj, "output_tokens", 0) or 0
    cache_r  = getattr(usage_obj, "cache_read_input_tokens", 0) or 0
    cache_c  = getattr(usage_obj, "cache_creation_input_tokens", 0) or 0

    cost = calc_cost(model, input_t, cache_r, cache_c, output_t)
    try:
        _rdb.insert_claude_usage(
            user=user or "system",
            operation=operation or "generic",
            model=model,
            input_tokens=input_t,
            cache_read_tokens=cache_r,
            cache_creation_tokens=cache_c,
            output_tokens=output_t,
            cost_usd=cost,
        )
    except Exception as exc:
        logger.error("Failed to persist claude usage: %s", exc)

    logger.info(
        "claude_call user=%s op=%s model=%s input=%d cache_read=%d cache_create=%d output=%d cost=$%.5f",
        user, operation, model, input_t, cache_r, cache_c, output_t, cost,
    )
    return cost


def today_spend_usd():
    """Cumulative USD spend on the current UTC date."""
    return _rdb.sum_claude_usage()


def daily_cap_usd():
    try:
        return float(os.environ.get("CLAUDE_DAILY_CAP_USD", DEFAULT_DAILY_CAP_USD))
    except (TypeError, ValueError):
        return DEFAULT_DAILY_CAP_USD


def check_budget():
    """Raise BudgetExceededError if today's spend >= daily cap.
    Returns dict {spent, cap, remaining, date_utc} on success.
    """
    cap = daily_cap_usd()
    spent = today_spend_usd()
    date_utc = datetime.utcnow().strftime("%Y-%m-%d")
    if spent >= cap:
        raise BudgetExceededError(
            f"Daily Claude cap of ${cap:.2f} reached. "
            f"Spent ${spent:.4f} on {date_utc}. Resets at UTC midnight."
        )
    return {
        "spent": round(spent, 4),
        "cap": round(cap, 2),
        "remaining": round(cap - spent, 4),
        "date_utc": date_utc,
    }


def usage_by_user(days=30):
    """Aggregated usage over last N days grouped by user, operation, model."""
    return _rdb.claude_usage_grouped(days=days)
