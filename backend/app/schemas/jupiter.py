from __future__ import annotations

from pydantic import BaseModel


class SwapStep(BaseModel):
    amm_key: str
    label: str
    input_mint: str
    output_mint: str
    in_amount: str
    out_amount: str


class RoutePlanStep(BaseModel):
    swap_info: SwapStep
    percent: int | None = None


class JupiterQuote(BaseModel):
    input_mint: str
    output_mint: str
    in_amount: str
    out_amount: str
    other_amount_threshold: str
    swap_mode: str
    slippage_bps: int
    price_impact_pct: str
    route_plan: list[RoutePlanStep]
    context_slot: int | None = None
    time_taken: float | None = None
