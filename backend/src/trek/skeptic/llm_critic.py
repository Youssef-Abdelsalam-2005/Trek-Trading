"""LLM-as-critic stage for the skeptic pipeline (Stage 4 — advisory, not blocking)."""

from __future__ import annotations

import json
import logging
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

CRITIC_SYSTEM_PROMPT = (
    "You are a quantitative-finance code auditor. You will receive Python strategy code. "
    "Identify lookahead bias, data leakage, or overfitting risk. For each finding, cite "
    "the specific line number(s) and explain the issue concisely. Respond ONLY with valid "
    "JSON matching the schema provided."
)

CRITIC_USER_TEMPLATE = """\
Audit the following strategy code for lookahead bias, data leakage, and overfitting risk.

```python
{strategy_code}
```

Respond with JSON matching this schema exactly:
{{
  "findings": [
    {{
      "line_numbers": [<int>, ...],
      "category": "lookahead_bias" | "data_leakage" | "overfitting",
      "severity": "low" | "medium" | "high",
      "explanation": "<string>"
    }}
  ],
  "summary": "<one-paragraph overall assessment>"
}}

If there are no issues, return {{"findings": [], "summary": "No issues detected."}}.
"""


class FindingCategory(str, Enum):
    LOOKAHEAD_BIAS = "lookahead_bias"
    DATA_LEAKAGE = "data_leakage"
    OVERFITTING = "overfitting"


class FindingSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Finding(BaseModel):
    line_numbers: list[int]
    category: FindingCategory
    severity: FindingSeverity
    explanation: str


class LLMCriticRequest(BaseModel):
    strategy_code: str
    variation_id: str
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 2048


class CostBreakdown(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    latency_ms: float = 0.0


class LLMCriticResult(BaseModel):
    variation_id: str
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""
    cost: CostBreakdown = Field(default_factory=CostBreakdown)
    raw_response: str = ""
    error: str | None = None


TOKEN_COSTS_PER_MILLION: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
}

DEFAULT_COST_PER_MILLION = {"input": 3.0, "output": 15.0}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = TOKEN_COSTS_PER_MILLION.get(model, DEFAULT_COST_PER_MILLION)
    return (prompt_tokens * rates["input"] + completion_tokens * rates["output"]) / 1_000_000


def _parse_critic_response(raw: str) -> tuple[list[Finding], str]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    data = json.loads(text)
    findings = [Finding(**f) for f in data.get("findings", [])]
    summary = data.get("summary", "")
    return findings, summary


async def run_llm_critic(request: LLMCriticRequest) -> LLMCriticResult:
    try:
        import anthropic
    except ImportError:
        return LLMCriticResult(
            variation_id=request.variation_id,
            error="anthropic SDK not installed — add 'anthropic' to dependencies",
        )

    client = anthropic.AsyncAnthropic()
    user_message = CRITIC_USER_TEMPLATE.format(strategy_code=request.strategy_code)

    start = time.monotonic()
    try:
        response = await client.messages.create(
            model=request.model,
            max_tokens=request.max_tokens,
            system=CRITIC_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        log.error("LLM critic call failed: %s", exc)
        return LLMCriticResult(
            variation_id=request.variation_id,
            error=str(exc),
        )
    latency_ms = (time.monotonic() - start) * 1000

    raw_text = response.content[0].text if response.content else ""
    prompt_tokens = response.usage.input_tokens
    completion_tokens = response.usage.output_tokens
    cost_usd = estimate_cost(request.model, prompt_tokens, completion_tokens)

    cost = CostBreakdown(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
        model=request.model,
        latency_ms=latency_ms,
    )

    try:
        findings, summary = _parse_critic_response(raw_text)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        log.warning("Failed to parse LLM critic response: %s", exc)
        return LLMCriticResult(
            variation_id=request.variation_id,
            summary=raw_text[:500],
            cost=cost,
            raw_response=raw_text,
            error=f"Response parse error: {exc}",
        )

    return LLMCriticResult(
        variation_id=request.variation_id,
        findings=findings,
        summary=summary,
        cost=cost,
        raw_response=raw_text,
    )


def critic_result_to_audit_notes(result: LLMCriticResult) -> dict[str, Any]:
    """Format result for storage on a skeptic_audit record's advisory_notes field."""
    return {
        "stage": "llm_critic",
        "status": "error" if result.error else "completed",
        "findings_count": len(result.findings),
        "high_severity_count": sum(
            1 for f in result.findings if f.severity == FindingSeverity.HIGH
        ),
        "findings": [f.model_dump() for f in result.findings],
        "summary": result.summary,
        "cost": result.cost.model_dump(),
        "error": result.error,
    }


async def accumulate_variation_cost(variation_id: str, cost_usd: float) -> None:
    """Add LLM cost to a variation's cumulative cost. Stub until DB models land (Step 2/3)."""
    log.info("Cost +$%.6f for variation %s (DB write pending Step 2/3)", cost_usd, variation_id)
