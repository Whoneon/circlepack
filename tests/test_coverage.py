"""Container constructors, verifier edge cases, CLI smoke tests, JSON round-trips."""
import json
import math
from fractions import Fraction

import numpy as np
import pytest

from circlepack.cli import main as cli_main
from circlepack.cli import record_key
from circlepack.containers import (CONTAINER_NAMES, PACKOMANIA, Container, circle, make_container,
                                   polygon, quadrant, rectangle, regular_polygon,
                                   right_isosceles_triangle, semicircle, square, triangle)
from circlepack.records import available, known_radius, load_records
from circlepack.solution import load_solution, save_solution
from circlepack.verify import exact_primitives, verify, verify_exact


# ------------------------------------------------------------------ containers
@pytest.mark.parametrize("k", range(3, 18))
def test_regular_polygon_geometry(k):
    c = regular_polygon(k)
    assert c.n_halfplanes == k and c.n_disks == 0
    np.testing.assert_allclose(np.linalg.norm(c.A, axis=1), 1.0)
    np.testing.assert_allclose(c.b, math.cos(math.pi / k), rtol=1e-14)    # inradius
    assert c.area() == pytest.approx(0.5 * k * math.sin(2 * math.pi / k), rel=1e-12)
    t = -math.pi / 2 - math.pi / k + 2 * math.pi * np.arange(k) / k
    V = np.stack([np.cos(t), np.sin(t)], 1)
    assert np.all(np.abs(c.clearance(V)) < 1e-12)                          # vertices on the boundary
    assert c.inradius() == pytest.approx(math.cos(math.pi / k), abs=1e-9)
    lo, hi = c.bounding_box()
    assert lo[1] == pytest.approx(-math.cos(math.pi / k))                   # flat bottom edge
    assert np.all(hi - lo <= 2.0 + 1e-12)


@pytest.mark.parametrize("h", [0.1, 0.3, 0.5, 0.6, 0.8, 1.0, 2.5])
def test_rectangle_geometry(h):
    c = rectangle(1.0, h)
    assert c.area() == pytest.approx(h)
    assert c.inradius() == pytest.approx(min(h, 1.0) / 2, abs=1e-9)
    lo, hi = c.bounding_box()
    np.testing.assert_allclose(hi - lo, [1.0, h], atol=1e-12)
    assert c.spec == {"type": "rectangle", "width": 1.0, "height": h}


def test_semicircle_and_quadrant_geometry():
    s, q = semicircle(), quadrant()
    assert s.area(samples=400_000) == pytest.approx(math.pi / 2, rel=5e-3)
    assert q.area(samples=400_000) == pytest.approx(math.pi / 4, rel=5e-3)
    # n = 1: incircles
    assert s.inradius() == pytest.approx(0.5, abs=1e-9)
    assert q.inradius() == pytest.approx(math.sqrt(2) - 1, abs=1e-9)
    assert s.clearance(np.array([[0.0, 0.5]]))[0] == pytest.approx(0.5)
    assert q.clearance(np.array([[0.2, 0.3]]))[0] == pytest.approx(0.2)
    assert semicircle(2.0).inradius() == pytest.approx(1.0, abs=1e-9)


def test_arbitrary_convex_polygon():
    V = [[0, 0], [3, 0], [4, 1], [2, 3], [0, 2]]
    c = polygon(V)
    shoelace = 0.5 * abs(sum(V[i][0] * V[(i + 1) % 5][1] - V[(i + 1) % 5][0] * V[i][1] for i in range(5)))
    assert c.area() == pytest.approx(shoelace)
    assert np.all(np.abs(c.clearance(np.asarray(V, float))) < 1e-12)
    assert c.contains(np.mean(V, axis=0)[None])[0]
    assert polygon(V[::-1]).area() == pytest.approx(shoelace)   # orientation-independent
    with pytest.raises(ValueError):
        polygon([[0, 0], [1, 0], [2, 0]])                          # degenerate
    with pytest.raises(ValueError):
        polygon([[0, 0], [1, 1]])


def test_general_triangle_and_right_triangle():
    t = triangle([0, 0], [4, 0], [0, 3])
    assert t.inradius() == pytest.approx(1.0, abs=1e-9)                 # 3-4-5 triangle
    rt = right_isosceles_triangle()
    assert rt.inradius() == pytest.approx((2 - math.sqrt(2)) / 2, abs=1e-9)


def test_container_validation():
    with pytest.raises(ValueError):
        Container(np.zeros((1, 2)), np.ones(1))       # zero normal
    with pytest.raises(ValueError):
        Container(np.zeros((0, 2)), np.zeros(0))      # no primitives
    with pytest.raises(ValueError):
        circle(-1.0)
    with pytest.raises(ValueError):
        regular_polygon(2)


