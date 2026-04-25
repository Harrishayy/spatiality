"""Resolve where artifacts live, regardless of execution environment.

Locally: defaults to <repo>/artifacts.
On Modal:  ARTIFACTS_PATH=/artifacts  (mounted via Modal Volume — set by modal_app.py).
On Render: ARTIFACTS_PATH=/var/data/artifacts (per render.yaml).
On Brev:   ARTIFACTS_PATH=$WORKSPACE/artifacts (set by deploy/brev/setup.sh).
"""

from __future__ import annotations

import os
from pathlib import Path


def artifacts_root() -> Path:
    env = os.environ.get("ARTIFACTS_PATH")
    if env:
        return Path(env)
    # Walk up from this file to find a sibling `artifacts/` dir; fall back to cwd.
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / "artifacts"
        if candidate.exists():
            return candidate
    return Path.cwd() / "artifacts"


def scene_dir(scene_id: str) -> Path:
    return artifacts_root() / "scenes" / scene_id
