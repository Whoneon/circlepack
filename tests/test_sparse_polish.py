"""Sparse polish path: sparse Jacobian/Hessian, SLP rows, convergence to known optima."""
import math

import numpy as np
import pytest

from circlepack.containers import circle, quadrant, regular_polygon, semicircle, square, triangle
from circlepack.energy import feasible_radius
from circlepack.neighbors import all_pairs
from circlepack.parallel import run_many
from circlepack.polish import (AUTO_SPARSE_N, ActiveSet, constraints, constraints_hess_sparse,
                               constraints_jac, constraints_jac_sparse, polish)
from circlepack.search import SearchConfig
from circlepack.slp import escape_directions, polish_slp, slp_rows

CONTAINERS = [square(), circle(), quadrant(), semicircle(), regular_polygon(7),
              triangle([0, 0], [2, 0.3], [0.4, 1.5])]


def _everything_active(container, n):
    I, J = all_pairs(n)
    hp_i, hp_k = np.meshgrid(np.arange(n), np.arange(container.n_halfplanes), indexing="ij")
    dk_i, dk_k = np.meshgrid(np.arange(n), np.arange(container.n_disks), indexing="ij")
    return ActiveSet(I, J, hp_i.ravel(), hp_k.ravel(), dk_i.ravel(), dk_k.ravel(), r_ref=0.13)


@pytest.mark.parametrize("container", CONTAINERS, ids=lambda c: c.name)
def test_sparse_jacobian_matches_dense_values_and_pattern(container):
    rng = np.random.default_rng(4)
    n = 7
    z = np.concatenate([container.sample(n, rng).ravel(), [0.09]])
    act = _everything_active(container, n)
    Jd = constraints_jac(z, container, act)
    Js = constraints_jac_sparse(z, container, act)
    assert Js.shape == Jd.shape
    np.testing.assert_array_equal(Js.toarray(), Jd)
    # structural pattern: <= 5 non-zeros per pair row, <= 3 per wall row, r column always present
    nnz = np.diff(Js.indptr)
    assert np.all(nnz[:act.I.size] <= 5) and np.all(nnz[act.I.size:] <= 3)
    assert set(zip(*np.nonzero(Jd))) == set(zip(*Js.nonzero()))


@pytest.mark.parametrize("container", CONTAINERS, ids=lambda c: c.name)
def test_sparse_hessian_matches_fd_of_jacobian(container):
    rng = np.random.default_rng(5)
    n = 5
    z = np.concatenate([container.sample(n, rng).ravel(), [0.08]])
    act = _everything_active(container, n)
    v = rng.random(act.size)
    H = constraints_hess_sparse(z, v, container, act).toarray()
    h = 1e-6
    Hfd = np.stack([(v @ constraints_jac(z + h * e, container, act) - v @ constraints_jac(z - h * e, container, act))
                    / (2 * h) for e in np.eye(z.size)], axis=1)
    np.testing.assert_allclose(H, Hfd, atol=1e-6)
    np.testing.assert_allclose(H, H.T)


@pytest.mark.parametrize("container", CONTAINERS, ids=lambda c: c.name)
def test_slp_rows_are_first_order_and_conservative(container):
    rng = np.random.default_rng(6)
    n = 12
    X = container.sample(n, rng, margin=0.02)
    r = feasible_radius(X, container)
    delta = 0.05 * r
    A, s, info = slp_rows(X, r, container, reach=10.0, curvature=delta ** 2)
    assert A.shape[1] == 2 * n + 1 and A.shape[0] == s.size == info.kind.size
    assert np.all(np.diff(A.indptr) <= 5)
    for _ in range(20):
        step = rng.uniform(-delta, delta, size=2 * n)
        dr = rng.uniform(-delta, delta)
        Y = X + step.reshape(n, 2)
        # exact slack of each row after the step
        exact = np.empty(s.size)
        for q in range(s.size):
            k, i, j = info.kind[q], info.i[q], info.j[q]
            if k == 0:
                exact[q] = np.linalg.norm(Y[i] - Y[j]) - 2 * (r + dr)
            elif k == 1:
                exact[q] = container.b[j] - container.A[j] @ Y[i] - (r + dr)
            else:
                exact[q] = container.R[j] - np.linalg.norm(Y[i] - container.C[j]) - (r + dr)
        linear = s - A @ np.concatenate([step, [dr]])
        assert np.all(exact >= linear - 1e-13)          # conservative
        assert np.max(exact - linear) < 4 * delta ** 2 / r  # and first-order accurate


def _hex7():
    a = np.linspace(0, 2 * np.pi, 7)[:-1]
    return np.vstack([[0, 0], (2 / 3) * np.stack([np.cos(a), np.sin(a)], 1)])


@pytest.mark.parametrize("container, X, r_opt", [
    (square(), np.array([[-.25, -.25], [.25, -.25], [-.25, .25], [.25, .25]]), 0.25),
    (circle(), _hex7(), 1 / 3),
    (square(), np.array([[-.3, -.3], [.3, -.3], [-.3, .3], [.3, .3], [0, 0]]), (math.sqrt(2) - 1) / 2),
])
def test_slp_converges_to_known_optimum(container, X, r_opt):
    rng = np.random.default_rng(7)
    Y = X + rng.normal(scale=0.01, size=X.shape)
    res = polish_slp(Y, container)
    assert res.r == pytest.approx(r_opt, abs=1e-12)
    assert res.r <= r_opt + 1e-15
    assert res.r == feasible_radius(res.X, container)


@pytest.mark.parametrize("container", [square(), circle(), quadrant()], ids=lambda c: c.name)
def test_slp_matches_slsqp_on_small_random_starts(container):
    rng = np.random.default_rng(8)
    for _ in range(3):
        X = container.sample(9, rng, margin=0.05)
        a = polish(X, container, method="SLSQP")
        b = polish(X, container, method="slp")
        assert b.r >= feasible_radius(X, container)
        # same local optimum, or SLP strictly better (SLSQP occasionally stalls)
        assert b.r >= a.r - 1e-12


def test_auto_switches_to_sparse_above_threshold():
    rng = np.random.default_rng(9)
    c = square()
    X = c.sample(AUTO_SPARSE_N + 1, rng, margin=0.02)
    res = polish(X, c, method="auto")
    assert res.method == "slp"
    small = polish(c.sample(8, rng, margin=0.05), c, method="auto")
    assert small.method == "SLSQP"
    with pytest.raises(ValueError):
        polish(X, c, method="newton")


def test_escape_at_strict_optimum_keeps_it():
    c = square()
    X = np.array([[-.25, -.25], [.25, -.25], [-.25, .25], [.25, .25]])
    dirs, n_act = escape_directions(X, 0.25, c)
    assert n_act >= 8  # 4 pair + 8 wall contacts, rigid
    assert polish_slp(X, c, escapes=2).r == 0.25


@pytest.mark.parametrize("name, factory, n, r", [
    ("square", square, 5, (math.sqrt(2) - 1) / 2),
    ("circle", circle, 7, 1 / 3),
])
def test_pipeline_with_sparse_polish_reproduces_optimum(name, factory, n, r):
    res = run_many(factory(), n, starts=3, workers=1, cfg=SearchConfig(hops=4, polish_method="slp"))
    assert res.best.r == pytest.approx(r, abs=1e-12)
