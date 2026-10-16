"""Old (dense SLSQP) vs new (sparse SLP) polish on identical global-phase outputs.

For each case the global phase (relaxation + a few basin-hopping moves,
no polish) is run once per seed; its centres are cached in ``--cache`` and then
polished by each method. Usage::

    python benchmarks/scripts/polish_compare.py --cases square:100,square:300,circle:100 \
        --seeds 2 --hops 2 --workers 6 --methods SLSQP,slp
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np


def _global(name: str, n: int, seed: int, hops: int, cache: str) -> str:
    from circlepack.containers import make_container
    from circlepack.search import SearchConfig, run_start

    os.nice(10)
    path = Path(cache) / f"{name}_n{n}_s{seed}_h{hops}.npy"
    if not path.exists():
        t = time.perf_counter()
        res = run_start(make_container(name), n, seed, SearchConfig(hops=hops, polish=False))
        np.save(path, res.X)
        (path.with_suffix(".json")).write_text(json.dumps({"seconds": time.perf_counter() - t}))
    return str(path)


def _polish(name: str, n: int, path: str, method: str) -> dict:
    from circlepack.containers import make_container
    from circlepack.energy import feasible_radius
    from circlepack.polish import polish

    os.nice(10)
    c = make_container(name)
    X = np.load(path)
    t = time.perf_counter()
    pr = polish(X, c, method=method)
    return {"case": f"{name}:{n}", "file": Path(path).name, "method": method,
            "seconds": time.perf_counter() - t, "r0": feasible_radius(X, c), "r": pr.r}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="square:100,square:150,square:200,square:300,circle:100,circle:200")
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--hops", type=int, default=2)
    ap.add_argument("--methods", default="SLSQP,slp")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--cache", default="results/polish_cache")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    from circlepack.records import known_radius

    Path(a.cache).mkdir(parents=True, exist_ok=True)
    cases = [(c.split(":")[0], int(c.split(":")[1])) for c in a.cases.split(",")]
    with ProcessPoolExecutor(a.workers) as ex:
        jobs = [(nm, n, s) for nm, n in cases for s in range(a.seeds)]
        paths = list(ex.map(_global, *zip(*[(nm, n, s, a.hops, a.cache) for nm, n, s in jobs])))
        tasks = [(nm, n, p, m) for (nm, n, _), p in zip(jobs, paths) for m in a.methods.split(",")]
        rows = list(ex.map(_polish, *zip(*tasks)))
    print("| case | seed file | method | s | r (global) | r (polished) | rel. gap to record |")
    print("|---|---|---|---:|---:|---:|---:|")
    for row in rows:
        nm, n = row["case"].split(":")
        rec = known_radius(nm, int(n))
        row["record"] = rec
        row["rel_gap"] = (rec - row["r"]) / rec
        print(f"| {row['case']} | {row['file']} | {row['method']} | {row['seconds']:.2f} | {row['r0']:.12f} | "
              f"{row['r']:.15f} | {row['rel_gap']:.3e} |", flush=True)
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
