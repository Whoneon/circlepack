# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-17

Initial release.

### Added

- Containers as intersections of half-planes and disks: square, rectangles,
  regular k-gons (pentagon, hexagon, 9-gon, 12-gon, any k), arbitrary convex
  polygons and triangles, circle, circular quadrant, semicircle, with
  Packomania-compatible normalisation, plus a generic `Container` class.
- Global phase: soft-to-rigid penalty continuation (L-BFGS-B, analytic
  gradient, Verlet neighbour list with a k-d tree) behind a `Backend` protocol
  (`NumpyBackend`), with early abort below the best radius and per-stage
  tolerances; single-`bincount` pair forces.
- Lattice-seeded starts (square and hexagonal, edge-aligned, random vacancies)
  in addition to uniform random starts.
- Basin hopping with jiggle and relocate-to-hole moves.
- Dense NLP polish (SLSQP, trust-constr) with analytic Jacobians and active-set
  refresh; the reported radius is always the feasible radius of the centres.
- Sparse polish by sequential linear programming (HiGHS) with a conservative
  linearisation; selected automatically above n = 60 (`--polish-method auto`).
  3 to 60 times faster than SLSQP for n = 100..300.
- Parallel multi-start driver (spawned workers, niced, capped).
- Stand-alone, standard-library-only verifier with a float mode and an exact
  rational mode (`fractions.Fraction`, no square roots).
- JSON solution format `circlepack/1`.
- Packomania record tables are **not** bundled: `circlepack records fetch`
  (and `circlepack.records.fetch_records`) downloads the summary pages of 27
  tables (csq, cci, crt, ccq, csc, crc_100..crc_800, regular 5..17-gons) with
  the standard library only, a polite delay (>= 2 s) and an identifying
  User-Agent, and stores the radii (all printed digits) with provenance in a
  local cache (`$CIRCLEPACK_DATA` or the platform cache directory). Options
  `--tables`, `--force`, `--delay`, `--offline-from DIR` (parse saved pages),
  `--save-html`, `--dest`. `circlepack records list|show|path`; `records NAME`
  is a shorthand for `records show NAME`.
- Without a cached table `run` prints a note instead of the comparison and
  `bench` stops with "record table X not found; run `circlepack records fetch
  --tables X`"; everything else works offline.
- Command line interface: `run`, `verify`, `bench`, `records`, `campaign`.
- `circlepack campaign {run,status,report,plan}`: resumable, load-adaptive
  multi-target search driver with SQLite state, atomically written best files,
  exact verification of every new best and classification against Packomania
  (records cache, optional CSV override) and, optionally, the Moki & Julio
  claims; `scripts/run_campaign.sh` launches it detached with sleep inhibited.
  Example campaign files in `campaigns/`.
- Test suite (`records` pytest marker: tests needing real record values are
  skipped when the table is not cached; the parser is tested on a synthetic
  page) and benchmark results with scripts (`polish_compare.py`,
  `mj_compare.py`, `compare_records.py`) in `benchmarks/`. The benchmark files
  contain only our own results, no copied record values.
- Bilingual (English and Italian) documentation.

[Unreleased]: https://github.com/Whoneon/circlepack/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Whoneon/circlepack/releases/tag/v0.1.0
