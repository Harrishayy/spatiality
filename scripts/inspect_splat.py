#!/usr/bin/env python3
"""Sanity-check a 3DGS PLY: are the fields varied enough to be a real
trained splat, or do they look like the old _fallback_to_points synthesis
(uniform opacity, uniform scale)?

Usage: uv run python scripts/inspect_splat.py path/to/splat.ply
"""

from __future__ import annotations

import argparse
import statistics as s
import struct
import sys
from pathlib import Path


def parse(path: Path) -> tuple[int, dict[str, list[float]]]:
    data = path.read_bytes()
    idx = data.find(b"end_header\n")
    if idx < 0:
        raise SystemExit(f"{path}: no end_header marker")
    idx += len(b"end_header\n")
    header = data[:idx].decode("ascii", errors="replace")
    n = 0
    props: list[tuple[str, str]] = []
    for line in header.splitlines():
        if line.startswith("element vertex "):
            n = int(line.split()[2])
        elif line.startswith("property "):
            parts = line.split()
            props.append((parts[1], parts[2]))
    if not n:
        raise SystemExit(f"{path}: zero vertices")
    sizes = {"float": 4, "float32": 4, "uchar": 1, "uint8": 1}
    stride = sum(sizes[t] for t, _ in props)
    body = data[idx:]
    fmt = "".join(
        {"float": "f", "float32": "f", "uchar": "B", "uint8": "B"}[t] for t, _ in props
    )
    fmt = "<" + fmt
    out: dict[str, list[float]] = {name: [] for _, name in props}
    # Sample up to 5000 vertices.
    import random
    rng = random.Random(0)
    indices = rng.sample(range(n), min(5000, n))
    for i in indices:
        rec = struct.unpack_from(fmt, body, i * stride)
        for (name_pair, v) in zip(props, rec):
            out[name_pair[1]].append(float(v))
    return n, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ply", type=Path)
    args = ap.parse_args()
    n, vals = parse(args.ply)
    print(f"vertices: {n}")
    print(f"props: {', '.join(vals.keys())}")
    print()
    print(f"{'field':10s} {'min':>10s} {'max':>10s} {'mean':>10s} {'stdev':>10s}")
    for name in (
        "x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2",
        "opacity", "scale_0", "scale_1", "scale_2",
        "rot_0", "rot_1", "rot_2", "rot_3",
    ):
        if name not in vals:
            continue
        v = vals[name]
        print(
            f"{name:10s} {min(v):10.4f} {max(v):10.4f} "
            f"{s.mean(v):10.4f} {s.stdev(v):10.4f}"
        )
    print()
    # Diagnose: does this look like a real trained splat?
    flags: list[str] = []
    if "opacity" in vals and s.stdev(vals["opacity"]) < 0.01:
        flags.append("opacity is uniform (synthetic-looking)")
    for k in ("scale_0", "scale_1", "scale_2"):
        if k in vals and s.stdev(vals[k]) < 0.01:
            flags.append(f"{k} is uniform (synthetic-looking)")
            break
    color_var = max(
        (s.stdev(vals[k]) for k in ("f_dc_0", "f_dc_1", "f_dc_2") if k in vals),
        default=0.0,
    )
    if color_var < 0.05:
        flags.append("low color variance")
    if flags:
        print("DIAGNOSIS: looks like fallback / untrained splat")
        for f in flags:
            print(f"  - {f}")
        return 1
    print("DIAGNOSIS: looks like a real trained 3DGS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
