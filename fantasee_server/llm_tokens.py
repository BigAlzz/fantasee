"""Shared completion-token policy for every Fantasee LLM provider call."""

from __future__ import annotations

import os


DEFAULT_LLM_TOKEN_MULTIPLIER = 2
MAX_LLM_TOKEN_MULTIPLIER = 8


def llm_unlimited() -> bool:
    """Whether Fantasee should leave completion sizing to the provider.

    Provider-side context and account limits still apply. This switch only
    removes Fantasee's artificial per-call and per-run completion ceilings.
    """
    return os.environ.get("FANTASEE_LLM_UNLIMITED", "0").strip().lower() in {"1", "true", "yes", "on"}


def llm_token_multiplier() -> int:
    """Return the configured completion-budget multiplier."""
    try:
        value = int(os.environ.get("FANTASEE_LLM_TOKEN_MULTIPLIER", str(DEFAULT_LLM_TOKEN_MULTIPLIER)))
    except (TypeError, ValueError):
        value = DEFAULT_LLM_TOKEN_MULTIPLIER
    return max(1, min(MAX_LLM_TOKEN_MULTIPLIER, value))


def scaled_llm_tokens(tokens: int) -> int:
    """Scale a provider completion limit while keeping it a positive integer."""
    return max(1, int(tokens)) * llm_token_multiplier()
