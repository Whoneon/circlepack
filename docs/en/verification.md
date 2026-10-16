# Verification

[Italiano](../it/verification.md) | [README](../../README.md)

`circlepack/verify.py` is a single file using only the Python standard library.
It can be copied next to any solution file and run as
`python verify.py solution.json [--tol 1e-12] [--exact] [--eps 1e-12]`, or via
`circlepack verify`. Exit status is 0 if VALID, 1 otherwise; unreadable files are
reported as errors rather than crashing.

## Float mode

For every pair, `slack = |x_i - x_j| - 2r`; for every half-plane,
`(b - a.x)/|a| - r`; for every disk, `R - |x - c| - r`. The report shows the
minimum pair slack (with the worst pair) and minimum container slack, and the
packing is VALID if both are `>= -tol` (default 1e-12) and `r > 0`. This is a
numerical check subject to floating-point rounding (slacks of -5e-17 are
typical for touching circles).

## Exact mode (`--exact`)

Every float in the file is converted *exactly* to a `fractions.Fraction`. The
radius is reduced to `r' = r - eps` (`eps` rational, default 1e-12). Then,
without any square root:

- pairs: `|x_i - x_j|^2 >= (2 r')^2`
- half-planes: `b - a.x >= 0` and `(b - a.x)^2 >= r'^2 |a|^2`
- disks: `R - r' >= 0` and `|x - c|^2 <= (R - r')^2`

**Primitives.** For containers whose `spec` has rational data (square,
rectangle, polygon, triangle, right isosceles triangle, circle, quadrant,
semicircle) the half-planes and disks are rebuilt exactly from the `spec`
(e.g. the hypotenuse of the right triangle is exactly `x + y <= 1`), so the
check refers to the true container. For other specs (regular polygons, whose
vertices are irrational) the stored float primitives are used and the output
says `primitives from stored float primitives`.

## What is proved

- VALID in exact mode proves that circles of radius `r - eps` centred at the
  stored binary floating-point centres lie inside the container and do not
  overlap. For rational containers, "the container" is the exact one.
- For regular polygons it proves the same statement for the polygon defined by
  the stored float half-planes, which differs from the ideal regular polygon by
  rounding (about 1e-16).

## What is not proved

- Not optimality: nothing here says a larger `r` is impossible.
- The `r - eps` reduction means the claim is about `r - 1e-12`, not `r`; this
  absorbs the rounding of the stored `r`.
- The verifier trusts the input: it does not check that the `halfplanes` and
  `disks` match the `spec` in float mode, and Python's `Fraction`/`float`
  implementations are assumed correct.
- Cost is O(n^2) rational operations for the pairs; this is fast for n in the
  hundreds.
