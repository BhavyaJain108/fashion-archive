"""Run/coverage models (spec §4.5)."""

from pydantic import BaseModel, Field


class Coverage(BaseModel):
    extracted: int
    channel_counts: dict[str, int] = Field(default_factory=dict)
    coverage_pct: float
    field_fill: dict[str, float] = Field(default_factory=dict)
    verdict: str  # "ok" | "degraded" | "failed"
    reasons: list[str] = Field(default_factory=list)
