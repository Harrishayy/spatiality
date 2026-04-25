"""3DGRUT splat training.

Spec: plans/modules/02_inference.md. 3DGRUT (nv-tlabs/3dgrut) uses Hydra
configs and a `train.py` entry point. We invoke it as a subprocess so we
don't have to import its internals.

3DGRUT's actual CLI varies between versions. We try a couple of known invocations
in order. If your fork uses different args, override with INFERENCE_3DGRUT_CMD
(a JSON list, e.g. '["python","/opt/3dgrut/train.py","--config","..."]').
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

THREEDGRUT_ROOT = os.environ.get("THREEDGRUT_ROOT", "/opt/3dgrut")
INFERENCE_3DGRUT_CMD = os.environ.get("INFERENCE_3DGRUT_CMD")  # JSON list override


def _candidate_commands(root: Path, frames_dir: Path, cameras_json: Path, out_ply: Path, iterations: int) -> list[list[str]]:
    """Best-guess 3DGRUT invocations. We try them in order."""
    py = sys.executable
    train_py = root / "train.py"
    scripts_train_py = root / "scripts" / "train.py"
    return [
        # Explicit user override
        json.loads(INFERENCE_3DGRUT_CMD) if INFERENCE_3DGRUT_CMD else None,
        # Hydra-style (likely in newer 3DGRUT)
        [
            py, str(train_py),
            f"path={frames_dir}",
            f"out_dir={out_ply.parent}",
            f"max_steps={iterations}",
        ] if train_py.exists() else None,
        # Older script-style
        [
            py, str(scripts_train_py),
            "--frames", str(frames_dir),
            "--cameras", str(cameras_json),
            "--out", str(out_ply),
            "--iterations", str(iterations),
        ] if scripts_train_py.exists() else None,
    ]


def run(frames_dir: Path, cameras_json: Path, out_ply: Path, iterations: int = 7000) -> None:
    root = Path(THREEDGRUT_ROOT)
    if not root.exists():
        raise FileNotFoundError(
            f"3DGRUT not found at {root}. Set THREEDGRUT_ROOT or install per "
            "plans/modules/10_kaggle.md."
        )

    cmds = [c for c in _candidate_commands(root, frames_dir, cameras_json, out_ply, iterations) if c]
    last_err: Exception | None = None
    for cmd in cmds:
        print(f"3dgrut: trying {' '.join(cmd)}", flush=True)
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            last_err = e
            print(f"  -> failed with exit {e.returncode}, trying next", flush=True)
            continue

        # 3DGRUT writes wherever `out_dir` says; if our out_ply isn't there, find it.
        if out_ply.exists():
            return
        candidates = list(out_ply.parent.rglob("*.ply"))
        if candidates:
            best = max(candidates, key=lambda p: p.stat().st_size)
            shutil.copy(best, out_ply)
            print(f"3dgrut: copied {best} -> {out_ply}")
            return
        last_err = RuntimeError(f"3dgrut succeeded but produced no .ply in {out_ply.parent}")

    raise RuntimeError(f"3dgrut: all candidate commands failed. Last error: {last_err}")
