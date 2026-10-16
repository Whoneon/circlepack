"""Solution files (JSON).

Schema (``format: "circlepack/1"``)::

    {
      "format": "circlepack/1",
      "container": {"name": ..., "spec": {"type": ..., ...},
                    "halfplanes": [[a1, a2, b], ...],      # a . x <= b
                    "disks": [[cx, cy, R], ...]},          # |x - c| <= R
      "n": 20,
      "r": 0.111382347512,
      "centers": [[x, y], ...],
      "meta": {...}
    }

Floats are written with ``repr`` precision (17 significant digits), so the
file round-trips exactly.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .containers import Container

__all__ = ["save_solution", "load_solution", "FORMAT"]

FORMAT = "circlepack/1"


def save_solution(path: str | Path, container: Container, X: np.ndarray, r: float,
                  meta: dict | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "format": FORMAT,
        "container": container.to_dict(),
        "n": int(X.shape[0]),
        "r": float(r),
        "centers": [[float(x), float(y)] for x, y in np.asarray(X, float)],
        "meta": meta or {},
    }
    path.write_text(json.dumps(doc, indent=1) + "\n")
    return path


def load_solution(path: str | Path) -> tuple[Container, np.ndarray, float, dict]:
    doc = json.loads(Path(path).read_text())
    C = Container.from_dict(doc["container"])
    X = np.asarray(doc["centers"], dtype=float).reshape(-1, 2)
    return C, X, float(doc["r"]), doc.get("meta", {})
