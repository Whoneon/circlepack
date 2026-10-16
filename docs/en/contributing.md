# Contributing

[Italiano](../it/contributing.md) | [README](../../README.md)

## Development setup

```bash
git clone https://github.com/Whoneon/circlepack.git circlepack && cd circlepack
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest -q                 # 164 tests, about 20 s
pytest -q -m "not slow"   # skip the longer optimisation tests
```

Python >= 3.10, NumPy >= 1.24, SciPy >= 1.10. BLAS threads are forced to 1 on
import (`circlepack/__init__.py`); set `OPENBLAS_NUM_THREADS` etc. explicitly if
you really want otherwise.

## Tests

`tests/` covers containers (n = 1 radii against the closed-form inradius and,
when cached, the Packomania table), the record cache and its parser, analytic Jacobians against finite differences, the sparse polish, the
verifier (float, exact, malformed files), the pipeline and known optima.

Tests never use the network. The parser is tested on a hand-written page with
made-up numbers (`tests/data/packomania/csq.html`). Tests that compare with
real Packomania radii are marked `@pytest.mark.records("name", ...)` and are
skipped, with the fetch command in the reason, when the table is not in the
cache. To run them, fill a cache once and point `CIRCLEPACK_DATA` at it:

```bash
CIRCLEPACK_DATA=~/.cache/circlepack/records pytest -q -rs   # or just `pytest` (default cache)
CIRCLEPACK_DATA=$(mktemp -d) pytest -q                      # behaviour without data
```

The suite must pass in both modes. Never commit record values copied from
Packomania (tables, fixtures or benchmark columns); tests use closed-form
optima or the cache.
Run the benchmarks only when you change the search: `circlepack bench` on at
least csq, cci, crt and ccq for n = 10..30, then compare against
`benchmarks/*/summary.json`. Any packing you add to `benchmarks/` must pass
`circlepack verify --exact`.

## Style

- Type hints and `from __future__ import annotations`; short docstrings that
  state the maths or the convention.
- Vectorised NumPy in hot paths; no Python loops over pairs.
- The verifier (`verify.py`) must stay standard-library only.
- Keep scale conventions explicit; never change a normalisation silently.

## Adding a container type

1. In `circlepack/containers.py`, write a constructor returning a `Container`
   (half-planes `A x <= b`, disks `C`, `R`) with a `spec` dict
   `{"type": "<name>", ...params}` that rebuilds it.
2. Register it in `_FACTORIES` (and in `CONTAINER_NAMES` for a short CLI name
   with default parameters). If Packomania has a matching table, add it to
   `PACKOMANIA`.
3. For exact verification with a rational container, add the type to
   `exact_primitives` in `circlepack/verify.py` (rational data only; otherwise
   the stored float primitives are used).
4. If Packomania has a table for it, add a `Table` entry (name, code, page path,
   normalisation) to `circlepack/records.py` and extend `record_key` in
   `cli.py`; check with `circlepack records fetch --tables NAME` that the page
   parses and that n = 1 matches the inradius. Do not commit the data.
5. Add tests in `tests/test_containers.py` and a verify test.

## Adding a GPU backend through the `backend.py` seam

The global phase is the only part behind the seam:

```python
class Backend(Protocol):
    name: str
    def relax(self, container, X, r, scale, mus, r_floor=None) -> (X, r):
        """X: (B, n, 2), r: (B,) -- a whole batch of starts."""
```

`NumpyBackend` loops over the batch with SciPy L-BFGS-B. A PyTorch/JAX backend
would hold all `B` starts as one `(B, n, 2)` tensor, evaluate the penalty `E`
with batched pair distances (dense for small n, cell lists for large n) and
run a batched first-order optimiser (FIRE, Adam, batched L-BFGS) through the
same `mu` schedule, masking out starts whose radius drops below `r_floor`.
Basin hopping, polishing and verification do not change.

To add one: implement a class with `name` and `relax`, add it to `_BACKENDS`
in `circlepack/backend.py` (`get_backend(name, **kw)` instantiates it; `run_start` passes the keyword arguments shown in `search.py`, `floor_mu`, `ftol` and `ftol_final`, so accept or ignore them), select it with
`SearchConfig(backend="<name>")`, keep torch/jax an *optional* dependency
(imported lazily), and test that the polished radii agree with the NumPy backend
on small cases. Note that `run_start` currently calls `relax` per start; to
exploit batching, the driver must group starts, which is the main integration
work.

## Pull requests

Keep changes focused, include tests, update `CHANGELOG.md` under
`[Unreleased]`, and do not commit data you do not have the right to
redistribute.
