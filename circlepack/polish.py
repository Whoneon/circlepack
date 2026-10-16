"""Local polish: constrained NLP ``max r`` over ``(X, r)`` with analytic Jacobians.

Only *near-active* constraints are passed to the solver (pairs closer than
``2 r (1 + margin)``, walls closer than ``r * margin``). After each solve the
exact feasible radius of the centres is recomputed, the active set is rebuilt
and the solve is repeated until the set is stable.

All constraints are written as ``g(z) >= 0`` with ``z = (x_1, y_1, ..., x_n, y_n, r)``:

* pair ``(i, j)``:   ``(|x_i - x_j|^2 - 4 r^2) / (4 r_ref)``   (smooth, ~ ``d - 2r``)
* half-plane ``k``:  ``b_k - a_k . x_i - r``
* disk ``k``:        ``((R_k - r)^2 - |x_i - c_k|^2) / (2 R_k)``  (smooth, ~ ``R - r - |x - c|``)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from .containers import Container
from .energy import feasible_radius
from .neighbors import pairs_within

__all__ = ["ActiveSet", "active_set", "constraints", "constraints_jac", "constraints_jac_sparse",
           "constraints_hess_sparse", "polish", "PolishResult", "POLISH_METHODS", "AUTO_SPARSE_N"]

#: ``method="auto"`` uses dense SLSQP up to this ``n`` and the sparse path above it.
AUTO_SPARSE_N = 60
POLISH_METHODS = ("auto", "SLSQP", "trust-constr", "sparse", "slp")


@dataclass
class ActiveSet:
    I: np.ndarray        # pair first index
    J: np.ndarray        # pair second index
    hp_i: np.ndarray     # circle index of half-plane constraints
    hp_k: np.ndarray     # half-plane index
    dk_i: np.ndarray     # circle index of disk constraints
    dk_k: np.ndarray     # disk index
    r_ref: float

    @property
    def size(self) -> int:
        return self.I.size + self.hp_i.size + self.dk_i.size


def active_set(X: np.ndarray, r: float, container: Container, margin: float = 0.25) -> ActiveSet:
    I, J = pairs_within(X, 2.0 * r * (1.0 + margin))
    if container.n_halfplanes:
        S = container.b[None, :] - X @ container.A.T - r
        hp_i, hp_k = np.nonzero(S < margin * r)
    else:
        hp_i = hp_k = np.zeros(0, np.intp)
    if container.n_disks:
        D = np.linalg.norm(X[:, None, :] - container.C[None, :, :], axis=2)
        S = container.R[None, :] - D - r
        dk_i, dk_k = np.nonzero(S < margin * r)
    else:
        dk_i = dk_k = np.zeros(0, np.intp)
    return ActiveSet(I, J, hp_i, hp_k, dk_i, dk_k, float(r))


def constraints(z: np.ndarray, container: Container, act: ActiveSet) -> np.ndarray:
    n = (z.size - 1) // 2
    X = z[:-1].reshape(n, 2)
    r = z[-1]
    D = X[act.I] - X[act.J]
    g_pair = (np.einsum("ij,ij->i", D, D) - 4.0 * r * r) / (4.0 * act.r_ref)
    g_hp = container.b[act.hp_k] - np.einsum("ij,ij->i", container.A[act.hp_k], X[act.hp_i]) - r
    Dc = X[act.dk_i] - container.C[act.dk_k]
    Rk = container.R[act.dk_k]
    g_dk = ((Rk - r) ** 2 - np.einsum("ij,ij->i", Dc, Dc)) / (2.0 * Rk)
    return np.concatenate([g_pair, g_hp, g_dk])


def constraints_jac(z: np.ndarray, container: Container, act: ActiveSet) -> np.ndarray:
    n = (z.size - 1) // 2
    X = z[:-1].reshape(n, 2)
    r = z[-1]
    m1, m2, m3 = act.I.size, act.hp_i.size, act.dk_i.size
    Jm = np.zeros((m1 + m2 + m3, 2 * n + 1))
    # pairs
    rows = np.arange(m1)
    D = (X[act.I] - X[act.J]) * (2.0 / (4.0 * act.r_ref))
    Jm[rows, 2 * act.I] = D[:, 0]
    Jm[rows, 2 * act.I + 1] = D[:, 1]
    Jm[rows, 2 * act.J] = -D[:, 0]
    Jm[rows, 2 * act.J + 1] = -D[:, 1]
    Jm[rows, -1] = -8.0 * r / (4.0 * act.r_ref)
    # half-planes
    rows = m1 + np.arange(m2)
    Ak = container.A[act.hp_k]
    Jm[rows, 2 * act.hp_i] = -Ak[:, 0]
    Jm[rows, 2 * act.hp_i + 1] = -Ak[:, 1]
    Jm[rows, -1] = -1.0
    # disks
    rows = m1 + m2 + np.arange(m3)
    Rk = container.R[act.dk_k]
    Dc = (X[act.dk_i] - container.C[act.dk_k]) * (-2.0 / (2.0 * Rk))[:, None]
    Jm[rows, 2 * act.dk_i] = Dc[:, 0]
    Jm[rows, 2 * act.dk_i + 1] = Dc[:, 1]
    Jm[rows, -1] = -2.0 * (Rk - r) / (2.0 * Rk)
    return Jm


def _jac_triplets(z: np.ndarray, container: Container, act: ActiveSet):
    n = (z.size - 1) // 2
    X = z[:-1].reshape(n, 2)
    r = z[-1]
    m1, m2, m3 = act.I.size, act.hp_i.size, act.dk_i.size
    rows, cols, vals = [], [], []
    rr = np.arange(m1)
    D = (X[act.I] - X[act.J]) * (2.0 / (4.0 * act.r_ref))
    rows += [rr] * 5
    cols += [2 * act.I, 2 * act.I + 1, 2 * act.J, 2 * act.J + 1, np.full(m1, 2 * n)]
    vals += [D[:, 0], D[:, 1], -D[:, 0], -D[:, 1], np.full(m1, -8.0 * r / (4.0 * act.r_ref))]
    rr = m1 + np.arange(m2)
    Ak = container.A[act.hp_k]
    rows += [rr] * 3
    cols += [2 * act.hp_i, 2 * act.hp_i + 1, np.full(m2, 2 * n)]
    vals += [-Ak[:, 0], -Ak[:, 1], np.full(m2, -1.0)]
    rr = m1 + m2 + np.arange(m3)
    Rk = container.R[act.dk_k]
    Dc = (X[act.dk_i] - container.C[act.dk_k]) * (-1.0 / Rk)[:, None]
    rows += [rr] * 3
    cols += [2 * act.dk_i, 2 * act.dk_i + 1, np.full(m3, 2 * n)]
    vals += [Dc[:, 0], Dc[:, 1], -(Rk - r) / Rk]
    return (np.concatenate(rows), np.concatenate(cols), np.concatenate(vals)), (m1 + m2 + m3, 2 * n + 1)


def constraints_jac_sparse(z: np.ndarray, container: Container, act: ActiveSet):
    """Same as :func:`constraints_jac` as a ``scipy.sparse`` CSR matrix (<= 5 non-zeros per row)."""
    from scipy.sparse import csr_matrix

    (rows, cols, vals), shape = _jac_triplets(z, container, act)
    return csr_matrix((vals, (rows, cols)), shape=shape)


def constraints_hess_sparse(z: np.ndarray, v: np.ndarray, container: Container, act: ActiveSet):
    """``sum_k v_k * Hessian(g_k)`` (constant blocks), as a sparse CSR matrix.

    pair ``(i, j)``: ``(1 / (2 r_ref)) [[I, -I], [-I, I]]`` on ``(x_i, x_j)`` and
    ``-2 / r_ref`` on ``r``; half-planes: 0; disk ``k``: ``-I / R_k`` on ``x_i``
    and ``1 / R_k`` on ``r``.
    """
    from scipy.sparse import csr_matrix

    n = (z.size - 1) // 2
    m1, m2 = act.I.size, act.hp_i.size
    vp = v[:m1] / (2.0 * act.r_ref)
    vd = v[m1 + m2:] / container.R[act.dk_k]
    rows, cols, vals = [], [], []
    for k in range(2):
        a, b = 2 * act.I + k, 2 * act.J + k
        rows += [a, b, a, b]
        cols += [a, b, b, a]
        vals += [vp, vp, -vp, -vp]
        c = 2 * act.dk_i + k
        rows.append(c)
        cols.append(c)
        vals.append(-vd)
    hr = -2.0 / act.r_ref * float(v[:m1].sum()) + float(vd.sum())
    rows.append(np.array([2 * n]))
    cols.append(np.array([2 * n]))
    vals.append(np.array([hr]))
    return csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                      shape=(2 * n + 1, 2 * n + 1))


@dataclass
class PolishResult:
    X: np.ndarray
    r: float
    rounds: int
    n_active: int
    message: str
    method: str = ""


def polish(X: np.ndarray, container: Container, *, margin: float = 0.25,
           max_rounds: int = 6, maxiter: int = 500, ftol: float = 1e-16,
           method: str = "SLSQP") -> PolishResult:
    """Maximise ``r`` locally starting from centres ``X``.

    ``method``: ``"SLSQP"`` (dense, exact to ~1e-15, best for small n),
    ``"slp"``/``"sparse"`` (sparse sequential LP with HiGHS, see
    :mod:`circlepack.slp`), ``"trust-constr"`` (sparse Jacobian and exact
    Hessian; slow, kept for reference) or ``"auto"`` (SLSQP for
    ``n <= AUTO_SPARSE_N``, SLP above).

    The returned ``r`` is :func:`feasible_radius` of the returned centres, so
    the result is feasible up to floating-point rounding regardless of how
    well the NLP converged. The polish never returns a worse packing than its
    input.
    """
    X = np.array(X, dtype=float)
    n = X.shape[0]
    if method == "auto":
        method = "SLSQP" if n <= AUTO_SPARSE_N else "slp"
    if method in ("slp", "sparse"):
        from .slp import polish_slp

        res = polish_slp(X, container)
        return PolishResult(res.X, res.r, res.iterations, res.n_active, res.message, "slp")
    if method not in ("SLSQP", "trust-constr"):
        raise ValueError(f"unknown polish method {method!r}; choose from {POLISH_METHODS}")
    best_X = X.copy()
    best_r = feasible_radius(X, container)
    if best_r <= 0:
        raise ValueError("polish needs centres strictly inside the container and distinct")
    z = np.concatenate([X.ravel(), [best_r]])
    msg = ""
    prev_key = None
    rounds = 0
    act = active_set(X, best_r, container, margin)
    for rounds in range(1, max_rounds + 1):
        act = active_set(best_X, best_r, container, margin)
        key = (act.I.tobytes(), act.J.tobytes(), act.hp_i.tobytes(), act.hp_k.tobytes(),
               act.dk_i.tobytes(), act.dk_k.tobytes())
        cons = {"type": "ineq",
                "fun": constraints, "jac": constraints_jac, "args": (container, act)}
        obj_g = np.zeros(2 * n + 1)
        obj_g[-1] = -1.0
        if method == "SLSQP":
            res = minimize(lambda z: -z[-1], z, jac=lambda z: obj_g, method="SLSQP",
                           constraints=[cons], options={"maxiter": maxiter, "ftol": ftol})
        elif method == "trust-constr":
            from scipy.optimize import NonlinearConstraint
            from scipy.sparse import csr_matrix
            nlc = NonlinearConstraint(lambda z: constraints(z, container, act), 0.0, np.inf,
                                      jac=lambda z: constraints_jac_sparse(z, container, act),
                                      hess=lambda z, v: constraints_hess_sparse(z, v, container, act))
            H0 = csr_matrix((2 * n + 1, 2 * n + 1))
            res = minimize(lambda z: -z[-1], z, jac=lambda z: obj_g, hess=lambda z: H0,
                           method="trust-constr", constraints=[nlc],
                           options={"maxiter": maxiter * 4, "gtol": 1e-14, "xtol": 1e-16})
        else:
            raise ValueError(f"unknown polish method {method!r}")
        msg = str(res.message)
        Xn = res.x[:-1].reshape(n, 2)
        rn = feasible_radius(Xn, container)
        if rn > best_r:
            best_r, best_X = rn, Xn.copy()
        z = np.concatenate([best_X.ravel(), [best_r]])
        if key == prev_key:
            break
        prev_key = key
    return PolishResult(best_X, best_r, rounds, act.size, msg, method)
