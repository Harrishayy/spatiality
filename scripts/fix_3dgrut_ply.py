"""
Reformat a 3DGRUT-flavored gaussian-splat PLY into the INRIA layout that
@mkkellogg/gaussian-splats-3d expects.

3DGRUT writes:   x y z scale_0..2 rot_0..3 f_dc_0..2 opacity
INRIA wants:     x y z nx ny nz f_dc_0..2 opacity scale_0..2 rot_0..3
                 (plus optional f_rest_* for SH > 0; we emit SH0 only)

Usage:
    uv run python scripts/fix_3dgrut_ply.py <in.ply> [out.ply]

If out.ply is omitted the input is rewritten in place (after a .bak copy).
"""

from __future__ import annotations

import shutil
import struct
import sys
from pathlib import Path

import numpy as np


SRC_FIELDS = [
    "x", "y", "z",
    "scale_0", "scale_1", "scale_2",
    "rot_0", "rot_1", "rot_2", "rot_3",
    "f_dc_0", "f_dc_1", "f_dc_2",
    "opacity",
]

DST_FIELDS = [
    "x", "y", "z",
    "nx", "ny", "nz",
    "f_dc_0", "f_dc_1", "f_dc_2",
    "opacity",
    "scale_0", "scale_1", "scale_2",
    "rot_0", "rot_1", "rot_2", "rot_3",
]


def parse_header(data: bytes) -> tuple[int, list[str], int]:
    end = data.find(b"end_header\n")
    if end < 0:
        raise ValueError("no end_header marker")
    header = data[: end + len(b"end_header\n")].decode("ascii", errors="replace")
    lines = header.splitlines()
    if lines[0] != "ply":
        raise ValueError("not a PLY file")
    if "format binary_little_endian 1.0" not in header:
        raise ValueError(f"unsupported format; need binary_little_endian 1.0\n{header}")
    n = None
    props: list[str] = []
    for line in lines:
        if line.startswith("element vertex "):
            n = int(line.split()[2])
        elif line.startswith("property float "):
            props.append(line.split()[2])
    if n is None:
        raise ValueError("no vertex element")
    return n, props, end + len(b"end_header\n")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = Path(sys.argv[1]).resolve()
    dst = Path(sys.argv[2]).resolve() if len(sys.argv) >= 3 else src

    raw = src.read_bytes()
    n, props, body_off = parse_header(raw)

    if props == DST_FIELDS:
        print(f"{src.name}: already INRIA layout — nothing to do")
        return 0
    if props != SRC_FIELDS:
        print(f"{src.name}: unrecognized field set: {props}")
        return 1

    body = np.frombuffer(raw, dtype="<f4", count=n * len(SRC_FIELDS), offset=body_off)
    body = body.reshape(n, len(SRC_FIELDS))
    src_idx = {name: i for i, name in enumerate(SRC_FIELDS)}

    out = np.zeros((n, len(DST_FIELDS)), dtype="<f4")
    for j, name in enumerate(DST_FIELDS):
        if name in src_idx:
            out[:, j] = body[:, src_idx[name]]
        # nx/ny/nz default to 0 (no normals in 3DGRUT output)

    header_lines = [
        "ply",
        "format binary_little_endian 1.0",
        f"element vertex {n}",
        *(f"property float {name}" for name in DST_FIELDS),
        "end_header",
        "",
    ]
    new_header = "\n".join(header_lines).encode("ascii")

    if dst == src:
        bak = src.with_suffix(src.suffix + ".bak")
        if not bak.exists():
            shutil.copy2(src, bak)
            print(f"backup → {bak}")

    with open(dst, "wb") as f:
        f.write(new_header)
        f.write(out.tobytes(order="C"))

    print(f"{dst}: wrote {n} vertices, {len(DST_FIELDS)} props ({dst.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
