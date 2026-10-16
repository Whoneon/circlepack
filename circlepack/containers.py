"""Convex containers built as intersections of half-planes and disks.

A container is the intersection of

* half-planes ``a . x <= b`` with ``|a| = 1`` (normalised on construction), and
* disks ``|x - c| <= R``.

A circle of radius ``r`` centred at ``x`` lies inside the container iff

* ``a . x + r <= b``     for every half-plane, and
* ``|x - c| + r <= R``   for every disk.

Both conditions are exact for convex primitives, so every container that can be
written this way (polygons, circles, circular sectors with angle <= pi,
lenses, ...) is supported by the same optimiser and the same verifier.

Scale conventions follow Packomania (www.packomania.com, E. Specht) where a
matching catalogue exists; see :data:`PACKOMANIA` and the README.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import ArrayLike

__all__ = [
    "Container",
    "square",
    "rectangle",
    "regular_polygon",
    "polygon",
    "triangle",
    "right_isosceles_triangle",
    "circle",
    "quadrant",
    "semicircle",
    "make_container",
    "CONTAINER_NAMES",
    "PACKOMANIA",
]


@dataclass
class Container:
    """Intersection of half-planes ``A x <= b`` and disks ``|x - C_k| <= R_k``.

    Attributes
    ----------
    A : (h, 2) array, rows are unit outward normals.
    b : (h,) array.
    C : (k, 2) array of disk centres.
    R : (k,) array of disk radii.
    name : human readable name.
    spec : JSON-serialisable dict that rebuilds this container through
        :func:`make_container` (``{"type": ..., **params}``).
    """

    A: np.ndarray
    b: np.ndarray
    C: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    R: np.ndarray = field(default_factory=lambda: np.zeros(0))
    name: str = "custom"
    spec: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        A = np.asarray(self.A, dtype=float).reshape(-1, 2)
        b = np.asarray(self.b, dtype=float).reshape(-1)
        if A.shape[0] != b.shape[0]:
            raise ValueError("A and b must have the same number of rows")
        norms = np.linalg.norm(A, axis=1)
        if np.any(norms <= 0):
            raise ValueError("half-plane normal must be non-zero")
        self.A = A / norms[:, None]
        self.b = b / norms
        self.C = np.asarray(self.C, dtype=float).reshape(-1, 2)
        self.R = np.asarray(self.R, dtype=float).reshape(-1)
        if self.C.shape[0] != self.R.shape[0]:
            raise ValueError("C and R must have the same number of rows")
        if np.any(self.R <= 0):
            raise ValueError("disk radii must be positive")
        if self.A.shape[0] == 0 and self.C.shape[0] == 0:
            raise ValueError("container must have at least one primitive")
        self._bbox: tuple[np.ndarray, np.ndarray] | None = None

    # ------------------------------------------------------------------ basics
    @property
    def n_halfplanes(self) -> int:
        return self.A.shape[0]

    @property
    def n_disks(self) -> int:
        return self.C.shape[0]

    def clearance(self, X: np.ndarray) -> np.ndarray:
        """Largest radius of a circle centred at each row of ``X`` that fits.

        Negative values mean the centre is outside the container.
        """
        X = np.atleast_2d(X)
        out = np.full(X.shape[0], np.inf)
        if self.n_halfplanes:
            out = np.minimum(out, np.min(self.b[None, :] - X @ self.A.T, axis=1))
        if self.n_disks:
            d = np.linalg.norm(X[:, None, :] - self.C[None, :, :], axis=2)
            out = np.minimum(out, np.min(self.R[None, :] - d, axis=1))
        return out

    def contains(self, X: np.ndarray, r: float = 0.0, tol: float = 0.0) -> np.ndarray:
        return self.clearance(X) >= r - tol

    def bounding_box(self) -> tuple[np.ndarray, np.ndarray]:
        """Axis-aligned bounding box (computed once by linear programming)."""
        if self._bbox is None:
            self._bbox = _bounding_box(self)
        return self._bbox

    def area(self, samples: int = 200_000, seed: int = 0) -> float:
        """Container area (exact for polygons, Monte Carlo otherwise)."""
        if self.spec.get("type") == "circle":
            return math.pi * self.R[0] ** 2
        if self.n_disks == 0:
            return _polygon_area(_polygon_vertices(self.A, self.b))
        lo, hi = self.bounding_box()
        rng = np.random.default_rng(seed)
        P = lo + rng.random((samples, 2)) * (hi - lo)
        frac = np.mean(self.clearance(P) >= 0)
        return float(frac * np.prod(hi - lo))

    def sample(self, m: int, rng: np.random.Generator, margin: float = 0.0) -> np.ndarray:
        """Uniform samples inside the container shrunk by ``margin`` (rejection)."""
        lo, hi = self.bounding_box()
        out = []
        need = m
        while need > 0:
            P = lo + rng.random((max(4 * need, 64), 2)) * (hi - lo)
            P = P[self.clearance(P) >= margin]
            out.append(P[:need])
            need -= len(out[-1])
        return np.concatenate(out, axis=0)

    def inradius(self) -> float:
        """Radius of the largest inscribed circle (approximate, via sampling+refine)."""
        from scipy.optimize import minimize

        rng = np.random.default_rng(0)
        P = self.sample(4000, rng)
        x0 = P[np.argmax(self.clearance(P))]
        res = minimize(lambda x: -self.clearance(x[None, :])[0], x0, method="Nelder-Mead",
                       options={"xatol": 1e-12, "fatol": 1e-14, "maxiter": 4000})
        return float(-res.fun)

    # ------------------------------------------------------------ (de)serialise
    def primitives(self) -> dict:
        """Explicit primitive list (what the stand-alone verifier reads)."""
        return {
            "halfplanes": [[float(a[0]), float(a[1]), float(bb)] for a, bb in zip(self.A, self.b)],
            "disks": [[float(c[0]), float(c[1]), float(rr)] for c, rr in zip(self.C, self.R)],
        }

    def to_dict(self) -> dict:
        d = {"name": self.name, "spec": dict(self.spec)}
        d.update(self.primitives())
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Container":
        if d.get("spec", {}).get("type") and d["spec"]["type"] != "custom":
            return make_container(**d["spec"])
        hp = np.asarray(d.get("halfplanes", []), dtype=float).reshape(-1, 3)
        dk = np.asarray(d.get("disks", []), dtype=float).reshape(-1, 3)
        return cls(hp[:, :2], hp[:, 2], dk[:, :2], dk[:, 2], name=d.get("name", "custom"),
                   spec={"type": "custom"})


# ---------------------------------------------------------------- constructors
def _halfplanes_from_ccw_vertices(V: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    V = np.asarray(V, dtype=float)
    if V.ndim != 2 or V.shape[1] != 2 or V.shape[0] < 3:
        raise ValueError("need at least three 2-D vertices")
    E = np.roll(V, -1, axis=0) - V
    signed = 0.5 * np.sum(V[:, 0] * np.roll(V[:, 1], -1) - np.roll(V[:, 0], -1) * V[:, 1])
    if signed < 0:  # make counter-clockwise
        V = V[::-1]
        E = np.roll(V, -1, axis=0) - V
    if abs(signed) < 1e-15:
        raise ValueError("degenerate polygon")
    cross = E[:, 0] * np.roll(E, -1, axis=0)[:, 1] - E[:, 1] * np.roll(E, -1, axis=0)[:, 0]
    if np.any(cross < -1e-12):
        raise ValueError("polygon is not convex")
    A = np.stack([E[:, 1], -E[:, 0]], axis=1)  # outward normal for CCW order
    b = np.einsum("ij,ij->i", A, V)
    return A, b


def polygon(vertices: ArrayLike, name: str = "polygon") -> Container:
    """Arbitrary convex polygon from its vertices (either orientation)."""
    V = np.asarray(vertices, dtype=float)
    A, b = _halfplanes_from_ccw_vertices(V)
    return Container(A, b, name=name, spec={"type": "polygon", "vertices": V.tolist()})


def rectangle(width: float = 1.0, height: float = 1.0) -> Container:
    """Axis-aligned rectangle ``[-w/2, w/2] x [-h/2, h/2]``.

    Packomania "circles in a 1 x h rectangle" (crc) uses ``width=1``.
    """
    w, h = float(width), float(height)
    A = [[1, 0], [-1, 0], [0, 1], [0, -1]]
    b = [w / 2, w / 2, h / 2, h / 2]
    return Container(np.asarray(A, float), np.asarray(b, float), name=f"rectangle {w:g}x{h:g}",
                     spec={"type": "rectangle", "width": w, "height": h})


def square(side: float = 1.0) -> Container:
    """Square ``[-s/2, s/2]^2``. Packomania (csq): side 1, centred at origin."""
    c = rectangle(side, side)
    c.name = f"square {side:g}"
    c.spec = {"type": "square", "side": float(side)}
    return c


def regular_polygon(k: int, circumradius: float = 1.0, rotation: float | None = None) -> Container:
    """Regular ``k``-gon centred at the origin.

    Packomania (cpt, chx, chp, ...) fixes the circumradius to 1. By default a
    flat edge is at the bottom (orientation does not affect the optimum).
    """
    k = int(k)
    if k < 3:
        raise ValueError("k >= 3")
    if rotation is None:
        rotation = -math.pi / 2 - math.pi / k  # bottom edge horizontal
    t = rotation + 2 * math.pi * np.arange(k) / k
    V = circumradius * np.stack([np.cos(t), np.sin(t)], axis=1)
    A, b = _halfplanes_from_ccw_vertices(V)
    return Container(A, b, name=f"regular {k}-gon",
                     spec={"type": "regular_polygon", "k": k, "circumradius": float(circumradius),
                           "rotation": float(rotation)})


def triangle(p0: ArrayLike, p1: ArrayLike, p2: ArrayLike) -> Container:
    """General triangle from three vertices."""
    c = polygon([p0, p1, p2], name="triangle")
    c.spec = {"type": "triangle", "vertices": np.asarray([p0, p1, p2], float).tolist()}
    return c


def right_isosceles_triangle(leg: float = 1.0) -> Container:
    """Isosceles right triangle with vertices (0,0), (L,0), (0,L).

    Packomania (crt): legs of length 1, right angle at the origin.
    """
    L = float(leg)
    c = polygon([[0, 0], [L, 0], [0, L]], name="isosceles right triangle")
    c.spec = {"type": "right_isosceles_triangle", "leg": L}
    return c


def circle(radius: float = 1.0) -> Container:
    """Disk of given radius at the origin. Packomania (cci): radius 1."""
    R = float(radius)
    return Container(np.zeros((0, 2)), np.zeros(0), np.zeros((1, 2)), np.array([R]), name="circle",
                     spec={"type": "circle", "radius": R})


def quadrant(radius: float = 1.0) -> Container:
    """Circular quadrant ``x >= 0, y >= 0, |x| <= R``. Packomania (ccq): R = 1."""
    R = float(radius)
    return Container(np.array([[-1.0, 0.0], [0.0, -1.0]]), np.zeros(2), np.zeros((1, 2)), np.array([R]), name="circular quadrant",
                     spec={"type": "quadrant", "radius": R})


def semicircle(radius: float = 1.0) -> Container:
    """Semicircle ``y >= 0, |x| <= R``. Packomania (csc): R = 1."""
    R = float(radius)
    return Container(np.array([[0.0, -1.0]]), np.zeros(1), np.zeros((1, 2)), np.array([R]), name="semicircle",
                     spec={"type": "semicircle", "radius": R})


_FACTORIES = {
    "square": lambda side=1.0: square(side),
    "rectangle": lambda width=1.0, height=1.0: rectangle(width, height),
    "regular_polygon": lambda k=6, circumradius=1.0, rotation=None: regular_polygon(k, circumradius, rotation),
    "polygon": lambda vertices: polygon(vertices),
    "triangle": lambda vertices: triangle(*vertices),
    "right_isosceles_triangle": lambda leg=1.0: right_isosceles_triangle(leg),
    "circle": lambda radius=1.0: circle(radius),
    "quadrant": lambda radius=1.0: quadrant(radius),
    "semicircle": lambda radius=1.0: semicircle(radius),
}

#: Short CLI names -> (factory type, default params). These match Packomania scale.
CONTAINER_NAMES = {
    "square": ("square", {}),
    "circle": ("circle", {}),
    "right_triangle": ("right_isosceles_triangle", {}),
    "quadrant": ("quadrant", {}),
    "semicircle": ("semicircle", {}),
    "pentagon": ("regular_polygon", {"k": 5}),
    "hexagon": ("regular_polygon", {"k": 6}),
    "nonagon": ("regular_polygon", {"k": 9}),
    "dodecagon": ("regular_polygon", {"k": 12}),
    "rectangle": ("rectangle", {}),
    "regular_polygon": ("regular_polygon", {}),
    "polygon": ("polygon", {}),
    "triangle": ("triangle", {}),
}

#: Packomania catalogue code and normalisation for each named container.
PACKOMANIA = {
    "square": ("csq", "square of side 1, [-1/2, 1/2]^2"),
    "circle": ("cci", "circle of radius 1 centred at the origin"),
    "right_triangle": ("crt", "isosceles right triangle, legs 1, vertices (0,0),(1,0),(0,1)"),
    "quadrant": ("ccq", "quarter disk of radius 1, x >= 0, y >= 0"),
    "semicircle": ("csc", "half disk of radius 1, y >= 0"),
    "pentagon": ("cpt", "regular pentagon with circumradius 1"),
    "hexagon": ("chx", "regular hexagon with circumradius 1"),
    "nonagon": ("cno", "regular 9-gon with circumradius 1"),
    "dodecagon": ("cdd", "regular 12-gon with circumradius 1"),
    "rectangle_0.3": ("crc_300", "rectangle 1 x 0.3"),
    "rectangle_0.5": ("crc_500", "rectangle 1 x 0.5"),
    "rectangle_0.6": ("crc_600", "rectangle 1 x 0.6"),
}


def make_container(type: str, **params) -> Container:  # noqa: A002 - mirrors JSON key
    """Build a container from a spec dict, e.g. ``make_container("regular_polygon", k=5)``.

    Short names from :data:`CONTAINER_NAMES` (``right_triangle``, ``pentagon``,
    ...) are accepted too.
    """
    if type in CONTAINER_NAMES and type not in _FACTORIES:
        base, defaults = CONTAINER_NAMES[type]
        return _FACTORIES[base](**{**defaults, **params})
    if type not in _FACTORIES:
        raise ValueError(f"unknown container type {type!r}; known: {sorted(set(_FACTORIES) | set(CONTAINER_NAMES))}")
    return _FACTORIES[type](**params)


# ------------------------------------------------------------------- helpers
def _bounding_box(c: Container) -> tuple[np.ndarray, np.ndarray]:
    from scipy.optimize import linprog

    lo = np.empty(2)
    hi = np.empty(2)
    # Disks are bounded; intersect their boxes with the LP over half-planes.
    big = 1e6
    box_lo = np.full(2, -big)
    box_hi = np.full(2, big)
    for cc, rr in zip(c.C, c.R):
        box_lo = np.maximum(box_lo, cc - rr)
        box_hi = np.minimum(box_hi, cc + rr)
    for k in range(2):
        for sgn, store in ((1.0, lo), (-1.0, hi)):
            cost = np.zeros(2)
            cost[k] = sgn
            if c.n_halfplanes:
                res = linprog(cost, A_ub=c.A, b_ub=c.b, bounds=list(zip(box_lo, box_hi)), method="highs")
                if res.status != 0:
                    raise ValueError("container is empty or unbounded")
                store[k] = res.x[k]
            else:
                store[k] = box_lo[k] if sgn > 0 else box_hi[k]
    if np.any(hi - lo >= big):
        raise ValueError("container is unbounded")
    return lo, hi


def _polygon_vertices(A: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Vertices of the polygon ``A x <= b`` (small h, brute force)."""
    pts = []
    h = A.shape[0]
    for i in range(h):
        for j in range(i + 1, h):
            M = np.array([A[i], A[j]])
            if abs(np.linalg.det(M)) < 1e-14:
                continue
            p = np.linalg.solve(M, [b[i], b[j]])
            if np.all(A @ p <= b + 1e-10):
                pts.append(p)
    P = np.unique(np.round(np.array(pts), 13), axis=0)
    ctr = P.mean(axis=0)
    ang = np.arctan2(P[:, 1] - ctr[1], P[:, 0] - ctr[0])
    return P[np.argsort(ang)]


def _polygon_area(V: np.ndarray) -> float:
    x, y = V[:, 0], V[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)))
