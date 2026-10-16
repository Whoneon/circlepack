"""Compare against the Moki & Julio claims (github.com/Hashirama1337s/moki-julio-circle-packing).

Their data (CC-BY-4.0) is *not* copied into this repository: point ``--repo``
at a local clone. Two sub-commands:

``verify``  convert some of their ``.pck`` coordinate files to circlepack JSON
            (in a temporary directory) and run circlepack's float and exact
            verifiers on them::

                python benchmarks/scripts/mj_compare.py verify --repo ../external/moki-julio-circle-packing \\
                    --table crc_300 --n 20,61,287

``compare`` print Packomania vs Moki & Julio vs our best radius for every n in
            one of our benchmark directories (``summary.json``)::

                python benchmarks/scripts/mj_compare.py compare --repo ... --table crc_300 \\
                    --ours benchmarks/rectangle_0.3
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
import zipfile
from decimal import Decimal, getcontext
from pathlib import Path

import numpy as np

from circlepack.containers import make_container
from circlepack.solution import save_solution
from circlepack.verify import verify, verify_exact

getcontext().prec = 60

#: Packomania table -> circlepack container spec. Coordinate frames were
#: checked against the files (crc centred at the origin, crt/ccq in the
#: positive quadrant, csc on y >= 0).
TABLES = {
    "crc_100": {"type": "rectangle", "width": 1.0, "height": 0.1},
    "crc_200": {"type": "rectangle", "width": 1.0, "height": 0.2},
    "crc_300": {"type": "rectangle", "width": 1.0, "height": 0.3},
    "crc_400": {"type": "rectangle", "width": 1.0, "height": 0.4},
    "crc_500": {"type": "rectangle", "width": 1.0, "height": 0.5},
    "crc_600": {"type": "rectangle", "width": 1.0, "height": 0.6},
    "crc_700": {"type": "rectangle", "width": 1.0, "height": 0.7},
    "crc_800": {"type": "rectangle", "width": 1.0, "height": 0.8},
    "crt": {"type": "right_isosceles_triangle"},
    "ccq": {"type": "quadrant"},
    "csc": {"type": "semicircle"},
    "csq": {"type": "square"},
}


def manifest(repo: Path) -> dict[tuple[str, int], dict]:
    with open(repo / "MANIFEST.csv") as f:
        return {(row["shelf"], int(row["N"])): row for row in csv.DictReader(f)}


def read_pck(repo: Path, table: str, n: int) -> tuple[Decimal, list[tuple[Decimal, Decimal]]]:
    z = zipfile.ZipFile(repo / "packomania" / f"{table}.zip")
    prefix = table.split("_")[0]
    names = [nm for nm in z.namelist()
             if nm.startswith(f"{prefix}{n}.") or nm.startswith(f"{prefix}{n}_")]
    if not names:
        raise KeyError(f"no coordinates for {table} n={n}")
    lines = z.read(names[0]).decode().split("\n")
    r = Decimal(lines[0].split()[0])
    pts = [tuple(Decimal(t) for t in ln.split()[:2]) for ln in lines[2:] if ln.strip()]
    if len(pts) != n:
        raise ValueError(f"{names[0]}: {len(pts)} centres, expected {n}")
    return r, pts


def cmd_verify(a) -> int:
    repo = Path(a.repo)
    container = make_container(**TABLES[a.table])
    ok_all = True
    print(f"| table | n | M&J radius | float min slack | exact (r - {a.eps}) |")
    print("|---|---:|---:|---:|---|")
    with tempfile.TemporaryDirectory() as tmp:
        for n in [int(x) for x in a.n.split(",")]:
            r, pts = read_pck(repo, a.table, n)
            X = np.array([[float(x), float(y)] for x, y in pts])
            p = save_solution(Path(tmp) / f"{a.table}_{n}.json", container, X, float(r),
                              {"source": "Moki & Julio (CC-BY-4.0), converted for verification"})
            ok, rep = verify(p, tol=1e-12)
            eok, _ = verify_exact(p, eps=a.eps)
            slack = min(rep["min_pair_slack"], rep["min_container_slack"])
            ok_all &= ok and eok
            print(f"| {a.table} | {n} | {r:.15f} | {slack:+.2e} | {'VALID' if eok else 'INVALID'} |")
    return 0 if ok_all else 1


def cmd_compare(a) -> int:
    repo = Path(a.repo)
    mj = manifest(repo)
    rows = json.loads((Path(a.ours) / "summary.json").read_text())
    print("| n | Packomania | Moki & Julio | ours | ours - best known | status |")
    print("|---:|---:|---:|---:|---:|---|")
    counts = {"beats both": 0, "matches frontier": 0, "matches Packomania only": 0, "below": 0}
    for row in rows:
        n, ours, pk = row["n"], row["ours"], row["known"]
        m = mj.get((a.table, n))
        mjr = float(m["new_radius"]) if m else None
        frontier = max(pk, mjr or 0.0)
        tol = a.rtol * frontier
        if ours > frontier + tol:
            st = "**BEATS BOTH**"
            counts["beats both"] += 1
        elif ours >= frontier - tol:
            st = "= frontier"
            counts["matches frontier"] += 1
        elif ours >= pk - a.rtol * pk:
            st = "= Packomania, < M&J"
            counts["matches Packomania only"] += 1
        else:
            st = "below"
            counts["below"] += 1
        print(f"| {n} | {pk:.12f} | {mjr:.12f} | {ours:.12f} | {ours - frontier:+.1e} | {st} |"
              if mjr else f"| {n} | {pk:.12f} | — | {ours:.12f} | {ours - frontier:+.1e} | {st} |")
    print("\n" + ", ".join(f"{k}: {v}" for k, v in counts.items()))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("verify")
    p.add_argument("--repo", required=True)
    p.add_argument("--table", required=True, choices=sorted(TABLES))
    p.add_argument("--n", required=True)
    p.add_argument("--eps", default="1e-12")
    p.set_defaults(func=cmd_verify)
    p = sub.add_parser("compare")
    p.add_argument("--repo", required=True)
    p.add_argument("--table", required=True)
    p.add_argument("--ours", required=True, help="benchmark directory with summary.json")
    p.add_argument("--rtol", type=float, default=1e-9)
    p.set_defaults(func=cmd_compare)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
