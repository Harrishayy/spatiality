"""Knob defaults for cad_export. All overridable via env vars (spec §"Knobs")."""

from __future__ import annotations

import os
from typing import Literal

FallbackMode = Literal["auto", "nksr", "poisson", "none"]


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


VIEW_K: int = _int_env("CAD_VIEW_K", 4)
VIEW_MIN_ANGLE_DEG: float = _float_env("CAD_VIEW_MIN_ANGLE_DEG", 30.0)
VIEW_MIN_VISIBLE_FRAC: float = _float_env("CAD_VIEW_MIN_VISIBLE_FRAC", 0.30)
REGISTER_RMSE_FRAC: float = _float_env("CAD_REGISTER_RMSE_FRAC", 0.08)
ACCEPT_BBOX_IOU: float = _float_env("CAD_ACCEPT_BBOX_IOU", 0.30)
MAX_FACES: int = _int_env("CAD_MAX_FACES", 150_000)
TRELLIS_SEED: int = _int_env("CAD_TRELLIS_SEED", 42)


def fallback_mode() -> FallbackMode:
    raw = os.environ.get("CAD_FALLBACK", "auto").lower()
    if raw not in ("auto", "nksr", "poisson", "none"):
        raise ValueError(f"CAD_FALLBACK must be one of auto/nksr/poisson/none, got {raw!r}")
    return raw  # type: ignore[return-value]


ARCHITECTURAL_LABEL_PATTERN = r"^(wall|floor|ceiling|window|door)$"
