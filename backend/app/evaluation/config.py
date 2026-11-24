"""Configurable evaluation rules (set per tender, confirmed by a human)."""

from typing import Literal

from pydantic import BaseModel, Field


class EvaluationConfig(BaseModel):
    # which stage runs first; "independent" = no dependency between the two
    order: Literal["technical_first", "commercial_first", "independent"] = "technical_first"
    # if true, the second stage is skipped for a vendor the first stage did not qualify
    second_stage_requires_first_qualified: bool = True
    technical_min_score: float = Field(default=0.0, ge=0, le=100)  # % of total criterion weight that must be met
    weight_technical: float = Field(default=0.5, ge=0, le=1)
    weight_commercial: float = Field(default=0.5, ge=0, le=1)

    def validate_weights(self) -> None:
        if abs(self.weight_technical + self.weight_commercial - 1.0) > 1e-6:
            raise ValueError("weight_technical + weight_commercial must equal 1")


def load_config(raw: dict | None) -> EvaluationConfig:
    cfg = EvaluationConfig(**(raw or {}))
    cfg.validate_weights()
    return cfg
