from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PolicyConfig:
    ml_auto_approve_threshold: float = 30.0
    ml_auto_reject_threshold: float = 85.0
    clock_mismatch_minutes_threshold: int = 60
    reject_risk_threshold: int = 70
    approve_risk_threshold: int = 25
    approve_positive_signals_threshold: int = 4

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PolicyConfig":
        return PolicyConfig(
            ml_auto_approve_threshold=float(data.get("ml_auto_approve_threshold", 30.0)),
            ml_auto_reject_threshold=float(data.get("ml_auto_reject_threshold", 85.0)),
            clock_mismatch_minutes_threshold=int(data.get("clock_mismatch_minutes_threshold", 60)),
            reject_risk_threshold=int(data.get("reject_risk_threshold", 70)),
            approve_risk_threshold=int(data.get("approve_risk_threshold", 25)),
            approve_positive_signals_threshold=int(data.get("approve_positive_signals_threshold", 4)),
        )


def load_policy_config(path: str | None) -> PolicyConfig:
    if not path:
        return PolicyConfig()

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Policy config not found: {path}")

    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("Policy config must be a JSON object")

    return PolicyConfig.from_dict(payload)
