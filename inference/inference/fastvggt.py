"""FastVGGT pose + per-pixel surfel synthesis.

Drop-in replacement for poses.py. Same outputs (cameras.json, points.ply,
surfels.npz), same downstream contract (splat.py is untouched). The only
difference is the model: FastVGGT (mystorm16/FastVGGT) is a training-free
fork of facebookresearch/vggt that adds token-merging to attention layers,
~3-4× faster at high frame counts (the speedup amortizes across frames so
it's most valuable when feeding hundreds of views).

Why this is a separate file rather than a flag inside poses.py:
- FastVGGT and vanilla VGGT both `import vggt.models.vggt`, so they can't
  both be `pip install`'d at once. We path-inject one or the other at
  module load time inside `_load_model`.
- FastVGGT has a different image preprocessor (518-wide, height multiple
  of 14, [0, 1] not ImageNet-normalised) and requires a per-batch
  `update_patch_dimensions` call. Wrapping that around poses.py would be
  more code than just forking the entry function.

Frame budget defaults are pushed up here (700 frames @ 10 fps) because the
whole point of FastVGGT is making large frame counts tractable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

# Reuse all the surfel synthesis machinery from the vanilla path —
# everything downstream of the model output (depth / pose decoding,
# unprojection, basis quaternions, surfel synthesis, PLY/NPZ writers) is
# identical. Only the model load + image preprocessing changes.
from .poses import (
    SH_C0,
    _basis_to_quat_wxyz,  # noqa: F401  (used inside _frame_surfels)
    _frame_surfels,
    _is_safetensors,
    _save_cameras,
    _save_points_ply,
    _smooth_depth,  # noqa: F401  (used inside _frame_surfels)
    _unproject_frame,  # noqa: F401  (used inside _frame_surfels)
)
from ._frame_select import select_frames as _select_frames_impl

VGGT_CHECKPOINT = os.environ.get("VGGT_CHECKPOINT", "facebook/VGGT-1B")
VGGT_LOCAL_WEIGHTS = os.environ.get("VGGT_LOCAL_WEIGHTS")  # /weights/vggt.pt on Modal

# FastVGGT lives at /opt/fastvggt on the Modal image (cloned, not pip-installed).
# Path injection at import time makes `import vggt.models.vggt` resolve to the
# fork. Process-local because each inference stage runs in its own subprocess.
FASTVGGT_REPO_PATH = os.environ.get("FASTVGGT_REPO_PATH", "/opt/fastvggt")

# ── Tunable knobs (defaults mirrored in modal_app.py:COMMON_ENV) ─────────
# Frame budget: FastVGGT is the path you take when you want to feed lots of
# frames, so the cap is 700 by default (10 fps × ~70 s of capture). Min floor
# stays modest so a short clip still works.
FASTVGGT_FRAMES_MAX = int(os.environ.get("FASTVGGT_FRAMES_MAX", "700"))
FASTVGGT_FRAMES_MIN = int(os.environ.get("FASTVGGT_FRAMES_MIN", "16"))
FASTVGGT_FPS_TARGET = float(os.environ.get("FASTVGGT_FPS_TARGET", "10.0"))
FASTVGGT_BLUR_DROP_PCT = float(os.environ.get("FASTVGGT_BLUR_DROP_PCT", "0.20"))

# Token-merging hyperparameters — defaults from FastVGGT/eval/eval_custom.py.
# `merging=0` enables the merging strategy (it's the block index at which it
# starts; 0 = from the bottom up). `merge_ratio=0.9` keeps 90% of tokens after
# merging at each block.
FASTVGGT_MERGING = int(os.environ.get("FASTVGGT_MERGING", "0"))
FASTVGGT_MERGE_RATIO = float(os.environ.get("FASTVGGT_MERGE_RATIO", "0.9"))

# Depth confidence threshold. FastVGGT's eval_custom.py uses a high threshold
# (default 3.0) because their depth_conf head outputs values >>1; vanilla VGGT
# uses [0,1]-style values gated at 0.2. We expose a separate knob so we can
# tune without touching the vanilla path.
FASTVGGT_DEPTH_CONF_MIN = float(os.environ.get("FASTVGGT_DEPTH_CONF_MIN", "0.2"))


# ── Frame selection ─────────────────────────────────────────────────────
def _select_frames(frames_dir: Path) -> list[Path]:
    return _select_frames_impl(
        frames_dir,
        frames_max=FASTVGGT_FRAMES_MAX,
        frames_min=FASTVGGT_FRAMES_MIN,
        blur_drop_pct=FASTVGGT_BLUR_DROP_PCT,
        log_prefix="fastvggt",
    )


# ── FastVGGT model + preprocessing ──────────────────────────────────────
def _ensure_fastvggt_on_path() -> None:
    """Inject FastVGGT into sys.path ahead of any installed `vggt` package.

    This MUST happen before `import vggt.models.vggt`. Process-local: safe
    because cli.py runs the poses stage in its own subprocess.
    """
    if not Path(FASTVGGT_REPO_PATH).exists():
        raise RuntimeError(
            f"FastVGGT repo not found at {FASTVGGT_REPO_PATH}; "
            "expected the Modal image to clone it (see modal_app.py)"
        )
    if FASTVGGT_REPO_PATH not in sys.path:
        sys.path.insert(0, FASTVGGT_REPO_PATH)
    # If the vanilla `vggt` package was already imported in this process,
    # purge it so the next import resolves to FastVGGT.
    for mod in list(sys.modules):
        if mod == "vggt" or mod.startswith("vggt."):
            del sys.modules[mod]


def _load_model():
    """Load the FastVGGT model. Same VGGT-1B weights as vanilla; the speedup
    is purely from token-merging in the attention layers."""
    _ensure_fastvggt_on_path()

    import torch
    from vggt.models.vggt import VGGT

    model = VGGT(
        merging=FASTVGGT_MERGING,
        merge_ratio=FASTVGGT_MERGE_RATIO,
        vis_attn_map=False,
    )
    if VGGT_LOCAL_WEIGHTS:
        if _is_safetensors(VGGT_LOCAL_WEIGHTS):
            from safetensors.torch import load_file as _safe_load
            state = _safe_load(VGGT_LOCAL_WEIGHTS, device="cpu")
        else:
            state = torch.load(VGGT_LOCAL_WEIGHTS, map_location="cpu")
            if isinstance(state, dict) and "model" in state and isinstance(state["model"], dict):
                state = state["model"]
        missing, unexpected = model.load_state_dict(state, strict=False)
        if missing:
            print(f"fastvggt: {len(missing)} missing keys (first: {missing[0]})")
        if unexpected:
            print(f"fastvggt: {len(unexpected)} unexpected keys (first: {unexpected[0]})")
    else:
        # Pull the standard VGGT-1B weights from HF; FastVGGT reuses them.
        # `from_pretrained` is provided by the fork (inherited from vanilla).
        model = VGGT.from_pretrained(
            VGGT_CHECKPOINT,
            merging=FASTVGGT_MERGING,
            merge_ratio=FASTVGGT_MERGE_RATIO,
            vis_attn_map=False,
        )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    # FastVGGT runs in bf16 end-to-end (their eval_custom.py forces this).
    return model.eval().to(device).to(torch.bfloat16)


def _preprocess(paths: list[Path]):
    """FastVGGT's preprocessing pipeline: 518 wide, height multiple of 14,
    bicubic resize, [0, 1] tensor (NOT ImageNet-normalised). Returns
    (S, 3, H, W) plus the patch grid dims required by `update_patch_dimensions`.
    """
    from PIL import Image
    import torch
    from torchvision import transforms as TF

    to_tensor = TF.ToTensor()
    tensors = []
    final_h = final_w = None
    for p in paths:
        img = Image.open(p).convert("RGB")
        w, h = img.size
        new_w = 518
        new_h = round(h * (new_w / w) / 14) * 14
        img = img.resize((new_w, new_h), Image.Resampling.BICUBIC)
        t = to_tensor(img)  # (3, H, W) in [0, 1]
        if new_h > 518:
            start = (new_h - 518) // 2
            t = t[:, start : start + 518, :]
            final_h = 518
        else:
            final_h = new_h
        final_w = new_w
        tensors.append(t)
    batch = torch.stack(tensors)
    patch_w = final_w // 14
    patch_h = final_h // 14
    return batch, patch_w, patch_h


# ── Public entry point ──────────────────────────────────────────────────
def run(frames_dir: Path, out_dir: Path) -> None:
    """Run FastVGGT, then synthesize per-pixel surfels.

    Outputs match poses.run() exactly:
        cameras.json   — list of {frame, extrinsic, intrinsic}
        points.ply     — binary RGB+conf cloud (debug artifact)
        surfels.npz    — per-pixel surfel arrays consumed by splat.py
    """
    _ensure_fastvggt_on_path()

    import torch
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri

    paths = _select_frames(frames_dir)
    images, patch_w, patch_h = _preprocess(paths)  # (S, 3, H, W) in [0, 1]
    print(f"fastvggt: patch grid {patch_w}x{patch_h}", flush=True)

    model = _load_model()
    model.update_patch_dimensions(patch_w, patch_h)

    device = next(model.parameters()).device
    images_dev = images.to(device).to(torch.bfloat16)

    with torch.no_grad():
        try:
            ctx = torch.cuda.amp.autocast(dtype=torch.bfloat16) if device.type == "cuda" \
                else torch.cpu.amp.autocast(dtype=torch.bfloat16)
        except (AttributeError, TypeError):
            from contextlib import nullcontext
            ctx = nullcontext()
        with ctx:
            preds = model(images_dev)

    # ── Cameras (extrinsics + intrinsics from pose_enc) ─────────────────
    extr, intr = pose_encoding_to_extri_intri(preds["pose_enc"], images.shape[-2:])
    _save_cameras(extr, intr, paths, out_dir / "cameras.json")

    # ── Depth + confidence (per-pixel, camera-frame depth) ──────────────
    if "depth" not in preds or "depth_conf" not in preds:
        raise RuntimeError(
            "fastvggt: model output missing depth/depth_conf; "
            "the FastVGGT fork does not expose the depth head"
        )
    depth = preds["depth"].squeeze(0).detach().float().cpu().numpy()           # (S, H, W, 1) or (S, H, W)
    depth_conf = preds["depth_conf"].squeeze(0).detach().float().cpu().numpy()  # (S, H, W)
    if depth.ndim == 4 and depth.shape[-1] == 1:
        depth = depth[..., 0]
    extr_np = extr.squeeze(0).detach().cpu().numpy()  # (S, 3, 4) or (S, 4, 4)
    intr_np = intr.squeeze(0).detach().cpu().numpy()  # (S, 3, 3)

    if extr_np.shape[-2:] == (3, 4):
        bottom = np.tile(np.array([0, 0, 0, 1], dtype=extr_np.dtype), (extr_np.shape[0], 1, 1))
        extr_np = np.concatenate([extr_np, bottom], axis=1)

    # FastVGGT preprocessing already gave us [0, 1] RGB at exactly the depth
    # resolution — no need to re-decode and resample like poses.py does.
    rgb_all = images.detach().float().permute(0, 2, 3, 1).cpu().numpy()  # (S, H, W, 3)

    # ── Per-frame surfel synthesis, stacked across frames ───────────────
    parts = []
    for i in range(len(paths)):
        part = _frame_surfels(
            depth=depth[i],
            depth_conf=depth_conf[i],
            rgb=rgb_all[i],
            K=intr_np[i],
            E=extr_np[i],
        )
        parts.append(part)
        print(
            f"fastvggt: frame {i + 1}/{len(paths)} → {part['xyz'].shape[0]} surfels",
            flush=True,
        )

    def _cat(key: str) -> np.ndarray:
        return np.concatenate([p[key] for p in parts], axis=0) if parts else np.empty((0,))

    surfels = {k: _cat(k) for k in ("xyz", "f_dc", "opacity", "log_scale", "quat", "conf")}
    n_total = surfels["xyz"].shape[0]
    if n_total == 0:
        raise RuntimeError(
            "fastvggt: zero surfels survived confidence/gradient gates — "
            "FastVGGT depth output is degenerate (check input frames + weights)"
        )
    print(f"fastvggt: {n_total} total surfels across {len(paths)} frames", flush=True)

    np.savez(
        out_dir / "surfels.npz",
        xyz=surfels["xyz"],
        f_dc=surfels["f_dc"],
        opacity=surfels["opacity"],
        log_scale=surfels["log_scale"],
        quat=surfels["quat"],
        conf=surfels["conf"],
    )

    rgb_decoded = (surfels["f_dc"] * SH_C0 + 0.5).clip(0.0, 1.0)
    _save_points_ply(surfels["xyz"], rgb_decoded, surfels["conf"], out_dir / "points.ply")

    print(
        f"fastvggt: {len(paths)} frames -> cameras.json + points.ply + surfels.npz "
        f"({n_total} surfels)",
        flush=True,
    )
