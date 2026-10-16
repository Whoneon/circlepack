# Solution file format

[Italiano](../it/file-format.md) | [README](../../README.md)

Solutions are JSON files with `"format": "circlepack/1"`, written by
`circlepack run` / `bench` (`solution.py`) and read by `verify`.

| Key | Type | Meaning |
|---|---|---|
| `format` | string | always `circlepack/1` |
| `container.name` | string | human-readable name |
| `container.spec` | object | `{"type": ..., params}` that rebuilds the container; also used by the verifier to rebuild rational primitives |
| `container.halfplanes` | `[[a1, a2, b], ...]` | `a . x <= b` (unit normals) |
| `container.disks` | `[[cx, cy, R], ...]` | `|x - c| <= R` |
| `n` | integer | number of circles (must equal `len(centers)`) |
| `r` | float | common radius |
| `centers` | `[[x, y], ...]` | circle centres |
| `meta` | object | free-form provenance (generator, seed, starts, hops, wall time, record table and, if the table was cached, known best) |

Floats are written with `repr` precision (17 significant digits), so files
round-trip exactly. The stand-alone verifier needs only `container.halfplanes`,
`container.disks` (and `container.spec` for exact rational primitives),
`centers`, `r` and optionally `n`.

Example (abridged: a real file has 10 centres and is pretty-printed with one
number per line):

```json
{
 "format": "circlepack/1",
 "container": {
  "name": "square 1",
  "spec": {"type": "square", "side": 1.0},
  "halfplanes": [[1.0, 0.0, 0.5], [-1.0, 0.0, 0.5], [0.0, 1.0, 0.5], [0.0, -1.0, 0.5]],
  "disks": []
 },
 "n": 10,
 "r": 0.14820432256522864,
 "centers": [[0.35179567743477086, -0.24091158209230082],
             [0.343720034134077, 0.35179567743477125]],
 "meta": {"generator": "circlepack 0.1.0", "seed": 3, "starts": 8, "first_seed": 0,
          "hops": 10, "wall_seconds": 1.5, "record_table": "square", "known_best": 0.148204322565}
}
```

Python API: `circlepack.solution.save_solution(path, container, X, r, meta)` and
`load_solution(path) -> (container, X, r, meta)`.
