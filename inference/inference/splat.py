"""3DGRUT splat training.

Spec: plans/modules/02_inference.md. 3DGRUT (nv-tlabs/3dgrut) uses Hydra
configs and a `train.py` entry point. We invoke it as a subprocess so we
don't have to import its internals.

3DGRUT's actual CLI varies between versions. We try a couple of known invocations
in order. If your fork uses different args, override with INFERENCE_3DGRUT_CMD
(a JSON list, e.g. '["python","/opt/3dgrut/train.py","--config","..."]').

While the subprocess runs we tail its stdout and emit `logfire.info(
"3dgrut_iteration", scene_id, step, loss)` events at the milestones called
out in plans/modules/08_observability.md (1k / 3k / 7k). These show up as
visual markers on the parent span and prove the training was real.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import logfire

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


# Match step + (optionally) loss in lines like:
#   "iter 1000  loss=0.0512"
#   "step: 7000, loss=0.012"
#   "[3000/7000]  loss 0.043"
_STEP_RE = re.compile(r"(?:iter|step|iteration)\D*?(\d{3,7})", re.IGNORECASE)
_LOSS_RE = re.compile(r"loss[=:\s]+([0-9]*\.?[0-9]+)", re.IGNORECASE)
# Default milestones; override via INFERENCE_3DGRUT_MILESTONES="1000,3000,7000".
_DEFAULT_MILESTONES = (1000, 3000, 7000)


def _milestones() -> tuple[int, ...]:
    raw = os.environ.get("INFERENCE_3DGRUT_MILESTONES")
    if not raw:
        return _DEFAULT_MILESTONES
    try:
        return tuple(int(x.strip()) for x in raw.split(",") if x.strip())
    except ValueError:
        return _DEFAULT_MILESTONES


def _stream_with_milestones(cmd: list[str], scene_id: str | None) -> int:
    """Run cmd, mirror its output, and emit logfire.info events at milestones.

    Returns the number of milestone events emitted (for the parent span attr).
    """
    targets = _milestones()
    fired: set[int] = set()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    assert proc.stdout is not None
    last_loss: float | None = None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        loss_match = _LOSS_RE.search(line)
        if loss_match:
            try:
                last_loss = float(loss_match.group(1))
            except ValueError:
                pass
        step_match = _STEP_RE.search(line)
        if not step_match:
            continue
        try:
            step = int(step_match.group(1))
        except ValueError:
            continue
        # Fire on first sighting of any milestone.
        for t in targets:
            if t not in fired and step >= t:
                fired.add(t)
                logfire.info(
                    "3dgrut_iteration",
                    scene_id=scene_id,
                    step=t,
                    observed_step=step,
                    loss=last_loss,
                )
    rc = proc.wait()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)
    return len(fired)


def _fallback_to_points(
    out_ply: Path,
    points_ply: Path | None,
    reason: str,
    *,
    frames_dir: Path | None = None,
    cameras_json: Path | None = None,
) -> int:
    """Degrade to a point-cloud-derived synthetic Gaussian splat.

    3DGRUT has heavy runtime deps and integration gaps that aren't worth blocking
    a demo on. Instead, when 3DGRUT can't run, we synthesize a Gaussian-splat PLY
    from VGGT's seed points: each point becomes an isotropic Gaussian.

    For each point we project into every keyframe and take the median pixel
    color across the frames where it lands inside the image — this turns the
    cloud from invisible-mid-gray into something that actually shows the scene.

    Output schema matches the inria 3DGS / supersplat conventions:
      x, y, z, scale_0..2 (log-scale), rot_0..3 (quat wxyz, identity),
      f_dc_0..2 (color DC, decoded as (rgb - 0.5) / 0.282), opacity (logit).
    """
    if not (points_ply and points_ply.exists()):
        out_ply.write_bytes(_gaussian_ply_header(0))
        print(f"splat: 3DGRUT unavailable ({reason}) and no points.ply seed. Wrote empty splat.")
        return 0

    import numpy as np

    pts = _read_xyz_ply(points_ply)
    n = len(pts)
    # Synthetic Gaussian params:
    # - log-scale = ln(0.03) ≈ -3.5, ~3cm radius (visible at typical viewer distance)
    # - identity quaternion (w=1, x=y=z=0)
    # - opacity logit ≈ 4 (sigmoid → 0.98)
    log_scale = float(np.log(0.03))
    sh_const_inv = 1.0 / 0.282094791  # 1 / Y_0_0 in spherical harmonics
    opacity_logit = 4.0

    rgb = _sample_colors_from_frames(pts, frames_dir, cameras_json)
    # f_dc encodes (rgb - 0.5) * sh_const_inv, with rgb in [0,1].
    color_dc = (rgb - 0.5) * sh_const_inv

    out_ply.write_bytes(_gaussian_ply_header(n))
    with out_ply.open("ab") as f:
        rows = np.empty((n, 14), dtype=np.float32)
        rows[:, 0:3] = pts
        rows[:, 3:6] = log_scale
        rows[:, 6] = 1.0  # rot_0 (w)
        rows[:, 7:10] = 0.0  # rot_1..3 (x, y, z)
        rows[:, 10:13] = color_dc
        rows[:, 13] = opacity_logit
        f.write(rows.tobytes(order="C"))

    print(
        f"splat: 3DGRUT unavailable ({reason}). Wrote {n} synthetic gaussians "
        f"(scale=3cm, sampled colors) -> {out_ply.name}"
    )
    return 0


def _sample_colors_from_frames(pts, frames_dir, cameras_json):
    """For each xyz point, return an (N, 3) RGB-in-[0,1] array sampled from
    keyframes via the known cameras. Falls back to mid-gray when projection
    inputs are missing or no frame contains the point."""
    import numpy as np

    n = len(pts)
    fallback = np.full((n, 3), 0.5, dtype=np.float32)
    if frames_dir is None or cameras_json is None:
        return fallback
    try:
        cameras = json.loads(Path(cameras_json).read_text())
    except Exception:
        return fallback
    if not cameras:
        return fallback

    try:
        from PIL import Image
    except Exception:
        return fallback

    homo = np.concatenate([pts, np.ones((n, 1), dtype=np.float32)], axis=1)
    accum = np.zeros((n, 3), dtype=np.float64)
    counts = np.zeros(n, dtype=np.int32)

    # Sample at most ~12 frames evenly across the trajectory; full coverage is overkill.
    step = max(1, len(cameras) // 12)
    for cam in cameras[::step]:
        try:
            ext = np.asarray(cam["extrinsic"], dtype=np.float32)
            intr = np.asarray(cam["intrinsic"], dtype=np.float32)
            frame_path = frames_dir / cam["frame"]
            if not frame_path.exists():
                continue
            img = np.asarray(Image.open(frame_path).convert("RGB"), dtype=np.float32) / 255.0
        except Exception:
            continue
        h, w, _ = img.shape
        cam_pts = homo @ ext.T
        z = cam_pts[:, 2]
        in_front = z > 1e-6
        safe_z = np.where(in_front, z, 1.0)
        pix = (cam_pts[:, :3] / safe_z[:, None]) @ intr.T
        u = np.rint(pix[:, 0]).astype(np.int32)
        v = np.rint(pix[:, 1]).astype(np.int32)
        ok = in_front & (u >= 0) & (u < w) & (v >= 0) & (v < h)
        if not ok.any():
            continue
        idx = np.flatnonzero(ok)
        accum[idx] += img[v[idx], u[idx]]
        counts[idx] += 1

    seen = counts > 0
    if not seen.any():
        return fallback
    out = fallback.copy()
    out[seen] = (accum[seen] / counts[seen, None]).astype(np.float32)
    return out


_GAUSSIAN_PLY_PROPS = (
    "property float x", "property float y", "property float z",
    "property float scale_0", "property float scale_1", "property float scale_2",
    "property float rot_0", "property float rot_1", "property float rot_2", "property float rot_3",
    "property float f_dc_0", "property float f_dc_1", "property float f_dc_2",
    "property float opacity",
)


def _gaussian_ply_header(n: int) -> bytes:
    return (
        f"ply\nformat binary_little_endian 1.0\nelement vertex {n}\n"
        + "\n".join(_GAUSSIAN_PLY_PROPS)
        + "\nend_header\n"
    ).encode()


def _read_xyz_ply(path: Path):
    """Minimal ASCII-PLY x/y/z reader — matches what poses._save_points writes."""
    import numpy as np

    with path.open() as f:
        line = ""
        while line.strip() != "end_header":
            line = f.readline()
            if not line:
                return np.empty((0, 3), dtype=np.float32)
        rows = []
        for line in f:
            parts = line.split()
            if len(parts) >= 3:
                rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
    return np.array(rows, dtype=np.float32)


def run(
    frames_dir: Path,
    cameras_json: Path,
    out_ply: Path,
    iterations: int = 7000,
    scene_id: str | None = None,
) -> int:
    """Run 3DGRUT; return the count of milestone events emitted.

    Degrades to copying points.ply -> splat.ply if 3DGRUT can't run.
    Set INFERENCE_3DGRUT_REQUIRED=1 to force a hard failure instead.
    """
    points_ply = cameras_json.parent / "points.ply"
    required = os.environ.get("INFERENCE_3DGRUT_REQUIRED") == "1"

    root = Path(THREEDGRUT_ROOT)
    if not root.exists():
        if required:
            raise FileNotFoundError(f"3DGRUT not found at {root}.")
        return _fallback_to_points(
            out_ply,
            points_ply,
            f"missing root {root}",
            frames_dir=frames_dir,
            cameras_json=cameras_json,
        )

    cmds = [c for c in _candidate_commands(root, frames_dir, cameras_json, out_ply, iterations) if c]
    last_err: Exception | None = None
    for cmd in cmds:
        print(f"3dgrut: trying {' '.join(cmd)}", flush=True)
        try:
            milestones_fired = _stream_with_milestones(cmd, scene_id=scene_id)
        except subprocess.CalledProcessError as e:
            last_err = e
            print(f"  -> failed with exit {e.returncode}, trying next", flush=True)
            continue
        except FileNotFoundError as e:
            last_err = e
            print(f"  -> {e}, trying next", flush=True)
            continue

        # 3DGRUT writes wherever `out_dir` says; if our out_ply isn't there, find it.
        if out_ply.exists():
            return milestones_fired
        candidates = list(out_ply.parent.rglob("*.ply"))
        if candidates:
            best = max(candidates, key=lambda p: p.stat().st_size)
            shutil.copy(best, out_ply)
            print(f"3dgrut: copied {best} -> {out_ply}")
            return milestones_fired
        last_err = RuntimeError(f"3dgrut succeeded but produced no .ply in {out_ply.parent}")

    if required:
        raise RuntimeError(f"3dgrut: all candidate commands failed. Last error: {last_err}")
    return _fallback_to_points(
        out_ply,
        points_ply,
        f"all commands failed: {last_err}",
        frames_dir=frames_dir,
        cameras_json=cameras_json,
    )
