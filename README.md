# circlepack

**English** | [Italiano](README.it.md)

`circlepack` packs **n equal circles of maximal radius** into a **fixed convex
container** built from half-planes and disks (square, rectangles, regular and
arbitrary convex polygons, triangles, circle, quadrant, semicircle, lenses, ...).
It combines a soft-to-rigid penalty relaxation, basin hopping and a high-precision
local polish (dense SLSQP or a sparse sequential-LP polish on HiGHS), runs many
starts in parallel, and ships a stand-alone verifier that can check every
packing in **exact rational arithmetic**.

## Features

- Any convex container that is an intersection of half-planes and disks; the
  common radius `r` is maximised while the container stays fixed (Packomania
  convention).
- Global phase: soft-to-rigid penalty continuation (L-BFGS-B, vectorised NumPy,
  Verlet neighbour lists), uniform and lattice-seeded starts.
- Basin hopping with *jiggle* and *relocate-to-hole* moves.
- Local polish reaching known optima to about 1e-15: dense SLSQP with analytic
  Jacobians (small n) and a sparse SLP polish with HiGHS (large n; n = 300 in
  about 0.5 s instead of about 30 s).
- Parallel multi-start driver (spawned workers, niced, capped).
- Stand-alone, standard-library-only verifier with an exact rational mode.
- `circlepack records fetch` downloads the Packomania best-known radii (27
  tables) into a local cache on your machine; `bench` compares against them.
  The tables are not distributed with circlepack.
- A `Backend` seam for a future GPU global phase.

## Quick start

```bash
git clone https://github.com/Whoneon/circlepack.git circlepack && cd circlepack
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"        # numpy, scipy (+ pytest)
pytest -q                        # 164 tests, about 20 s (record-dependent ones skip without the cache)
circlepack records fetch --tables square   # optional: download a record table (see below)

circlepack run --container square --n 10 --starts 8 --workers 4 --hops 10 --out results/sq10.json
circlepack verify results/sq10.json --exact
```

Real output of the two commands above (8 starts take 1.5 s on a desktop; the
`known ... hits` part appears once the square table has been fetched with
`circlepack records fetch --tables square`):

```text
circlepack 0.1.0: n = 10 in square 1, 8 starts
best r = 0.148204322565229  (seed 3)  known 0.148204322565000  gap -2.287e-13  hits 2/8
wrote results/sq10.json  [1.5s wall]

results/sq10.json
  n = 10  r = 0.14820432256522864
  min pair slack      = -5.551115e-17  (pair (2, 3))
  min container slack = 1.110223e-16
  float check (tol 1e-12): VALID
  exact check, r - 1e-12, primitives from spec (exact): VALID
```

(The Packomania csq table prints 12 decimals, so a gap of order 1e-13 is
rounding, not an improvement.) `python -m circlepack ...` is equivalent to the
`circlepack` console script. From Python:

```python
from circlepack import make_container, run_many, SearchConfig

if __name__ == "__main__":   # needed when workers > 1 (spawn start method)
    res = run_many(make_container("quadrant"), n=12, starts=16, workers=4, cfg=SearchConfig(hops=20))
    print(res.best.r, res.best.X)
```

Full CLI reference: [docs/en/cli.md](docs/en/cli.md).

### Long campaigns

`circlepack campaign {run,status,report,plan}` runs a resumable, load-adaptive
search over many `(Packomania table, n)` targets with SQLite state, atomic best
files, exact verification and comparison against Packomania (from the records
cache) and, optionally, Moki & Julio; `scripts/run_campaign.sh start|status|stop`
launches it detached with sleep inhibited. See [campaigns/README.md](campaigns/README.md).

## Record tables (downloaded, not bundled)