@pytest.mark.parametrize("name", sorted(CONTAINER_NAMES))
def test_every_short_name_builds(name):
    params = {"polygon": {"vertices": [[0, 0], [1, 0], [0, 1]]},
              "triangle": {"vertices": [[0, 0], [1, 0], [0, 1]]}}.get(name, {})
    c = make_container(name, **params)
    assert c.area() > 0
    c2 = Container.from_dict(json.loads(json.dumps(c.to_dict())))
    np.testing.assert_allclose(c2.A, c.A)
    np.testing.assert_allclose(c2.b, c.b)


@pytest.mark.parametrize("table, container, n1", [
    pytest.param("nonagon", regular_polygon(9), None, marks=pytest.mark.records("nonagon")),
    pytest.param("dodecagon", regular_polygon(12), math.cos(math.pi / 12), marks=pytest.mark.records("dodecagon")),
    pytest.param("rectangle_0.3", rectangle(1, 0.3), 0.15, marks=pytest.mark.records("rectangle_0.3")),
    pytest.param("rectangle_0.6", rectangle(1, 0.6), 0.3, marks=pytest.mark.records("rectangle_0.6")),
])
def test_new_record_tables(table, container, n1):
    assert table in available() and table in PACKOMANIA
    recs = load_records(table)
    if n1 is not None:
        assert known_radius(table, 1) == pytest.approx(n1, abs=1e-11)
        assert container.inradius() == pytest.approx(n1, abs=1e-9)
    ns = sorted(recs)
    # r(n) >= r(n + 1) must hold (drop a circle). The site's crc_600 table violates it at
    # n = 179 and 219, i.e. those two entries are beaten by the n + 1 packings.
    bad = [a for a, b in zip(ns, ns[1:]) if float(recs[b]) > float(recs[a]) + 1e-15]
    assert bad == ([179, 219] if table == "rectangle_0.6" else [])


def test_record_key_mapping():
    assert record_key("regular_polygon", {"k": 9}) == "nonagon"
    assert record_key("dodecagon", {}) == "dodecagon"
    assert record_key("rectangle", {"height": 0.3}) == "rectangle_0.3"
    assert record_key("rectangle", {"width": 1, "height": 1}) == "square"
    assert record_key("regular_polygon", {"k": 7}) == "heptagon"
    assert record_key("regular_polygon", {"k": 4}) is None
    assert record_key("rectangle", {"height": 0.35}) is None
    assert record_key("hexagon", {"circumradius": 2}) is None


# ------------------------------------------------------------- verifier edges
def test_touching_exactly_at_tolerance(tmp_path):
    # pair slack exactly -tol (dyadic numbers, no rounding): accepted; -2 tol: rejected
    tol = 2.0 ** -40
    X = np.array([[-0.25, 0.0], [0.25, 0.0]])
    p = save_solution(tmp_path / "a.json", square(), X, 0.25 + tol / 2)
    ok, rep = verify(p, tol=tol)
    assert rep["min_pair_slack"] == -tol and ok
    p2 = save_solution(tmp_path / "b.json", square(), X, 0.25 + tol)
    assert not verify(p2, tol=tol)[0]
    # exact mode: eps = the overshoot exactly restores touching (allowed), less does not
    assert verify_exact(p, eps=str(Fraction(tol / 2)))[0]
    assert not verify_exact(p, eps=str(Fraction(tol / 4)))[0]


def test_container_contact_at_tolerance(tmp_path):
    tol = 2.0 ** -40
    p = save_solution(tmp_path / "c.json", circle(), np.array([[0.5, 0.0]]), 0.5 + tol)
    ok, rep = verify(p, tol=tol)
    assert rep["min_container_slack"] == -tol and ok
    assert not verify(p, tol=tol / 2)[0]


def test_exact_mode_irrational_container(tmp_path):
    # regular 7-gon: irrational vertices, stored float primitives are used
    c = regular_polygon(7)
    r = math.cos(math.pi / 7)
    p = save_solution(tmp_path / "h.json", c, np.zeros((1, 2)), r)
    assert exact_primitives(c.spec) is None
    ok, rep = verify_exact(p, eps="1e-12")
    assert ok and rep["primitives"] == "stored float primitives"
    assert not verify_exact(p, eps="-1e-9")[0]      # growing the radius must fail


def test_exact_primitives_rational_specs_match_floats():
    for c in (square(), rectangle(1, 0.3), right_isosceles_triangle(), quadrant(), semicircle(), circle(),
              polygon([[0, 0], [3, 0], [2, 1], [0, 1]])):
        hp, dk = exact_primitives(c.spec)
        assert len(hp) == c.n_halfplanes and len(dk) == c.n_disks
        for a1, a2, b in hp:  # each exact half-plane matches one float primitive after normalisation
            na = math.hypot(float(a1), float(a2))
            assert np.any(np.all(np.isclose(c.A, [float(a1) / na, float(a2) / na]), axis=1)
                          & np.isclose(c.b, float(b) / na))


