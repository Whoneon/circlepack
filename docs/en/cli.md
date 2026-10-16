# Command-line reference

[Italiano](../it/cli.md) | [README](../../README.md)

Invoke as `circlepack ...` (console script) or `python -m circlepack ...`.
Global options: `-h/--help`, `--version`.

```
circlepack {run,verify,bench,records} ...
```

## Container selection (`run`, `bench`)

| Option | Meaning |
|---|---|
| `--container NAME` | one of `circle, dodecagon, hexagon, nonagon, pentagon, polygon, quadrant, rectangle, regular_polygon, right_triangle, semicircle, square, triangle` (default `square`) |
| `--param KEY=VALUE` | container parameter, repeatable; value parsed as JSON, e.g. `--param height=0.5`, `--param k=7` |
| `--spec JSON_OR_FILE` | container spec as a JSON string or a path to a JSON file; overrides `--container`. See [containers.md](containers.md) |

A Packomania record table is matched automatically for `square`, `circle`,
`right_triangle`, `quadrant`, `semicircle`, regular k-gons with k = 5..17
(`pentagon`, ..., `regular_polygon --param k=K`, circumradius 1, default
rotation), and `rectangle` with width 1 and height 0.1, 0.2, ..., 0.8.
`--spec` containers never have a record. The table must have been downloaded
with [`records fetch`](#records); if it is missing, `run` prints a note and
skips the comparison, while `bench` stops with an error.

## Search options (`run`, `bench`)

| Option | Default | Meaning |
|---|---|---|
| `--starts N` | 32 | independent starts |
| `--workers N` | `min(10, cpu_count - 2)` | worker processes |
| `--seed S` | 0 | first seed (start `i` uses seed `S + i`) |
| `--hops N` | 20 | basin-hopping moves per start |
| `--patience N` | none | stop hopping after N non-improving moves |
| `--polish-method M` | `auto` | `auto`, `SLSQP`, `trust-constr`, `sparse`, `slp` (`sparse` is an alias of `slp`); `auto` = SLSQP for n <= 60, SLP above |
| `--nice N` | 10 | niceness of the process and workers |
| `--quiet` | off | suppress progress output |

## `run`

Multi-start search for one `n`.

```
circlepack run --n N [container and search options] [--out FILE_OR_DIR]
```

`--out`: a `.json` file, or a directory (default `results/`); the file name is
`<table or custom>_n<N>.json`. Prints the best radius and, when a record table
is cached, the known value, gap and hits. Progress goes to stderr.

```
$ circlepack run --container square --n 10 --starts 8 --workers 4 --hops 10 --quiet --out results/sq10.json
circlepack 0.1.0: n = 10 in square 1, 8 starts
[total 1.5s]
best r = 0.148204322565229  (seed 3)  known 0.148204322565000  gap -2.287e-13  hits 2/8
wrote results/sq10.json  [1.5s wall]
```

More examples:

```bash
circlepack run --container rectangle --param height=0.5 --n 30
circlepack run --container regular_polygon --param k=7 --n 15
circlepack run --container square --n 300 --starts 8 --polish-method auto
circlepack run --spec '{"type": "polygon", "vertices": [[0,0],[3,0],[2,1],[0,1]]}' --n 10
```

## `verify`

```
circlepack verify FILE [FILE ...] [--tol TOL] [--exact] [--eps EPS]
```

| Option | Default | Meaning |
|---|---|---|
| `--tol` | 1e-12 | float-mode tolerance on the minimum slack |
| `--exact` | off | also run the exact rational check |
| `--eps` | 1e-12 | exact mode: radius is reduced to `r - eps` |

Exit status 0 if every file is VALID, 1 otherwise. The same verifier runs
stand-alone: `python circlepack/verify.py FILE --exact`. See
[verification.md](verification.md).

## `bench`

Runs `run` for a range of `n` against the record table of the container (the
container must have one and it must be in the cache: `circlepack records fetch
--tables NAME`).

```
circlepack bench [container and search options] [--n RANGE] [--rtol RTOL] [--out DIR]
```

| Option | Default | Meaning |
|---|---|---|
| `--n` | `10-30` | range or list, e.g. `10-30` or `5,7,12` |
| `--rtol` | 1e-9 | relative tolerance for a "hit" |
| `--out` | `results/bench_<table>` | output directory (one JSON per n plus `summary.json`) |

Prints a Markdown table (`n | known best | ours | gap | hits | s/start`), flagging
`**NEW?**` when the radius exceeds the record by more than 1e-11 relative; such
a flag is only a prompt to verify, not a claim.

## `records`

Packomania tables are **not** distributed with circlepack. They are downloaded
on demand into a local cache and read from there.

```
circlepack records [list]                         # supported tables and cache status
circlepack records fetch [--tables NAMES] [...]   # download into the cache
circlepack records show NAME [--n RANGE] [--digits]  # print "n radius" (default n = 1-30)
circlepack records NAME [--n RANGE]               # short for `records show NAME`
circlepack records path                           # print the cache directory
```

Table names (Packomania code in brackets): `square` (csq), `circle` (cci),
`right_triangle` (crt), `quadrant` (ccq), `semicircle` (csc),
`rectangle_0.1` ... `rectangle_0.8` (crc_100 ... crc_800), `pentagon` (cpt),
`hexagon` (chx), `heptagon` (chp), `octagon` (coc), `nonagon` (cno),
`decagon` (cdc), `hendecagon` (chd), `dodecagon` (cdd), `tridecagon` (ctd),
`tetradecagon` (crd), `pentadecagon` (cpd), `hexadecagon` (cxd),
`heptadecagon` (ced). Names and codes are both accepted.

### `records fetch`

| Option | Default | Meaning |
|---|---|---|
| `--tables NAMES` | all | comma-separated names or codes, repeatable (`all` = every table) |
| `--force` | off | re-download tables that are already cached |
| `--delay S` | 2.5 | seconds between two requests; never less than 2 |
| `--offline-from DIR` | - | parse pages saved earlier in `DIR` (`<code>.html`, `<code>_<page>.html` or the site layout `<code>/<page>`) instead of downloading |
| `--save-html DIR` | - | also keep a copy of every downloaded page |
| `--dest DIR` | cache | write to `DIR` instead of the cache directory |
| `--timeout S` | 30 | network timeout per request |

Only the summary page of each table is requested (one request per table,
e.g. `https://www.packomania.com/csq/csq.html`), with a `User-Agent`
identifying circlepack. Network errors are reported per table (exit status 1)
and do not stop the other tables; already cached tables are skipped.

**Cache location**: `$CIRCLEPACK_DATA` if set; otherwise
`$XDG_CACHE_HOME/circlepack/records` (default `~/.cache/circlepack/records`) on
Linux, `~/Library/Caches/circlepack/records` on macOS and
`%LOCALAPPDATA%\circlepack\Cache\records` on Windows.

**Cache layout**: one file `<code>.json` per table, e.g. `csq.json`:

```json
{"format": "circlepack-records/1", "name": "square", "code": "csq",
 "source_url": "https://www.packomania.com/csq/csq.html",
 "retrieved_from": "https://www.packomania.com/csq/csq.html",
 "fetched_at": "2026-10-16T14:17:04+00:00", "table_last_update": "10-Sep-2026",
 "normalization": "square of side 1, [-1/2, 1/2]^2", "notes": [],
 "attribution": "...", "n_min": 1, "n_max": 9996, "count": 3147,
 "proven_optimal": [1, 2, ...], "radii": {"1": "0.500000000000", ...}}
```

Radii are kept as strings with every digit printed on the site (12 or 30
decimals depending on the table). Normalisations applied while parsing (listed
in `notes`): duplicate rows for the same n keep the larger radius (crt n = 166,
294; crc_100 n = 88); the n = 1 rows of cno and cdc are dropped because they are
inconsistent with the circumradius-1 convention of the other rows.
`proven_optimal` lists the n whose radius is printed in bold on the site.

From Python:

```python
from circlepack.records import fetch_records, load_records, known_radius, load_table_meta

fetch_records(["square"])               # same as the CLI; returns {name: status}
known_radius("square", 10)              # float, or None if n is not in the table
load_records("csq")[10]                 # exact string as printed
```

A missing table raises `RecordTableMissing` ("record table X not found; run
`circlepack records fetch --tables X`").

```
$ circlepack records show square --n 2-4 --digits
2 0.292893218813
3 0.254333095030
4 0.250000000000
```
