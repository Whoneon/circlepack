# Method

[Italiano](../it/method.md) | [README](../../README.md)

## Problem

Given a convex container `K` and an integer `n`, find centres `x_1..x_n` and
the largest `r` such that

```
maximise   r
subject to |x_i - x_j| >= 2 r                  for i < j        (no overlap)
           a_k . x_i + r <= b_k                for every half-plane k, |a_k| = 1
           |x_i - c_k| + r <= R_k              for every disk k
```

`K` is the intersection of half-planes `{a_k . x <= b_k}` and disks
`{|x - c_k| <= R_k}` (normals are normalised on construction). A circle of
radius `r` centred at `x` lies in `K` iff it satisfies the wall conditions
above; this is exact for convex primitives. The container never changes size
(Packomania convention): equal circles are maximised in a fixed container.

## Phase 1: soft-to-rigid relaxation

Let `s` be the radius of `n` disks whose total area equals the container area.
For a penalty weight `mu`, minimise over `(X, r)`

```
f = -r/s + (mu/n) E(X, r) / s^2
E = sum_{i<j}  max(0, 2r - d_ij)^2
  + sum_{i,k}  max(0, a_k.x_i + r - b_k)^2
  + sum_{i,k}  max(0, |x_i - c_k| + r - R_k)^2
```

with L-BFGS-B and the analytic gradient (`energy.py`), over a geometric schedule
`mu = 0.5, 2, 8, ...` (factor 4), each stage warm-started from the previous one.
At small `mu` the disks are soft and overlap by about `s/mu`; as `mu` grows they
harden and `r` decreases towards a rigid local optimum. This is the circle
analogue of the soft-to-rigid idea of Nakajima: the radius "inflates" from a
heavily overlapping, mobile state into a jammed one. The schedule ends at
`mu = 1e3` when every candidate is polished afterwards, otherwise at `1e10`.

Starting points are uniform random points (75%) or a square or hexagonal lattice
cut by the container, aligned with a random edge, with random vacancies (25%;
these enter the schedule at `mu = 30`). Lattice seeds matter for containers with
crystalline optima, e.g. 15 = 1+2+3+4+5 circles in the right isosceles triangle.

Pair terms use a Verlet neighbour list (cutoff `2r(1 + skin)`, built with a
k-d tree, rebuilt only when some centre has moved half the skin), so the energy
is exact while each evaluation costs O(n). Pair forces are scattered with a
single `bincount`.

## Phase 2: basin hopping

From the best configuration, either *jiggle* all centres (Gaussian, about 0.35 r)
or *relocate* 1 to 3 circles (the ones with most slack, i.e. rattlers, or
random ones) into the largest holes (found by sampling candidate points and
maximising clearance to the other centres and the walls). The configuration is
re-relaxed from a softness drawn log-uniformly in `mu in [1, 100]`, polished,
and accepted if the radius improves. A hop is abandoned early once its penalty
radius falls below the current best at `mu >= 100`. Dense polish methods
polish every hop only for n <= 150; the sparse polish is cheap enough to be
used for every candidate.

## Phase 3: polish

The polish solves the original constrained problem to machine precision. The
reported radius is always the **feasible radius** of the final centres,
`min(min_ij d_ij / 2, min_i clearance(x_i))`, so the output is feasible by
construction (up to rounding) and the polish never makes a result worse.

### Dense: SLSQP with analytic Jacobians (n <= 60, default)

Maximise `r` over `(X, r)` with SLSQP, keeping only near-active constraints:

```
pairs        (|x_i - x_j|^2 - 4 r^2) / (4 r_ref)  >= 0
half-planes   b - a.x - r                          >= 0
disks        ((R - r)^2 - |x - c|^2) / (2 R)       >= 0
```

with analytic Jacobians. The active set is refreshed and the solve repeated
until it is stable. `trust-constr` (sparse Jacobian, exact sparse Lagrangian
Hessian) is available but did not converge at n = 300 in reasonable time and is
not used by default.

### Sparse: sequential LP with HiGHS (`circlepack/slp.py`, n > 60)

Around the current feasible point, in a box trust region `|dx_i|_inf <= delta`,
every constraint whose slack is within reach of a step of that size is
linearised. The LP in the scaled step `dX = delta * xi` and `dr = delta * sigma`:

```
max   sigma
s.t.  -u_ij . (xi_i - xi_j) + 2 sigma <= (d_ij - 2 r) / delta          pairs
       a_k . xi_i + sigma             <= (b_k - a_k.x_i - r) / delta    half-planes
       v_ik . xi_i + sigma            <= (R_k - |x_i - c_k| - r) / delta  disks
       -1 <= xi <= 1,   0 <= sigma <= sigma_max
```

has `2n + 1` variables and `O(n)` rows with at most 5 non-zeros each; HiGHS
(`scipy.optimize.linprog`, sparse `A_ub`) solves it in milliseconds.

**Why the linearisation is conservative.** The distance `|x_i - x_j|` is a convex
function of the centres, so it lies above its tangent plane:
`d(x + dx) >= d + u . dx`. The linearised pair constraint therefore
under-estimates the true slack and a step that is feasible for the LP is
feasible for the pairs. Half-plane constraints are linear (exact). The disk
wall `R - |x - c|` is concave in `x`, so the tangent over-estimates it; the
second-order bound `delta^2 / |x - c|` is subtracted from the disk rows to
restore conservatism. Hence the true feasible radius after a step is never below
the LP prediction. A step is nevertheless accepted only if the exact feasible
radius increases.

The trust region doubles when the step bounds carry non-zero reduced costs (the
box limits the gain) and shrinks by 4 when the LP optimum is interior
(Newton-like regime; this keeps the LP tolerances, relative to `delta`, from
limiting the last digits). The iteration stops when the LP predicts no gain
(`dr <= 1e-15 r`); typically 4 to 30 LPs. SLP finds first-order stationary
points. An optional second-order escape (`polish_slp(..., escapes=k)`) exists
but never improved a result in our tests and is off by default.

## Parallelism and the backend seam

Starts are independent and run in a `ProcessPoolExecutor` (spawn context,
`os.nice(10)`, default `min(10, cpu_count - 2)` workers, BLAS forced to one
thread: multithreaded BLAS makes the tiny vectorised operations about 100 times
slower). The global phase sits behind `circlepack.backend.Backend`, see
[contributing.md](contributing.md).

## Complexity notes

- Penalty evaluation: O(n) with the Verlet list (plus a k-d tree rebuild
  O(n log n) when the skin is exhausted).
- Dense SLSQP polish: roughly cubic in the number of variables (`2n + 1`); n = 300
  takes 10 to 35 s.
- Sparse SLP polish: one sparse LP of `2n + 1` variables per iteration,
  milliseconds each; n = 300 in about 0.5 s.
- At large n the global phase dominates: profiling an n = 300 start shows more
  than 90% of the time in L-BFGS on the penalty (about 13k evaluations per
  relaxation). A start with 6 hops takes about 30 s.
- Exact verification is O(n^2) rational operations on the pairs.