The best-known radii are compiled by E. Specht on
[Packomania](https://www.packomania.com/). circlepack does **not** ship them;
the comparison features (`known` in `run`, `bench`, `records show`) read a
local cache that you fill once:

```bash
circlepack records fetch                       # all 27 supported tables, >= 2 s between requests
circlepack records fetch --tables square,circle
circlepack records list                        # cache status, n range, "Last update" of each table
circlepack records show square --n 1-10 --digits
```

The cache lives in `$CIRCLEPACK_DATA` if set, otherwise in the platform cache
directory (`~/.cache/circlepack/records` on Linux, `~/Library/Caches/circlepack/records`
on macOS, `%LOCALAPPDATA%\circlepack\Cache\records` on Windows). Each table is a
JSON file with the radii as printed on the site and its provenance (source
URL, fetch time, the page's "Last update" date, normalisation, any rows
dropped). Everything else (`run`, `verify`, the Python API) works without the
cache; without a table `run` simply omits the comparison. Details:
[docs/en/cli.md](docs/en/cli.md#records).

## Supported containers

Scales follow Packomania, so results are directly comparable with its tables.

| CLI name | Geometry (Packomania normalisation) | Table |
|---|---|---|
| `square` | side 1, centred at the origin: `[-1/2, 1/2]^2` | csq |
| `rectangle` (`--param height=h`) | `1 x h`, centred at the origin | crc_XXX (`1 x 0.XXX`) |
| `circle` | radius 1, centre at the origin | cci |
| `right_triangle` | legs 1, vertices (0,0), (1,0), (0,1) | crt |
| `quadrant` | circular quadrant, radius 1: `x >= 0, y >= 0, |x| <= 1` | ccq |
| `semicircle` | half disk, radius 1: `y >= 0, |x| <= 1` | csc |
| `pentagon`, `hexagon`, `nonagon`, `dodecagon`, `regular_polygon` (`--param k=K`) | regular k-gon, circumradius 1, flat bottom edge | cpt, chx, chp, coc, cno, cdc, chd, cdd, ctd, crd, cpd, cxd, ced (k = 5..17) |
| `triangle`, `polygon` (via `--spec`) | any (convex) vertices | - |

Custom containers: [docs/en/containers.md](docs/en/containers.md).

## How it works

Each start has three phases: (1) a **soft-to-rigid relaxation**, minimising a
penalised objective over centres and radius while the penalty weight grows
geometrically so that the radius "inflates" from an overlapping, mobile state
into a jammed one; (2) **basin hopping** from the best configuration; (3) a
**polish** that solves the packing problem to machine precision as a
constrained optimisation, with SLSQP (n <= 60) or sparse sequential linear
programming (larger n). The reported radius is always the feasible radius of
the final centres, so the output is feasible by construction. Details:
[docs/en/method.md](docs/en/method.md).

## Exact verification

`circlepack/verify.py` uses only the standard library and can be copied next to
a solution file. In `--exact` mode every float is converted exactly to a
rational, the radius is shrunk to `r - 1e-12`, and all pair, wall and disk
constraints are checked without square roots. VALID is a proof that circles of
that radius at the stored centres form a packing; it is *not* a proof of
optimality. See [docs/en/verification.md](docs/en/verification.md).

## Benchmarks

Everything below is reproducible with `circlepack bench` and the scripts in
`benchmarks/scripts/`; every stored packing in `benchmarks/*/` passes
`verify --exact`. The stored files contain only our results;
`benchmarks/scripts/compare_records.py` prints them next to the known radii
from your local cache. "Hit" means a start reached the Packomania radius within a
relative 1e-9. Hardware: one desktop, 10 worker processes at `nice 10`.

| Container (table) | n | Starts x hops | n reached | Starts hitting |
|---|---|---|---:|---:|
| square (csq) | 10..30 | 40 x 20 | 21/21 | 511/840 (61%) |
| circle (cci) | 10..30 | 40 x 20 | 21/21 | 667/840 (79%) |
| right triangle (crt) | 10..30 | 24 x 20 | 16/21 | 103/504 (20%) |
| quadrant (ccq) | 10..30 | 24 x 20 | 19/21 | 263/504 (52%) |
| rectangle 1x0.3 (crc_300) | 10..40 | 16 x 15 | 27/31 | 45% |
| rectangle 1x0.6 (crc_600) | 10..40 | 16 x 15 | 28/31 | 46% |
| 9-gon (cno) | 10..30 | 16 x 15 | 19/21 | 65% |
| 12-gon (cdd) | 10..30 | 16 x 15 | 19/21 | 64% |
| semicircle (csc) | 10..30 | 16 x 15 | 19/21 | 53% |

Misses are mostly crystalline optima (e.g. 15 circles in the right triangle)
that random starts rarely find; lattice seeding recovers some of them.

**Sparse vs dense polish** (`benchmarks/scripts/polish_compare.py`, identical
global-phase outputs, single process): the sparse SLP polish is 3 to 60 times
faster than SLSQP for n = 100..300 (e.g. square n = 300: 0.54 s vs 33.9 s).
On 12 large cases 7 end in the same optimum (to about 1e-14) and the rest in a
neighbouring one (|diff| <= 5e-6, either sign). On 60 smaller cases (n = 10..60)
SLP matched SLSQP to 1e-12 in 53, was better in 7, never worse.

**Large n** (8 starts x 6 hops): relative gap to the Packomania radius is
5.4e-5 (circle n = 100) up to 3.6e-3 (square and circle n = 200); one n = 300
start takes about 30 s. The remaining 0.1 to 1% gap at large n comes from the
global phase, not the polish.

**Beyond the published tables.** In the rectangle benchmarks some radii exceed
the Packomania values at the time of retrieval (crc_300 n = 22, 29; crc_600
n = 26 by +1.1e-4, +6.9e-5, +3.4e-4 relative, exact-verified at `r - 1e-13`),
and re-polishing a third-party set of packings improved 12 of 1,551 by 1e-10 to
2e-7 relative. These are **candidates only**: they are not submitted, and we do
not know whether other submissions are pending with the record maintainer. We
make no claim of new records until they are submitted and accepted.

**Cross-check.** Packings from the Moki & Julio data set (CC-BY-4.0, not
bundled here) were converted and verified with our verifier;
`benchmarks/scripts/mj_compare.py` reads a local clone for comparison.

## Limitations

- Heuristic search: results are not optimality proofs. The exact verifier
  proves feasibility of the stored packing only.
- Hit rates fall for "irregular" n (e.g. circles in a circle, n >= 25) and at
  n >= 100 a start lands 0.1 to 1% below the records; no dedicated large-n
  strategy is implemented.
- The SLP polish finds first-order stationary points (the optional
  second-order escape is off by default).
- Exact verification of regular polygons uses the stored float primitives
  (irrational vertices): it proves a packing in that float-defined polygon.
- Only convex containers; a GPU backend is not implemented yet.

## Citing and credits

- The soft-to-rigid idea and the minimal stand-alone verifier style are
  inspired by Yohei Nakajima's
  [soft-to-rigid-packing](https://github.com/yoheinakajima/soft-to-rigid-packing).
- Record data and normalisation conventions: Eckard Specht,
  [Packomania](https://www.packomania.com/). The radii are the work of their
  respective discoverers as compiled by E. Specht. circlepack does not
  redistribute them: `circlepack records fetch` downloads them on the user's
  machine, for comparison only, with provenance stored next to each table.
- Moki & Julio
  ([repository](https://github.com/Hashirama1337s/moki-julio-circle-packing))
  published packings with certificates; we used a few of them for an
  independent cross-check.
- Parts of the code and documentation were written with Claude (Anthropic).

If you use this software, please cite the repository (version 0.1.0) and
Packomania for the reference radii.

## License

MIT, see [LICENSE](LICENSE). See also [CHANGELOG.md](CHANGELOG.md) and the
documentation in [docs/en](docs/en) ([docs/it](docs/it) in Italian).
