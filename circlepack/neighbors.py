"""Neighbour lists for the pair terms.

For small ``n`` all pairs are used. For larger ``n`` a Verlet list is built
with a k-d tree (a C-implemented spatial grid, :class:`scipy.spatial.cKDTree`)
using cutoff ``2 r + skin`` and rebuilt only when some centre has moved far
enough that a pair outside the list could have come into contact. The list is
therefore *exact*: the energy computed with it equals the all-pairs energy.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

__all__ = ["NeighborList", "all_pairs", "pairs_within"]

DENSE_MAX_N = 64


def _bin_index(I: np.ndarray, J: np.ndarray) -> np.ndarray:
    return np.concatenate([2 * I, 2 * I + 1, 2 * J, 2 * J + 1])


def all_pairs(n: int) -> tuple[np.ndarray, np.ndarray]:
    I, J = np.triu_indices(n, k=1)
    return I.astype(np.intp), J.astype(np.intp)


def pairs_within(X: np.ndarray, cutoff: float) -> tuple[np.ndarray, np.ndarray]:
    """Index arrays ``(I, J)``, ``I < J``, of all pairs closer than ``cutoff``."""
    n = X.shape[0]
    if n <= DENSE_MAX_N:
        I, J = all_pairs(n)
        d = np.linalg.norm(X[I] - X[J], axis=1)
        keep = d < cutoff
        return I[keep], J[keep]
    P = cKDTree(X).query_pairs(cutoff, output_type="ndarray")
    if P.size == 0:
        return np.zeros(0, np.intp), np.zeros(0, np.intp)
    return P[:, 0].astype(np.intp), P[:, 1].astype(np.intp)


class NeighborList:
    """Verlet list with automatic rebuild.

    Parameters
    ----------
    n : number of circles.
    skin : extra cutoff relative to the current radius (``skin * r``).
    """

    def __init__(self, n: int, skin: float = 0.6):
        self.n = n
        self.skin = skin
        self.dense = n <= DENSE_MAX_N
        self._ref: np.ndarray | None = None
        self._cut = 0.0
        self.I, self.J = all_pairs(n) if self.dense else (np.zeros(0, np.intp),) * 2
        self.ix = _bin_index(self.I, self.J)
        self.rebuilds = 0

    def reset(self) -> None:
        self._ref = None

    def get(self, X: np.ndarray, r: float) -> tuple[np.ndarray, np.ndarray]:
        if self.dense:
            return self.I, self.J
        r = abs(float(r))
        if self._ref is not None:
            disp = np.sqrt(np.max(np.sum((X - self._ref) ** 2, axis=1)))
            if 2.0 * disp < self._cut - 2.0 * r:
                return self.I, self.J
        self._cut = 2.0 * r * (1.0 + self.skin)
        self._ref = X.copy()
        self.I, self.J = pairs_within(X, self._cut)
        self.ix = _bin_index(self.I, self.J)
        self.rebuilds += 1
        return self.I, self.J
