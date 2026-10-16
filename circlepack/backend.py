"""Global-phase backends.

A backend implements :meth:`Backend.relax`: given a *batch* of starting
configurations it runs the soft-to-rigid penalty continuation and returns the
relaxed centres and radii. Everything else in the pipeline (basin hopping,
polishing, verification) is backend-agnostic, so a GPU implementation that
treats many starts as one tensor ``(B, n, 2)`` only needs to provide this one
method. See the README ("Backend seam").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np
from scipy.optimize import minimize

from .containers import Container
from .energy import penalty
from .neighbors import NeighborList

__all__ = ["Backend", "NumpyBackend", "default_schedule", "get_backend"]


def default_schedule(mu0: float = 0.5, mu1: float = 1e10, factor: float = 4.0) -> np.ndarray:
    """Geometric penalty schedule (softest first)."""
    k = int(np.ceil(np.log(mu1 / mu0) / np.log(factor)))
    return mu0 * factor ** np.arange(k + 1)


class Backend(Protocol):
    name: str

    def relax(self, container: Container, X: np.ndarray, r: np.ndarray, scale: float,
              mus: Sequence[float], r_floor: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Relax a batch.

        Parameters
        ----------
        X : (B, n, 2) starting centres.
        r : (B,) starting radii.
        scale : length scale ``s`` used to non-dimensionalise the objective.
        mus : penalty weights, applied in order (warm-started).
        r_floor : optional (B,) radii. The penalty radius decreases (almost
            monotonically) along the schedule, so a start whose radius drops
            below its floor cannot end above it: it is abandoned early and
            returned as is (the caller recomputes the feasible radius).

        Returns
        -------
        (X, r) with the same shapes.
        """
        ...


@dataclass
class NumpyBackend:
    """Reference CPU backend: SciPy L-BFGS-B on each start of the batch."""

    maxiter: int = 3000
    gtol: float = 1e-12
    ftol: float = 1e-12            # intermediate stages
    ftol_final: float = 1e-15      # last two stages
    floor_mu: float = 1e4          # r_floor is only enforced once mu >= floor_mu
    name: str = "numpy"

    def relax(self, container, X, r, scale, mus, r_floor=None):
        X = np.asarray(X, dtype=float)
        r = np.asarray(r, dtype=float)
        outX = np.empty_like(X)
        outr = np.empty_like(r)
        for b in range(X.shape[0]):
            fl = None if r_floor is None else float(r_floor[b])
            outX[b], outr[b] = self.relax_one(container, X[b], float(r[b]), scale, mus, fl)
        return outX, outr

    def relax_one(self, container: Container, X: np.ndarray, r: float, scale: float,
                  mus: Sequence[float], r_floor: float | None = None) -> tuple[np.ndarray, float]:
        n = X.shape[0]
        nl = NeighborList(n)
        s = float(scale)
        z = np.concatenate([X.ravel() / s, [r / s]])
        bounds = [(None, None)] * (2 * n) + [(0.0, None)]
        last = len(mus) - 2
        for stage, mu in enumerate(mus):
            w = mu / n

            def fun(z, w=w):
                Xs = z[:-1].reshape(n, 2) * s
                rr = z[-1] * s
                I, J = nl.get(Xs, rr)
                E, gX, gr = penalty(Xs, rr, container, I, J, nl.ix)
                f = -z[-1] + w * E / (s * s)
                g = np.empty_like(z)
                g[:-1] = (w / s) * gX.ravel()
                g[-1] = -1.0 + (w / s) * gr
                return f, g

            res = minimize(fun, z, jac=True, method="L-BFGS-B", bounds=bounds,
                           options={"maxiter": self.maxiter, "gtol": self.gtol,
                                    "ftol": self.ftol_final if stage >= last else self.ftol,
                                    "maxcor": 20})
            z = res.x
            if r_floor is not None and mu >= self.floor_mu and z[-1] * s < r_floor:
                break
        return z[:-1].reshape(n, 2) * s, float(z[-1] * s)


_BACKENDS = {"numpy": NumpyBackend}


def get_backend(name: str = "numpy", **kw) -> Backend:
    try:
        return _BACKENDS[name](**kw)
    except KeyError:
        raise ValueError(f"unknown backend {name!r}; available: {sorted(_BACKENDS)}") from None
