"""Single-start pipeline: soft-to-rigid relaxation, basin hopping, NLP polish."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy.spatial import cKDTree

from .backend import Backend, default_schedule, get_backend
from .containers import Container
from .energy import feasible_radius, radius_scale
from .polish import AUTO_SPARSE_N, polish

__all__ = ["SearchConfig", "StartResult", "run_start", "perturb_jiggle", "perturb_relocate",
           "local_slack", "lattice_start"]


@dataclass
class SearchConfig:
    """Parameters of one start. Defaults work for n up to a few hundred."""

    hops: int = 20                 # basin-hopping moves after the initial relaxation
    patience: int | None = None    # stop hopping after this many non-improving moves
    mu0: float = 0.5               # softest penalty weight (overlap ~ s / mu)
    mu1: float = 1e10              # most rigid penalty weight
    mu_factor: float = 4.0         # geometric step of the schedule
    mu1_polished: float = 1e3      # schedule end when every candidate is polished
    relax_ftol: float = 1e-9       # L-BFGS relative-decrease tolerance, intermediate stages
    relax_ftol_final: float = 1e-15  # last two stages (slow sliding into the best basin matters)
    prune_mu: float = 1e2          # hops whose penalty radius falls below the best at mu >= prune_mu stop early
    hop_mu0: float = 1.0           # hops re-enter the schedule at a softness drawn
    hop_mu0_max: float | None = 100.0  # log-uniformly in [hop_mu0, hop_mu0_max]
    hop_mu_factor: float = 10.0    # coarser schedule for hops (cheaper)
    init_radius: float = 0.5       # starting r as a fraction of the area scale
    lattice_fraction: float = 0.25  # share of starts seeded from a cut lattice instead of uniform points
    lattice_mu0: float = 30.0      # lattice seeds enter the schedule fairly rigid
    jiggle: float = 0.35           # jiggle amplitude in units of r
    relocate_max: int = 3          # a relocate move moves 1..relocate_max circles
    polish: bool = True
    polish_method: str = "auto"         # SLSQP for n <= 60, sparse SLP above
    polish_margin: float = 0.25
    polish_hops_max_n: int = 150   # dense polish methods: polish every hop candidate up to this n
    backend: str = "numpy"

    def schedule(self, mu_end: float | None = None) -> np.ndarray:
        return default_schedule(self.mu0, mu_end or self.mu1, self.mu_factor)

    def hop_schedule(self, rng: np.random.Generator | None = None,
                     mu_end: float | None = None) -> np.ndarray:
        mu0 = self.hop_mu0
        if self.hop_mu0_max is not None and rng is not None:
            mu0 = float(np.exp(rng.uniform(np.log(self.hop_mu0), np.log(self.hop_mu0_max))))
        return default_schedule(mu0, mu_end or self.mu1, self.hop_mu_factor)


@dataclass
class StartResult:
    seed: int
    n: int
    r: float                       # final (polished) feasible radius
    X: np.ndarray = field(repr=False)
    r_relax: float = 0.0           # feasible radius after the first relaxation
    r_hops: float = 0.0            # best feasible radius after basin hopping
    accepted: int = 0              # improving hops
    seconds: float = 0.0

    def summary(self) -> dict:
        d = asdict(self)
        d.pop("X")
        return d


def local_slack(X: np.ndarray, r: float, container: Container) -> np.ndarray:
    """Per-circle slack: how much circle ``i`` could grow alone (rattlers are large)."""
    if X.shape[0] > 1:
        d, _ = cKDTree(X).query(X, k=2)
        pair = d[:, 1] - 2.0 * r
    else:
        pair = np.full(1, np.inf)
    return np.minimum(pair, container.clearance(X) - r)


def perturb_jiggle(X: np.ndarray, r: float, rng: np.random.Generator, amp: float) -> np.ndarray:
    return X + rng.normal(scale=amp * r * rng.uniform(0.3, 1.0), size=X.shape)


def perturb_relocate(X: np.ndarray, r: float, container: Container, rng: np.random.Generator,
                     k: int) -> np.ndarray:
    """Move ``k`` circles to the largest holes.

    The first circle moved is the one with most slack (a rattler, if any) with
    probability 1/2, otherwise a random one; the rest are random.
    """
    X = X.copy()
    n = X.shape[0]
    if n < 2:
        return X
    cand = container.sample(max(400, 25 * n), rng)
    clear = container.clearance(cand)
    for t in range(k):
        if t == 0 and rng.random() < 0.5:
            i = int(np.argmax(local_slack(X, r, container)))
        else:
            i = int(rng.integers(n))
        others = np.delete(X, i, axis=0)
        dist, _ = cKDTree(others).query(cand, k=1)
        hole = np.minimum(dist - r, clear)
        X[i] = cand[int(np.argmax(hole))]
    return X


def _lattice_points(container: Container, basis: np.ndarray, h: float, offset: np.ndarray,
                    ) -> np.ndarray:
    """Lattice points ``h (i e1 + j e2 + offset)`` whose disk of radius ``h/2`` fits."""
    lo, hi = container.bounding_box()
    ctr = 0.5 * (lo + hi)
    rad = 0.5 * float(np.linalg.norm(hi - lo))
    m = int(np.ceil(rad / (h * 0.5))) + 2  # 0.5 = min |e| * sin(angle) lower bound for our bases
    k = np.arange(-m, m + 1)
    I, J = np.meshgrid(k, k, indexing="ij")
    P = ctr + h * ((I.ravel()[:, None] + offset[0]) * basis[0] + (J.ravel()[:, None] + offset[1]) * basis[1])
    return P[container.clearance(P) >= 0.5 * h]


def lattice_start(container: Container, n: int, rng: np.random.Generator) -> tuple[np.ndarray, float]:
    """Seed from a square or hexagonal lattice cut by the container.

    The lattice is aligned with a random container edge (if any) with
    probability 0.7, otherwise randomly rotated; its spacing is the largest
    for which at least ``n`` lattice disks fit, and surplus sites are removed
    at random (vacancies). Returns ``(X, r)``.
    """
    if container.n_halfplanes and rng.random() < 0.7:
        a = container.A[int(rng.integers(container.n_halfplanes))]
        theta = float(np.arctan2(a[1], a[0]) + np.pi / 2)
    else:
        theta = float(rng.uniform(0, np.pi))
    if rng.random() < 0.5:
        basis = np.array([[1.0, 0.0], [0.0, 1.0]])
    else:
        basis = np.array([[1.0, 0.0], [0.5, np.sqrt(3) / 2]])
    c, s_ = np.cos(theta), np.sin(theta)
    basis = basis @ np.array([[c, s_], [-s_, c]])
    offset = rng.random(2)
    lo, hi = container.bounding_box()
    h_lo, h_hi = 0.0, float(np.max(hi - lo))
    for _ in range(50):
        h = 0.5 * (h_lo + h_hi)
        if len(_lattice_points(container, basis, h, offset)) >= n:
            h_lo = h
        else:
            h_hi = h
    if h_lo == 0.0:
        return container.sample(n, rng), 0.0
    P = _lattice_points(container, basis, h_lo, offset)
    P = P[rng.permutation(len(P))[:n]]
    return P, 0.5 * h_lo


def run_start(container: Container, n: int, seed: int, cfg: SearchConfig | None = None,
              backend: Backend | None = None, X0: np.ndarray | None = None) -> StartResult:
    """Run one complete start and return the best packing it found.

    With the sparse polish (``auto`` above ``AUTO_SPARSE_N``, or ``slp``), or
    for ``n <= cfg.polish_hops_max_n`` with a dense method, every candidate
    (initial relaxation and each hop) is polished, so candidates are compared
    by their exact local optimum and the penalty schedule can stop at
    ``cfg.mu1_polished``. Otherwise (dense polish at large ``n``) candidates
    are compared by the feasible radius after the full schedule, and only the
    best is polished.
    """
    cfg = cfg or SearchConfig()
    # The sparse polish is cheap, so with it every candidate is polished at any n.
    sparse = cfg.polish_method in ("slp", "sparse") or (cfg.polish_method == "auto" and n > AUTO_SPARSE_N)
    polish_each = cfg.polish and (sparse or n <= cfg.polish_hops_max_n)
    # When every candidate is polished the relaxation only has to find the basin.
    backend = backend or get_backend(cfg.backend, floor_mu=cfg.prune_mu, ftol=cfg.relax_ftol,
                                     ftol_final=cfg.relax_ftol_final)
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    s = radius_scale(container, n)
    mu_end = cfg.mu1_polished if polish_each else cfg.mu1

    def evaluate(X: np.ndarray) -> tuple[np.ndarray, float]:
        r = feasible_radius(X, container)
        if polish_each and r > 0:
            pr = polish(X, container, method=cfg.polish_method, margin=cfg.polish_margin)
            return pr.X, pr.r
        return X, r

    r0, mu0 = cfg.init_radius * s, cfg.mu0
    if X0 is not None:
        X = np.asarray(X0, float)
    elif cfg.lattice_fraction > 0 and rng.random() < cfg.lattice_fraction:
        X, rl = lattice_start(container, n, rng)
        if rl > 0:
            r0, mu0 = rl, cfg.lattice_mu0
    else:
        X = container.sample(n, rng)
    Xb, _ = backend.relax(container, X[None], np.array([r0]), s,
                          default_schedule(mu0, mu_end, cfg.mu_factor))
    best_X, best_r = evaluate(Xb[0])
    r_relax = best_r

    accepted = 0
    stale = 0
    for _ in range(cfg.hops):
        if rng.random() < 0.5:
            Xp = perturb_jiggle(best_X, best_r, rng, cfg.jiggle)
        else:
            Xp = perturb_relocate(best_X, best_r, container, rng,
                                  int(rng.integers(1, cfg.relocate_max + 1)))
        Xb, _ = backend.relax(container, Xp[None], np.array([best_r]), s,
                              cfg.hop_schedule(rng, mu_end), r_floor=np.array([best_r]))
        Xp, rp = evaluate(Xb[0])
        if rp > best_r * (1.0 + 1e-11):
            best_X, best_r = Xp, rp
            accepted += 1
            stale = 0
        else:
            stale += 1
            if cfg.patience is not None and stale >= cfg.patience:
                break
    r_hops = best_r

    if cfg.polish and not polish_each and best_r > 0:
        pr = polish(best_X, container, method=cfg.polish_method, margin=cfg.polish_margin)
        best_X, best_r = pr.X, pr.r
    return StartResult(seed=seed, n=n, r=best_r, X=best_X, r_relax=r_relax, r_hops=r_hops,
                       accepted=accepted, seconds=time.perf_counter() - t0)
