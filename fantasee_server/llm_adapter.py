"""Bounded, measurable LLM calls for granular creative production."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable


def estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 3) // 4)


@dataclass
class TokenBudget:
    limit: int
    reserved_tokens: int = 0
    actual_tokens: int = 0
    retries: int = 0
    escalations: int = 0

    def reserve(self, amount: int) -> None:
        amount = max(1, int(amount))
        if self.actual_tokens + self.reserved_tokens + amount > self.limit:
            raise ValueError("LLM token budget would be exceeded")
        self.reserved_tokens += amount

    def settle(self, reserved: int, actual: int) -> None:
        self.reserved_tokens = max(0, self.reserved_tokens - reserved)
        self.actual_tokens += max(0, int(actual))


@dataclass(frozen=True)
class LLMResult:
    name: str
    text: str
    estimated_tokens: int
    actual_tokens: int
    retries: int = 0


class GranularLLMAdapter:
    """Call an LLM for one bounded commission and account for its spend."""

    def __init__(
        self,
        call: Callable[..., str | None],
        *,
        budget: TokenBudget,
        temperature: float = 0.7,
    ):
        self.call = call
        self.budget = budget
        self.temperature = temperature

    def complete(
        self,
        *,
        name: str,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float | None = None,
    ) -> LLMResult:
        reserved = max(1, int(max_tokens))
        self.budget.reserve(reserved)
        retries = 0
        try:
            try:
                text = self.call(
                    system,
                    prompt,
                    temperature=self.temperature if temperature is None else temperature,
                    max_tokens=reserved,
                )
            except TypeError:
                text = self.call(system, prompt, self.temperature if temperature is None else temperature)
            if not text:
                raise RuntimeError(f"LLM returned no content for {name}")
            actual = estimate_tokens(text)
            return LLMResult(
                name=name,
                text=text,
                estimated_tokens=estimate_tokens(system) + estimate_tokens(prompt),
                actual_tokens=actual,
                retries=retries,
            )
        finally:
            actual = estimate_tokens(text) if "text" in locals() and text else 0
            self.budget.settle(reserved, actual)
