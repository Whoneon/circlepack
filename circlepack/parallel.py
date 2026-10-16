"""Parallel multi-start driver."""
from __future__ import annotations

import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .containers import Container
from .search import SearchConfig, StartResult, run_start

__all__ = ["default_workers", "run_many", "MultiStartResult"]


def default_workers() -> int:
    """``min(10, cpu_count - 2)``, at least 1."""
    return max(1, min(10, (os.cpu_count() or 1) - 2))


def _init_worker(nice: int) -> None:
    for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, "1")
    if nice and hasattr(os, "nice"):
        try:
            os.nice(nice)
        except OSError:
            pass


def _job(spec: dict, n: int, seed: int, cfg: SearchConfig) -> StartResult:
    return run_start(Container.from_dict(spec), n, seed, cfg)


@dataclass
class MultiStartResult:
    best: StartResult
    results: list[StartResult] = field(repr=False)
    seconds: float = 0.0

    def radii(self) -> np.ndarray:
        return np.array([r.r for r in self.results])

    def hits(self, target: float, rtol: float = 1e-9) -> int:
        """Number of starts whose radius reaches ``target`` within ``rtol``."""
        return int(np.sum(self.radii() >= target * (1.0 - rtol)))


def run_many(container: Container, n: int, starts: int, *, workers: int | None = None,
             cfg: SearchConfig | None = None, seed: int = 0, nice: int = 10,
             progress: Callable[[StartResult, int, int], None] | None = None) -> MultiStartResult:
    """Run ``starts`` independent starts (seeds ``seed .. seed+starts-1``).

    ``workers=1`` runs in-process (handy for debugging and tests). Worker
    processes are started with ``spawn`` and lowered to ``nice`` priority.
    """
    cfg = cfg or SearchConfig()
    workers = default_workers() if workers is None else max(1, int(workers))
    seeds = list(range(seed, seed + starts))
    t0 = time.perf_counter()
    results: list[StartResult] = []
    if workers == 1:
        for k, s in enumerate(seeds):
            res = run_start(container, n, s, cfg)
            results.append(res)
            if progress:
                progress(res, k + 1, starts)
    else:
        spec = container.to_dict()
        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=min(workers, starts), mp_context=ctx,
                                 initializer=_init_worker, initargs=(nice,)) as ex:
            futs = [ex.submit(_job, spec, n, s, cfg) for s in seeds]
            for k, f in enumerate(as_completed(futs)):
                res = f.result()
                results.append(res)
                if progress:
                    progress(res, k + 1, starts)
    results.sort(key=lambda r: -r.r)
    return MultiStartResult(best=results[0], results=results, seconds=time.perf_counter() - t0)


def print_progress(res: StartResult, k: int, total: int) -> None:
    print(f"  [{k:>4}/{total}] seed {res.seed:>6}  r = {res.r:.15f}  "
          f"(relax {res.r_relax:.10f}, hops +{res.accepted})  {res.seconds:6.2f}s",
          file=sys.stderr, flush=True)
