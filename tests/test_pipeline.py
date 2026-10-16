import numpy as np
import pytest

from circlepack.cli import main as cli_main
from circlepack.containers import circle, quadrant, square
from circlepack.energy import feasible_radius, penalty
from circlepack.neighbors import NeighborList, all_pairs
from circlepack.parallel import run_many
from circlepack.polish import polish
from circlepack.records import known_radius
from circlepack.search import SearchConfig, perturb_relocate, run_start


def test_verlet_list_energy_equals_all_pairs():
    rng = np.random.default_rng(0)
    c = square()
    n = 150
    X = c.sample(n, rng)
    r = 0.05
    nl = NeighborList(n)
    I0, J0 = all_pairs(n)
    for _ in range(25):
        I, J = nl.get(X, r)
        assert penalty(X, r, c, I, J)[0] == pytest.approx(penalty(X, r, c, I0, J0)[0], rel=1e-13)
        X = X + rng.normal(scale=0.01, size=X.shape)
        r *= 1.02
    assert 1 < nl.rebuilds < 25


def test_polish_never_worse_and_feasible():
    c = quadrant()
    rng = np.random.default_rng(3)
    X = c.sample(8, rng, margin=0.05)
    r0 = feasible_radius(X, c)
    res = polish(X, c)
    assert res.r >= r0
    assert res.r == pytest.approx(feasible_radius(res.X, c))


def test_relocate_moves_into_container():
    c = square()
    rng = np.random.default_rng(0)
    X = c.sample(20, rng)
    Y = perturb_relocate(X, 0.05, c, rng, 2)
    assert np.all(c.clearance(Y) >= 0)
    assert np.sum(np.any(X != Y, axis=1)) <= 2


@pytest.mark.slow
def test_parallel_matches_serial():
    cfg = SearchConfig(hops=3)
    a = run_many(square(), 6, starts=2, workers=1, cfg=cfg)
    b = run_many(square(), 6, starts=2, workers=2, cfg=cfg)
    assert sorted(r.r for r in a.results) == pytest.approx(sorted(r.r for r in b.results), abs=1e-14)


@pytest.mark.parametrize("name, factory, n", [
    pytest.param("circle", circle, 10, marks=pytest.mark.records("circle")),
    pytest.param("square", square, 9, marks=pytest.mark.records("square")),
    pytest.param("quadrant", quadrant, 6, marks=pytest.mark.records("quadrant")),
])
def test_known_records_moderate_n(name, factory, n):
    rec = known_radius(name, n)
    best = max(run_start(factory(), n, s, SearchConfig(hops=10)).r for s in range(3))
    assert best == pytest.approx(rec, abs=1e-12)


def test_cli_run_and_verify(tmp_path, capsys):
    out = tmp_path / "q5.json"
    assert cli_main(["run", "--container", "quadrant", "--n", "5", "--starts", "2", "--workers", "1",
                     "--hops", "4", "--nice", "0", "--quiet", "--out", str(out)]) == 0
    assert out.exists()
    assert cli_main(["verify", str(out), "--exact"]) == 0
    text = capsys.readouterr().out
    assert "VALID" in text and "INVALID" not in text


def test_lattice_start_fits_and_has_n_points():
    from circlepack.containers import right_isosceles_triangle
    from circlepack.search import lattice_start

    rng = np.random.default_rng(0)
    for c in (right_isosceles_triangle(), quadrant(), square(), circle()):
        for _ in range(5):
            X, r = lattice_start(c, 15, rng)
            assert X.shape == (15, 2) and r > 0
            assert feasible_radius(X, c) >= r * (1 - 1e-9)