def test_exact_detects_tiny_overlap_float_misses(tmp_path):
    # overlap of ~1e-17: float check passes with tol 1e-12, exact with eps=0 fails
    X = np.array([[-0.25, -0.25], [0.25, -0.25], [-0.25, 0.25], [0.25, 0.25]])
    r = np.nextafter(0.25, 1.0)
    p = save_solution(tmp_path / "o.json", square(), X, r)
    assert verify(p)[0]
    assert not verify_exact(p, eps="0")[0]
    assert verify_exact(p, eps="1e-15")[0]


# ---------------------------------------------------------------- JSON files
@pytest.mark.parametrize("c", [square(), circle(), quadrant(), semicircle(), regular_polygon(11),
                               rectangle(1, 0.3), right_isosceles_triangle(),
                               polygon([[0, 0], [3, 0], [2, 1], [0, 1]])], ids=lambda c: c.name)
def test_json_roundtrip_is_exact(tmp_path, c):
    rng = np.random.default_rng(0)
    X = c.sample(13, rng)
    r = 0.012345678901234567
    meta = {"seed": 3, "note": "x", "nested": {"a": [1, 2]}}
    p = save_solution(tmp_path / "s.json", c, X, r, meta)
    C2, X2, r2, m2 = load_solution(p)
    assert np.array_equal(X2, X) and r2 == r and m2 == meta
    assert C2.spec == c.spec
    np.testing.assert_array_equal(C2.A, c.A)
    np.testing.assert_array_equal(C2.R, c.R)
    doc = json.loads(p.read_text())
    assert doc["n"] == 13 and doc["format"] == "circlepack/1"


def test_custom_container_roundtrip(tmp_path):
    c = Container.from_dict({"halfplanes": [[0, -1, 0]], "disks": [[0, 0, 1], [0.5, 0, 1]]})
    p = save_solution(tmp_path / "lens.json", c, np.array([[0.25, 0.3]]), 0.1)
    C2, *_ = load_solution(p)
    np.testing.assert_array_equal(C2.C, c.C)
    assert verify(p)[0] and verify_exact(p)[0]


def test_n_mismatch_is_an_error(tmp_path):
    p = save_solution(tmp_path / "s.json", square(), np.zeros((1, 2)), 0.1)
    d = json.loads(p.read_text())
    d["n"] = 2
    p.write_text(json.dumps(d))
    with pytest.raises(ValueError):
        verify(p)


# ------------------------------------------------------------------ CLI smoke
def _closed_form_square_cache(directory):
    """Write a square table holding only proven closed-form optima (no Packomania data)."""
    from circlepack.records import TABLES, build_cache_entry

    m3 = math.sqrt(6) - math.sqrt(2)
    radii = {1: 0.5, 2: (2 - math.sqrt(2)) / 2, 3: m3 / (2 * (1 + m3)), 4: 0.25}
    page = "<table><tr><th>N</th><th>radius</th></tr>" + "".join(
        f"<tr><td>{n}</td><td>{r:.15f}</td></tr>" for n, r in radii.items()) + "</table>"
    entry = build_cache_entry(TABLES["square"], page, source="closed form (test)")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "csq.json").write_text(json.dumps(entry))


def test_cli_records(empty_cache, capsys):
    _closed_form_square_cache(empty_cache)
    assert cli_main(["records"]) == 0
    out = capsys.readouterr().out
    assert "square" in out and "nonagon" in out and "not fetched" in out
    assert cli_main(["records", "square", "--n", "4"]) == 0
    assert capsys.readouterr().out.split() == ["4", "0.25"]


def test_cli_bench_tiny(empty_cache, tmp_path, capsys):
    _closed_form_square_cache(empty_cache)
    out = tmp_path / "bench"
    assert cli_main(["bench", "--container", "square", "--n", "2-3", "--starts", "2", "--workers", "1",
                     "--hops", "2", "--nice", "0", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "reached known best" in text and "2/2 values" in text
    rows = json.loads((out / "summary.json").read_text())
    assert [r["n"] for r in rows] == [2, 3]
    assert cli_main(["verify", str(out / "square_n2.json"), str(out / "square_n3.json"), "--exact"]) == 0


@pytest.mark.parametrize("args", [
    ["--container", "regular_polygon", "--param", "k=9"],
    ["--container", "rectangle", "--param", "height=0.3", "--polish-method", "slp"],
    ["--spec", '{"type": "polygon", "vertices": [[0,0],[3,0],[2,1],[0,1]]}'],
])
def test_cli_run_variants(tmp_path, capsys, args):
    out = tmp_path / "r.json"
    assert cli_main(["run", *args, "--n", "4", "--starts", "1", "--workers", "1", "--hops", "1",
                     "--nice", "0", "--quiet", "--out", str(out)]) == 0
    assert cli_main(["verify", str(out)]) == 0
    assert "VALID" in capsys.readouterr().out


def test_cli_rejects_unknown_container():
    with pytest.raises(SystemExit):
        cli_main(["run", "--container", "torus", "--n", "3"])
