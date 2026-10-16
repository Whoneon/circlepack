"""Analytic derivatives vs central finite differences."""
import numpy as np
import pytest

from circlepack.containers import circle, quadrant, regular_polygon, semicircle, square, triangle
from circlepack.energy import penalty
from circlepack.neighbors import all_pairs
from circlepack.polish import ActiveSet, constraints, constraints_jac

CONTAINERS = [square(), circle(), quadrant(), semicircle(), regular_polygon(7),
              triangle([0, 0], [2, 0.3], [0.4, 1.5])]


def _fd_jac(f, z, h=1e-6):
    cols = []
    for k in range(z.size):
        e = np.zeros_like(z)
        e[k] = h
        cols.append((f(z + e) - f(z - e)) / (2 * h))
    return np.stack(cols, axis=-1)


def _everything_active(container, n):
    I, J = all_pairs(n)
    hp_i, hp_k = np.meshgrid(np.arange(n), np.arange(container.n_halfplanes), indexing="ij")
    dk_i, dk_k = np.meshgrid(np.arange(n), np.arange(container.n_disks), indexing="ij")
    return ActiveSet(I, J, hp_i.ravel(), hp_k.ravel(), dk_i.ravel(), dk_k.ravel(), r_ref=0.13)


@pytest.mark.parametrize("container", CONTAINERS, ids=lambda c: c.name)
def test_constraint_jacobian_matches_fd(container):
    rng = np.random.default_rng(1)
    n = 6
    X = container.sample(n, rng)
    z = np.concatenate([X.ravel(), [0.11]])
    act = _everything_active(container, n)
    J = constraints_jac(z, container, act)
    Jfd = _fd_jac(lambda zz: constraints(zz, container, act), z)
    assert J.shape == (act.size, 2 * n + 1)
    np.testing.assert_allclose(J, Jfd, atol=1e-8, rtol=1e-6)


@pytest.mark.parametrize("kind", ["pair", "halfplane", "disk"])
def test_each_constraint_type_present(kind):
    c = quadrant()
    act = _everything_active(c, 4)
    sizes = {"pair": act.I.size, "halfplane": act.hp_i.size, "disk": act.dk_i.size}
    assert sizes[kind] > 0


@pytest.mark.parametrize("container", CONTAINERS, ids=lambda c: c.name)
def test_penalty_gradient_matches_fd(container):
    rng = np.random.default_rng(2)
    n = 9
    lo, hi = container.bounding_box()
    # spread some centres outside so every penalty term is active
    X = lo + (rng.random((n, 2)) * 1.3 - 0.15) * (hi - lo)
    r = 0.6 * float(np.max(hi - lo)) / np.sqrt(n)
    I, J = all_pairs(n)

    def E(z):
        return penalty(z[:-1].reshape(n, 2), z[-1], container, I, J)[0]

    z = np.concatenate([X.ravel(), [r]])
    _, gX, gr = penalty(X, r, container, I, J)
    g = np.concatenate([gX.ravel(), [gr]])
    gfd = _fd_jac(lambda zz: np.array([E(zz)]), z)[0]
    assert E(z) > 0
    np.testing.assert_allclose(g, gfd, atol=1e-7, rtol=1e-6)
