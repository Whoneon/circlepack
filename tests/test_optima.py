"""Small known optima (proven), constants from closed forms.

Circles in a unit square (Packomania csq): n=2 r=(2-sqrt2)/2; n=3 r=m/(2(1+m)) with
m=sqrt6-sqrt2 (max-min point distance); n=4 r=1/4; n=5 r=(sqrt2-1)/2.
Circles in a unit circle (cci): n=2 r=1/2; n=3 r=2sqrt3-3; n=7 r=1/3.
All agree with the Packomania tables (checked below when they are in the local cache).
"""
import math

import pytest

from circlepack.containers import circle, square
from circlepack.parallel import run_many
from circlepack.records import known_radius
from circlepack.search import SearchConfig

_m3 = math.sqrt(6) - math.sqrt(2)
CASES = [
    ("square", 2, (2 - math.sqrt(2)) / 2),
    ("square", 3, _m3 / (2 * (1 + _m3))),
    ("square", 4, 0.25),
    ("square", 5, (math.sqrt(2) - 1) / 2),
    ("circle", 2, 0.5),
    ("circle", 3, 2 * math.sqrt(3) - 3),
    ("circle", 7, 1 / 3),
]
FACTORY = {"square": square, "circle": circle}


@pytest.mark.records("square", "circle")
@pytest.mark.parametrize("name, n, r", CASES)
def test_constant_matches_packomania_table(name, n, r):
    assert known_radius(name, n) == pytest.approx(r, abs=6e-13)


@pytest.mark.parametrize("name, n, r", CASES)
def test_reproduce_small_optimum(name, n, r):
    res = run_many(FACTORY[name](), n, starts=4, workers=1, cfg=SearchConfig(hops=6), seed=0)
    assert res.best.r == pytest.approx(r, abs=1e-12)
    assert res.best.r <= r + 1e-15  # never claims more than the optimum
