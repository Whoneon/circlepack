# Containers

[Italiano](../it/containers.md) | [README](../../README.md)

A container is `{x : a_k . x <= b_k for all k} intersected with {x : |x - c_j| <= R_j for all j}`.
Every container with such a description works with the optimiser and the
verifier, as long as it is convex and bounded (a disk, or enough half-planes to
close the region). Half-plane normals are normalised on construction.

## Built-in types (spec `type`)

| `type` | Parameters | Geometry |
|---|---|---|
| `square` | `side=1` | `[-s/2, s/2]^2` |
| `rectangle` | `width=1, height=1` | `[-w/2, w/2] x [-h/2, h/2]` |
| `regular_polygon` | `k=6, circumradius=1, rotation=None` | k-gon centred at the origin, flat bottom edge by default |
| `polygon` | `vertices` | convex polygon, either orientation |
| `triangle` | `vertices` (three points) | any triangle |
| `right_isosceles_triangle` | `leg=1` | vertices (0,0), (L,0), (0,L) |
| `circle` | `radius=1` | disk at the origin |
| `quadrant` | `radius=1` | `x >= 0, y >= 0, |x| <= R` |
| `semicircle` | `radius=1` | `y >= 0, |x| <= R` |

The CLI short names `right_triangle`, `pentagon`, `hexagon`, `nonagon`,
`dodecagon` are also accepted as `type`.

## Packomania normalisation

Square side 1 centred at the origin (csq); rectangle `1 x h` centred at the
origin (crc); circle radius 1 (cci); right triangle legs 1 with the right angle
at the origin (crt); quadrant and semicircle radius 1 (ccq, csc); regular k-gon
circumradius 1 (cpt, chx, cno, cdd). These were checked against the site's
coordinate files and the n = 1 radii (the inradius).

## Custom containers through a spec

On the command line, `--spec` takes a JSON string or a file:

```bash
circlepack run --n 10 --spec '{"type": "polygon", "vertices": [[0,0],[3,0],[2,1],[0,1]]}'
circlepack run --n 8  --spec '{"type": "triangle", "vertices": [[0,0],[1,0],[0.3,0.8]]}'
circlepack run --n 12 --spec my_container.json
```

A real run of the first container with n = 6, 4 starts and 5 hops gave
`r = 0.289528631083438`, VALID in float mode (the exact check of polygon specs
works from the rational vertices).

## Lenses and arbitrary half-plane/disk intersections

The built-in constructors are conveniences; any other region needs the generic
class. A `custom` container is described by its primitives directly, which is
also how every solution file stores it (`container.halfplanes`,
`container.disks`):

```python
import numpy as np
from circlepack import Container, run_many, SearchConfig

if __name__ == "__main__":      # required: workers are started with "spawn"
    # lens: intersection of two unit disks centred at (-0.5, 0) and (0.5, 0)
    lens = Container(A=np.zeros((0, 2)), b=np.zeros(0),
                     C=[[-0.5, 0.0], [0.5, 0.0]], R=[1.0, 1.0], name="lens")
    res = run_many(lens, n=7, starts=4, workers=2, cfg=SearchConfig(hops=3))
    print(res.best.r)           # 0.19724606981995318 in our run
```

Notes: a container built this way has `spec == {}`, so it is not reconstructible
through the CLI `--spec`; saving a solution stores the primitives, and loading
rebuilds a `custom` container from them. Exact verification of such files uses
the stored float primitives (not a rational `spec`), and the area (used for the
penalty scale) is computed by Monte Carlo when disks are present.
Ensure the region is convex and non-empty; empty or unbounded regions raise
`ValueError`.

## Records

A record table is matched to a container only for the normalisations listed
above; any other parameter (e.g. a square of side 2) has no table. Tables are
downloaded with `circlepack records fetch` (see [cli.md](cli.md#records)); they
are not part of the package.
