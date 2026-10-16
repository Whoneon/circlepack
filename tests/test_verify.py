import json
import math

import numpy as np
import pytest

from circlepack.containers import circle, quadrant, regular_polygon, right_isosceles_triangle, square
from circlepack.solution import load_solution, save_solution
from circlepack.verify import main as verify_main
from circlepack.verify import verify, verify_exact


def _four_in_square(r=0.25):
    return np.array([[-0.25, -0.25], [0.25, -0.25], [-0.25, 0.25], [0.25, 0.25]]), r


def test_accepts_known_optimum(tmp_path):
    X, r = _four_in_square()
    p = save_solution(tmp_path / "s4.json", square(), X, r)
    ok, rep = verify(p)
    assert ok and rep["min_pair_slack"] == 0.0 and rep["min_container_slack"] == 0.0
    ok, rep = verify_exact(p, eps="1e-15")
    assert ok and rep["primitives"] == "spec (exact)"
    assert verify_main([str(p), "--exact"]) == 0


def test_exact_mode_needs_positive_eps_for_touching_circles(tmp_path):
    X, r = _four_in_square()
    p = save_solution(tmp_path / "s4.json", square(), X, r)
    assert verify_exact(p, eps="0")[0]          # exactly touching is still a packing
    p2 = save_solution(tmp_path / "s4b.json", square(), X, r + 1e-15)
    assert not verify_exact(p2, eps="0")[0]


def test_rejects_overlap(tmp_path):
    X, _ = _four_in_square()
    p = save_solution(tmp_path / "bad.json", square(), X, 0.2501)
    ok, rep = verify(p)
    assert not ok and rep["min_pair_slack"] < 0
    assert not verify_exact(p)[0]
    assert verify_main([str(p)]) == 1


def test_rejects_outside(tmp_path):
    X = np.array([[0.0, 0.0], [0.0, 0.8]])
    p = save_solution(tmp_path / "out.json", circle(), X, 0.3)
    ok, rep = verify(p)
    assert not ok and rep["min_container_slack"] == pytest.approx(1 - 0.8 - 0.3)
    ok, rep = verify_exact(p)
    assert not ok and rep["failures"][0][0] == "disk"


def test_exact_halfplane_without_sqrt(tmp_path):
    # n = 1 in the isosceles right triangle: the incircle touches the hypotenuse x + y <= 1
    r = (2 - math.sqrt(2)) / 2
    p = save_solution(tmp_path / "t1.json", right_isosceles_triangle(), np.array([[r, r]]), r)
    assert verify(p)[0]
    assert verify_exact(p, eps="1e-14")[0]
    p2 = save_solution(tmp_path / "t1b.json", right_isosceles_triangle(), np.array([[r, r]]), r + 1e-9)
    assert not verify_exact(p2, eps="1e-14")[0]


def test_irrational_container_uses_stored_primitives(tmp_path):
    p = save_solution(tmp_path / "hex.json", regular_polygon(6), np.zeros((1, 2)), 0.8)
    ok, rep = verify_exact(p)
    assert ok and rep["primitives"] == "stored float primitives"


def test_quadrant_and_roundtrip(tmp_path):
    r = math.sqrt(2) - 1
    p = save_solution(tmp_path / "q.json", quadrant(), np.array([[r, r]]), r * (1 - 1e-15))
    C, X, rr, _ = load_solution(p)
    assert C.spec["type"] == "quadrant" and rr == r * (1 - 1e-15)
    assert verify(p)[0] and verify_exact(p, eps="1e-15")[0]
    assert json.loads(p.read_text())["format"] == "circlepack/1"


def test_verifier_is_stdlib_only():
    import ast
    import circlepack.verify as v

    tree = ast.parse(open(v.__file__).read())
    mods = {a.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names}
    mods |= {node.module.split(".")[0] for node in ast.walk(tree)
             if isinstance(node, ast.ImportFrom) and node.module}
    assert mods <= {"__future__", "argparse", "itertools", "json", "math", "sys", "fractions"}


def test_non_solution_file_is_reported_not_crashing(tmp_path, capsys):
    p = tmp_path / "summary.json"
    p.write_text("[1, 2, 3]")
    assert verify_main([str(p)]) == 1
    assert "ERROR" in capsys.readouterr().out
