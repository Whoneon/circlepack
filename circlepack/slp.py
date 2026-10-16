"""Sparse polish for large ``n``: sequential linear programming (SLP) with HiGHS.

Each iteration linearises every constraint that can become active inside a
box trust region of half-width ``delta`` around the current centres and solves
the sparse LP

    max  sigma
    s.t. -u_ij . (xi_i - xi_j) + 2 sigma <= (d_ij - 2 r) / delta        pairs
          a_k . xi_i          +   sigma <= (b_k - a_k . x_i - r) / delta  half-planes
          v_ik . xi_i         +   sigma <= (R_k - |x_i - c_k| - r) / delta disks
          -1 <= xi <= 1,  0 <= sigma <= sigma_max

for the scaled step ``dX = delta * xi`` and radius increase ``dr = delta *
sigma`` (``u_ij`` and ``v_ik`` are unit vectors). ``r`` is always the
*feasible radius* of the current centres, so ``xi = 0, sigma = 0`` is feasible
and the LP value is never negative. Pair distances are convex in the centres,
so their linearisation is conservative: the true radius after a step is at
least the predicted one except for the (second-order) curvature of disk
walls. A step is accepted iff the exact feasible radius increases; the trust
region grows when the prediction is good and shrinks otherwise.

Only constraints whose slack is smaller than the largest change a step of
size ``delta`` can produce are included, so no contact is ever missed. The LP
has ``2n + 1`` variables and ``O(n)`` rows with at most 5 non-zeros each;
HiGHS solves it in milliseconds for ``n`` in the hundreds.

Near a jammed local optimum the active constraints determine the step and
SLP behaves like Newton's method on them (fast local convergence). Precision
of the last digits is limited by the LP tolerances *relative to delta*, so
the trust region is also shrunk towards the size of the steps actually taken.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csr_array

from .containers import Container
from .energy import feasible_radius
from .neighbors import pairs_within

__all__ = ["polish_slp", "SLPResult", "slp_rows", "RowInfo", "escape_directions"]

_SQRT2 = math.sqrt(2.0)
_HIGHS = {"primal_feasibility_tolerance": 1e-10, "dual_feasibility_tolerance": 1e-10,
          "presolve": True}


@dataclass
class SLPResult:
    X: np.ndarray
    r: float
    iterations: int
    n_active: int
    message: str


@dataclass
class RowInfo:
    kind: np.ndarray   # 0 pair, 1 half-plane, 2 disk
    i: np.ndarray      # circle (first circle of a pair)
    j: np.ndarray      # second circle of a pair, or primitive index
    dist: np.ndarray   # pair distance or distance to the disk centre


def slp_rows(X: np.ndarray, r: float, container: Container, reach: float, curvature: float = 0.0):
    """Sparse LP rows ``(A, b)`` (unscaled: variables ``dX, dr``) for constraints with slack < ``reach``.

    ``curvature`` (= ``delta^2``) makes the disk rows conservative: inside the
    box, ``|x + dx - c| <= |x - c| + v . dx + delta^2 / |x - c|``.

    Returns the CSR matrix over ``2n + 1`` columns, the slack vector and a
    :class:`RowInfo` describing each row.
    """
    n = X.shape[0]
    rows, cols, vals, rhs = [], [], [], []
    meta = []  # (kind, i, j_or_k, distance) per block; kind 0 pair, 1 half-plane, 2 disk
    m = 0
    # pairs
    if n > 1:
        I, J = pairs_within(X, 2.0 * r + reach)
        if I.size:
            D = X[I] - X[J]
            d = np.sqrt(np.einsum("ij,ij->i", D, D))
            U = D / d[:, None]
            k = I.size
            row = m + np.arange(k)
            rows += [row] * 5
            cols += [2 * I, 2 * I + 1, 2 * J, 2 * J + 1, np.full(k, 2 * n)]
            vals += [-U[:, 0], -U[:, 1], U[:, 0], U[:, 1], np.full(k, 2.0)]
            rhs.append(d - 2.0 * r)
            meta.append((np.zeros(k, np.int8), I, J, d))
            m += k
    # half-planes
    if container.n_halfplanes:
        S = container.b[None, :] - X @ container.A.T - r
        hi, hk = np.nonzero(S < reach)
        if hi.size:
            k = hi.size
            row = m + np.arange(k)
            Ak = container.A[hk]
            rows += [row] * 3
            cols += [2 * hi, 2 * hi + 1, np.full(k, 2 * n)]
            vals += [Ak[:, 0], Ak[:, 1], np.ones(k)]
            rhs.append(S[hi, hk])
            meta.append((np.ones(k, np.int8), hi, hk, np.zeros(k)))
            m += k
    # disks
    if container.n_disks:
        Dc = X[:, None, :] - container.C[None, :, :]
        dc = np.linalg.norm(Dc, axis=2)
        S = container.R[None, :] - dc - r
        di, dk = np.nonzero(S < reach)
        if di.size:
            k = di.size
            row = m + np.arange(k)
            V = Dc[di, dk] / np.maximum(dc[di, dk], 1e-300)[:, None]
            rows += [row] * 3
            cols += [2 * di, 2 * di + 1, np.full(k, 2 * n)]
            vals += [V[:, 0], V[:, 1], np.ones(k)]
            rhs.append(S[di, dk] - curvature / dc[di, dk])
            meta.append((np.full(k, 2, np.int8), di, dk, dc[di, dk]))
            m += k
    if m == 0:
        return None, np.zeros(0), None
    A = csr_array((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                  shape=(m, 2 * n + 1))
    info = RowInfo(*(np.concatenate([b[t] for b in meta]) for t in range(4)))
    return A, np.concatenate(rhs), info


def _lp(A, s, delta, n, sigma_max):
    c = np.zeros(2 * n + 1)
    c[-1] = -1.0
    bounds = np.empty((2 * n + 1, 2))
    bounds[:-1] = (-1.0, 1.0)
    bounds[-1] = (-sigma_max, sigma_max)
    return linprog(c, A_ub=A, b_ub=s / delta, bounds=bounds, method="highs", options=_HIGHS)


def _reach(delta: float, sigma_max: float) -> float:
    # largest change of any slack for |dX|_inf <= delta, 0 <= dr <= sigma_max delta
    return (2.0 * _SQRT2 + 2.0 * sigma_max) * delta * 1.0001


def _ascent(X, r, container, delta, delta_max, max_iter, sigma_max, rtol, stall):
    """Plain SLP until no first-order improvement is left. Returns ``(X, r, iterations, message)``."""
    n = X.shape[0]
    msg = "max_iter reached"
    fails = 0
    it = 0
    for it in range(1, max_iter + 1):
        A, s, _ = slp_rows(X, r, container, _reach(delta, sigma_max), delta * delta)
        if A is None:  # nothing within reach: grow
            delta = min(2.0 * delta, delta_max * r)
            continue
        res = _lp(A, s, delta, n, sigma_max)
        if res.status != 0:
            delta *= 0.25
            fails += 1
            if fails > stall or delta < rtol * r:
                msg = f"LP failed: {res.message}"
                break
            continue
        pred = float(res.x[-1]) * delta
        if pred <= rtol * r:
            if container.n_disks and delta > 1e-10 * r:
                delta *= 0.25  # the conservative disk term may be what blocks progress
                continue
            msg = "converged"
            break
        Xn = X + res.x[:-1].reshape(n, 2) * delta
        rn = feasible_radius(Xn, container)
        rho = (rn - r) / pred
        if rn > r:
            X, r = Xn, rn
            fails = 0
        else:
            fails += 1
        # Is the gain limited by the trust region? (non-zero reduced costs on
        # the step bounds, or sigma at its cap)
        box = (float(np.abs(res.lower.marginals[:-1]).sum() + np.abs(res.upper.marginals[:-1]).sum())
               > 1e-9 or res.x[-1] >= sigma_max * (1.0 - 1e-9))
        if rho < 0.25:
            delta *= 0.25
        elif box:
            if rho > 0.75:
                delta = min(2.0 * delta, delta_max * r)
        else:
            # Newton-like regime: the LP optimum is interior. LP tolerances are
            # relative to delta, so shrink it to resolve the last digits.
            delta *= 0.25
        if fails > stall or delta < rtol * r:
            msg = "converged (trust region collapsed)"
            break
    return X, r, it, msg


def escape_directions(X: np.ndarray, r: float, container: Container, k: int = 3,
                      delta: float | None = None, sigma_max: float = 2.0):
    """Second-order ascent directions at a first-order stationary point.

    SLP stops where no *first-order* improvement exists. Because pair
    distances are convex, such a point can still be a saddle: moving along a
    direction ``w`` that keeps every active constraint stationary to first
    order (``J_A w = 0``) increases the pair slacks by ``~ t^2 w^T H w / 2``,
    with ``H`` the Hessian of the Lagrangian built from the LP multipliers.
    Returns up to ``k`` unit directions (rows, shape ``(k, n, 2)``) with
    positive curvature, best first, and the number of active constraints.
    """
    from scipy.linalg import eigh, null_space

    n = X.shape[0]
    delta = delta or 1e-4 * r
    A, s, info = slp_rows(X, r, container, _reach(delta, sigma_max))
    if A is None:
        return np.zeros((0, n, 2)), 0
    res = _lp(A, s, delta, n, sigma_max)
    if res.status != 0:
        return np.zeros((0, n, 2)), 0
    lam = -np.asarray(res.ineqlin.marginals)
    # active: positive multiplier, or touching (degenerate contacts must stay
    # first-order stationary too, so they are treated as equalities)
    act = (lam > 1e-9 * max(float(lam.max()), 1e-300)) | (s < 1e-9 * r)
    if not np.any(act):
        return np.zeros((0, n, 2)), 0
    Ja = A[act][:, :-1].toarray()
    N = null_space(Ja, rcond=1e-10)
    if N.shape[1] == 0:
        return np.zeros((0, n, 2)), int(act.sum())
    # Hessian of sum_k lam_k * slack_k in the centre coordinates
    H = np.zeros((2 * n, 2 * n))
    kind, ii, jj, dist, la = info.kind[act], info.i[act], info.j[act], info.dist[act], lam[act]
    pm = kind == 0
    if np.any(pm):
        I, J, d, w = ii[pm], jj[pm], dist[pm], la[pm]
        U = (X[I] - X[J]) / d[:, None]
        P = (np.eye(2)[None] - U[:, :, None] * U[:, None, :]) * (w / d)[:, None, None]
        for a in range(2):
            for b in range(2):
                np.add.at(H, (2 * I + a, 2 * I + b), P[:, a, b])
                np.add.at(H, (2 * J + a, 2 * J + b), P[:, a, b])
                np.add.at(H, (2 * I + a, 2 * J + b), -P[:, a, b])
                np.add.at(H, (2 * J + a, 2 * I + b), -P[:, a, b])
    dm = kind == 2
    if np.any(dm):
        I, K, dc, w = ii[dm], jj[dm], dist[dm], la[dm]
        V = (X[I] - container.C[K]) / dc[:, None]
        P = (np.eye(2)[None] - V[:, :, None] * V[:, None, :]) * (w / dc)[:, None, None]
        for a in range(2):
            for b in range(2):
                np.add.at(H, (2 * I + a, 2 * I + b), -P[:, a, b])
    M = N.T @ H @ N
    vals, vecs = eigh(0.5 * (M + M.T))
    tol = 1e-6 * max(float(np.abs(vals).max()), 1e-300)
    order = np.argsort(vals)[::-1]
    dirs = [N @ vecs[:, q] for q in order[:k] if vals[q] > tol]
    out = np.array([d_ / np.abs(d_).max() for d_ in dirs]).reshape(-1, n, 2)
    return out, int(act.sum())


def polish_slp(X: np.ndarray, container: Container, *, delta0: float = 0.05,
               delta_max: float = 0.25, max_iter: int = 400, sigma_max: float = 2.0,
               rtol: float = 1e-15, stall: int = 8, escapes: int = 0,
               escape_steps: tuple[float, ...] = (0.05, 0.005)) -> SLPResult:
    """Maximise ``r`` locally from centres ``X`` by sequential sparse LPs.

    Plain SLP (:func:`_ascent`) runs until no first-order improvement is
    left; then up to ``escapes`` times second-order directions
    (:func:`escape_directions`) are tried with step sizes ``escape_steps``
    (relative to ``r``), each followed by SLP; the first one that increases
    the radius is kept. ``delta0`` and ``delta_max`` are relative to ``r``.
    The returned radius is the exact feasible radius of the returned centres
    and is never smaller than that of the input.
    """
    X = np.array(X, dtype=float)
    n = X.shape[0]
    r = feasible_radius(X, container)
    if r <= 0:
        raise ValueError("polish needs centres strictly inside the container and distinct")
    kw = dict(delta_max=delta_max, max_iter=max_iter, sigma_max=sigma_max, rtol=rtol, stall=stall)
    X, r, its, msg = _ascent(X, r, container, delta0 * r, **kw)
    n_active = 0
    for _ in range(escapes):
        dirs, n_active = escape_directions(X, r, container, sigma_max=sigma_max)
        improved = False
        for w in dirs:
            for t in escape_steps:
                for sgn in (1.0, -1.0):
                    Y = X + sgn * t * r * w
                    ry = feasible_radius(Y, container)
                    if ry <= 0:
                        continue
                    Y, ry, k, _ = _ascent(Y, ry, container, t * r, **kw)
                    its += k
                    if ry > r * (1.0 + 4.0 * rtol):
                        X, r, improved = Y, ry, True
                        break
                if improved:
                    break
            if improved:
                break
        if not improved:
            break
        msg = "converged after second-order escape"
    return SLPResult(X, r, its, n_active, msg)
