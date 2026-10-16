#!/usr/bin/env python3
"""Stand-alone verifier for circlepack solution files (standard library only).

Usage::

    python3 verify.py solution.json [--tol 1e-12] [--exact] [--eps 1e-12]

Float mode
    For every pair, ``slack = |x_i - x_j| - 2r``; for every half-plane
    ``a . x <= b``, ``slack = (b - a . x) / |a| - r``; for every disk
    ``|x - c| <= R``, ``slack = R - |x - c| - r``. Prints the minimum slack of
    each kind and reports VALID if all are ``>= -tol``.

Exact mode (``--exact``)
    Every float in the file is converted *exactly* to a ``fractions.Fraction``
    and the radius is reduced to ``r' = r - eps`` (``eps`` rational). Then
    every constraint is checked in exact rational arithmetic without square
    roots:

    * pairs:       ``|x_i - x_j|^2 >= (2 r')^2``
    * half-planes: ``b - a . x >= 0`` and ``(b - a . x)^2 >= r'^2 |a|^2``
    * disks:       ``R - r' >= 0``   and ``|x - c|^2 <= (R - r')^2``

    VALID in exact mode is a proof that disks of radius ``r - eps`` centred
    at the stored (binary floating point) centres form a packing. For
    containers whose ``spec`` has rational data (square, rectangle, polygon,
    triangle, right_isosceles_triangle, circle, quadrant, semicircle) the
    primitives are rebuilt exactly from the spec; otherwise (e.g. regular
    polygons, whose vertices are irrational) the stored float primitives are
    used and this is stated in the output.

Exit status 0 if VALID, 1 otherwise.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from fractions import Fraction

__all__ = ["verify", "verify_exact", "exact_primitives", "main"]


def _hp_from_vertices(V):
    """Half-planes (a, b) of a convex polygon, exact if V is rational; orientation-independent."""
    area2 = sum(V[i][0] * V[(i + 1) % len(V)][1] - V[(i + 1) % len(V)][0] * V[i][1]
                for i in range(len(V)))
    if area2 < 0:
        V = V[::-1]
    out = []
    for i in range(len(V)):
        (x0, y0), (x1, y1) = V[i], V[(i + 1) % len(V)]
        a = (y1 - y0, -(x1 - x0))
        out.append((a[0], a[1], a[0] * x0 + a[1] * y0))
    return out


def exact_primitives(spec: dict):
    """``(halfplanes, disks)`` as Fractions for rational container specs, else ``None``."""
    F = Fraction
    t = spec.get("type")
    if t in ("square", "rectangle"):
        w = F(spec.get("side", spec.get("width", 1.0)))
        h = F(spec.get("side", spec.get("height", 1.0)))
        return [(F(1), F(0), w / 2), (F(-1), F(0), w / 2), (F(0), F(1), h / 2), (F(0), F(-1), h / 2)], []
    if t in ("polygon", "triangle"):
        return _hp_from_vertices([(F(x), F(y)) for x, y in spec["vertices"]]), []
    if t == "right_isosceles_triangle":
        L = F(spec.get("leg", 1.0))
        return _hp_from_vertices([(F(0), F(0)), (L, F(0)), (F(0), L)]), []
    if t == "circle":
        return [], [(F(0), F(0), F(spec.get("radius", 1.0)))]
    if t == "quadrant":
        return [(F(-1), F(0), F(0)), (F(0), F(-1), F(0))], [(F(0), F(0), F(spec.get("radius", 1.0)))]
    if t == "semicircle":
        return [(F(0), F(-1), F(0))], [(F(0), F(0), F(spec.get("radius", 1.0)))]
    return None


def _load(path):
    with open(path) as f:
        d = json.load(f)
    if not isinstance(d, dict) or "container" not in d or "centers" not in d:
        raise ValueError("missing 'container' or 'centers'")
    c = d["container"]
    hp = [tuple(map(float, h)) for h in c.get("halfplanes", [])]
    dk = [tuple(map(float, k)) for k in c.get("disks", [])]
    P = [tuple(map(float, p)) for p in d["centers"]]
    r = float(d["r"])
    if "n" in d and int(d["n"]) != len(P):
        raise ValueError(f"n = {d['n']} but {len(P)} centres given")
    return d, hp, dk, P, r


def verify(path, tol=1e-12):
    """Float check. Returns ``(ok, report_dict)``."""
    d, hp, dk, P, r = _load(path)
    pair = math.inf
    worst_pair = None
    for (i, p), (j, q) in itertools.combinations(enumerate(P), 2):
        s = math.hypot(p[0] - q[0], p[1] - q[1]) - 2 * r
        if s < pair:
            pair, worst_pair = s, (i, j)
    wall = math.inf
    for a1, a2, b in hp:
        na = math.hypot(a1, a2)
        for x, y in P:
            wall = min(wall, (b - a1 * x - a2 * y) / na - r)
    for cx, cy, R in dk:
        for x, y in P:
            wall = min(wall, R - math.hypot(x - cx, y - cy) - r)
    ok = r > 0 and pair >= -tol and wall >= -tol
    return ok, {"n": len(P), "r": r, "min_pair_slack": pair, "worst_pair": worst_pair,
                "min_container_slack": wall, "tol": tol}


def verify_exact(path, eps="1e-12"):
    """Exact rational check with radius ``r - eps``. Returns ``(ok, report_dict)``."""
    d, hp, dk, P, r = _load(path)
    F = Fraction
    rr = F(r) - F(eps)
    ex = exact_primitives(d["container"].get("spec", {}))
    source = "spec (exact)"
    if ex is None:
        ex = ([(F(a1), F(a2), F(b)) for a1, a2, b in hp], [(F(cx), F(cy), F(R)) for cx, cy, R in dk])
        source = "stored float primitives"
    HP, DK = ex
    Q = [(F(x), F(y)) for x, y in P]
    fails = []
    four_r2 = 4 * rr * rr
    for (i, p), (j, q) in itertools.combinations(enumerate(Q), 2):
        dx, dy = p[0] - q[0], p[1] - q[1]
        if dx * dx + dy * dy < four_r2:
            fails.append(("pair", i, j))
    for k, (a1, a2, b) in enumerate(HP):
        na2 = a1 * a1 + a2 * a2
        for i, (x, y) in enumerate(Q):
            s = b - a1 * x - a2 * y
            if s < 0 or s * s < rr * rr * na2:
                fails.append(("halfplane", i, k))
    for k, (cx, cy, R) in enumerate(DK):
        for i, (x, y) in enumerate(Q):
            m = R - rr
            if m < 0 or (x - cx) ** 2 + (y - cy) ** 2 > m * m:
                fails.append(("disk", i, k))
    ok = rr > 0 and not fails
    return ok, {"n": len(Q), "r": r, "eps": str(F(eps)) if not isinstance(eps, str) else eps,
                "primitives": source, "failures": fails[:20], "n_failures": len(fails)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="verify", description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--tol", type=float, default=1e-12, help="float-mode tolerance (default 1e-12)")
    ap.add_argument("--exact", action="store_true", help="also run the exact rational check")
    ap.add_argument("--eps", default="1e-12", help="exact mode: radius reduction (default 1e-12)")
    a = ap.parse_args(argv)
    all_ok = True
    for path in a.files:
        try:
            ok, rep = verify(path, a.tol)
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"{path}\n  ERROR: not a readable solution file ({type(e).__name__}: {e})")
            all_ok = False
            continue
        print(f"{path}\n  n = {rep['n']}  r = {rep['r']!r}")
        print(f"  min pair slack      = {rep['min_pair_slack']:.6e}  (pair {rep['worst_pair']})")
        print(f"  min container slack = {rep['min_container_slack']:.6e}")
        print(f"  float check (tol {a.tol:g}): {'VALID' if ok else 'INVALID'}")
        if a.exact:
            eok, erep = verify_exact(path, a.eps)
            print(f"  exact check, r - {a.eps}, primitives from {erep['primitives']}: "
                  f"{'VALID' if eok else 'INVALID'}"
                  + ("" if eok else f"  ({erep['n_failures']} failures, e.g. {erep['failures'][:3]})"))
            ok = ok and eok
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
