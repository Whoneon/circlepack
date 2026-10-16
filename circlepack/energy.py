"""Penalty energy, its analytic gradient and the feasible radius of a configuration.

The global phase minimises, over centres ``X`` and common radius ``r``,

    f(X, r) = -r / s + (mu / n) * E(X, r) / s**2

with ``s`` a length scale (the radius of ``n`` disks filling the container
area), and

    E = sum_{i<j} max(0, 2r - |x_i - x_j|)^2
      + sum_{i, k} max(0, a_k . x_i + r - b_k)^2
      + sum_{i, k} max(0, |x_i - c_k| + r - R_k)^2 .

Small ``mu`` allows large overlaps (soft disks); increasing ``mu`` hardens them.
The first-order condition gives an overlap of order ``s / mu``, so a
geometric ``mu`` schedule up to ~1e9 approaches the rigid optimum, and the
local NLP polish (:mod:`circlepack.polish`) removes the remaining violation.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from .containers import Container

__all__ = ["penalty", "pair_bin_index", "feasible_radius", "pair_slacks", "radius_scale"]

_EPS = 1e-300


def radius_scale(container: Container, n: int) -> float:
    """Radius of ``n`` disks whose total area equals the container area."""
    return float(np.sqrt(container.area() / (n * np.pi)))


def pair_bin_index(I: np.ndarray, J: np.ndarray) -> np.ndarray:
    """Flat gradient indices ``[2I, 2I+1, 2J, 2J+1]`` used to scatter pair forces with one bincount."""
    return np.concatenate([2 * I, 2 * I + 1, 2 * J, 2 * J + 1])


def penalty(X: np.ndarray, r: float, container: Container, I: np.ndarray, J: np.ndarray,
            ix: np.ndarray | None = None):
    """Penalty energy ``E`` and its gradients ``(dE/dX, dE/dr)``.

    ``I, J`` list candidate pairs (a superset of the overlapping ones);
    ``ix = pair_bin_index(I, J)`` may be passed to avoid rebuilding it.
    """
    n = X.shape[0]
    E = 0.0
    gr = 0.0
    g = np.zeros(2 * n)
    # pairs (non-overlapping candidates contribute exact zeros; no masking needed)
    if I.size:
        D = X[I] - X[J]
        d = np.sqrt(D[:, 0] * D[:, 0] + D[:, 1] * D[:, 1])
        v = np.maximum(2.0 * r - d, 0.0)
        E += float(v @ v)
        gr += 4.0 * float(v.sum())
        W = (-2.0 * v / np.maximum(d, _EPS))[:, None] * D
        z = (d == 0) & (v > 0)
        if np.any(z):  # nudge coincident centres apart deterministically
            W[z] = -2.0 * v[z, None] * np.array([1.0, 0.0])
        if ix is None:
            ix = pair_bin_index(I, J)
        g += np.bincount(ix, np.concatenate([W[:, 0], W[:, 1], -W[:, 0], -W[:, 1]]), 2 * n)
    gX = g.reshape(n, 2)
    # half-planes
    if container.n_halfplanes:
        S = X @ container.A.T + (r - container.b)[None, :]
        V = np.maximum(S, 0.0)
        E += float(np.einsum("ij,ij->", V, V))
        gX += 2.0 * V @ container.A
        gr += 2.0 * float(V.sum())
    # disks
    for c, R in zip(container.C, container.R):
        Dc = X - c
        dc = np.sqrt(Dc[:, 0] * Dc[:, 0] + Dc[:, 1] * Dc[:, 1])
        v = np.maximum(dc + r - R, 0.0)
        E += float(v @ v)
        gX += (2.0 * v / np.maximum(dc, _EPS))[:, None] * Dc
        gr += 2.0 * float(v.sum())
    return E, gX, gr


def feasible_radius(X: np.ndarray, container: Container) -> float:
    """Largest common radius for which the centres ``X`` form a valid packing."""
    X = np.asarray(X, dtype=float)
    rc = float(np.min(container.clearance(X)))
    if X.shape[0] < 2:
        return rc
    d, _ = cKDTree(X).query(X, k=2)
    return min(rc, 0.5 * float(np.min(d[:, 1])))


def pair_slacks(X: np.ndarray, r: float, cutoff: float):
    """``(I, J, d - 2r)`` for pairs with ``d < cutoff``."""
    from .neighbors import pairs_within

    I, J = pairs_within(X, cutoff)
    d = np.linalg.norm(X[I] - X[J], axis=1)
    return I, J, d - 2.0 * r
