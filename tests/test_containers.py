import math

import numpy as np
import pytest

from circlepack.containers import (Container, circle, make_container, polygon, quadrant,
                                   rectangle, regular_polygon, right_isosceles_triangle,
                                   semicircle, square, triangle)
from circlepack.records import has_table, known_radius


@pytest.mark.parametrize("name, container, r1", [
    ("square", square(), 0.5),
    ("circle", circle(), 1.0),
    ("right_triangle", right_isosceles_triangle(), (2 - math.sqrt(2)) / 2),
    ("quadrant", quadrant(), math.sqrt(2) - 1),
    ("semicircle", semicircle(), 0.5),
    ("pentagon", regular_polygon(5), math.cos(math.pi / 5)),
    ("hexagon", regular_polygon(6), math.cos(math.pi / 6)),
    ("rectangle_0.5", rectangle(1, 0.5), 0.25),
])
def test_normalisation_matches_packomania_n1(request, name, container, r1):
    """n = 1 optimum is the inradius (closed form); it must match the Packomania table if cached."""
    assert container.inradius() == pytest.approx(r1, abs=1e-9)
    if not has_table(name):
        pytest.skip(f"record table {name} not cached (closed-form part passed); "
                    f"run `circlepack records fetch --tables {name}`")
    assert known_radius(name, 1) == pytest.approx(r1, abs=1e-11)


def test_clearance_square():
    c = square()
    assert c.clearance(np.array([[0.0, 0.0], [0.4, 0.0], [0.6, 0.0]])) == pytest.approx([0.5, 0.1, -0.1])


def test_clearance_quadrant_mixes_halfplanes_and_disk():
    c = quadrant()
    x = np.array([[0.5, 0.5]])
    assert c.clearance(x)[0] == pytest.approx(min(0.5, 1 - math.sqrt(0.5)))


def test_polygon_orientation_and_convexity():
    sq_cw = polygon([[0, 0], [0, 1], [1, 1], [1, 0]])
    assert np.all(sq_cw.contains(np.array([[0.5, 0.5]])))
    with pytest.raises(ValueError):
        polygon([[0, 0], [2, 0], [1, 0.2], [1, 2]])  # reflex vertex


def test_triangle_area_and_bbox():
    t = triangle([0, 0], [2, 0], [0, 1])
    assert t.area() == pytest.approx(1.0)
    lo, hi = t.bounding_box()
    np.testing.assert_allclose(lo, [0, 0], atol=1e-12)
    np.testing.assert_allclose(hi, [2, 1], atol=1e-12)


def test_roundtrip_dict():
    for c in [square(), circle(2.0), quadrant(), semicircle(), regular_polygon(9),
              rectangle(1, 0.3), triangle([0, 0], [1, 0], [0.2, 0.9])]:
        d = c.to_dict()
        c2 = Container.from_dict(d)
        np.testing.assert_allclose(c2.A, c.A)
        np.testing.assert_allclose(c2.b, c.b)
        np.testing.assert_allclose(c2.R, c.R)


def test_custom_container_from_primitives():
    d = {"halfplanes": [[0, -2, 0]], "disks": [[0, 0, 1], [0.5, 0, 1]]}  # lens cut in half
    c = Container.from_dict(d)
    assert c.n_disks == 2 and np.allclose(c.A, [[0, -1]])
    assert c.contains(np.array([[0.25, 0.1]]))[0]


def test_make_container_short_names():
    assert make_container("pentagon").n_halfplanes == 5
    assert make_container("right_triangle").n_halfplanes == 3
    with pytest.raises(ValueError):
        make_container("dodecahedron")
