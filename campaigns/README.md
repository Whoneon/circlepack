# Campaigns

Long-running, resumable searches over many `(table, n)` targets
(`circlepack/campaign.py`, references in `circlepack/references.py`).

Files here: `example.toml` (minimal, ~10 min), `smoke.toml` (driver smoke test),
`weekend.toml` (the ~60 h campaign described below).

## Commands

```bash
# from the repository root
circlepack records fetch                                  # Packomania references (once)
scripts/run_campaign.sh start  campaigns/weekend.toml     # detached; dir from the file: runs/weekend
scripts/run_campaign.sh status runs/weekend               # progress, throughput, candidates
scripts/run_campaign.sh log    runs/weekend               # tail -f campaign.log
scripts/run_campaign.sh stop   runs/weekend               # graceful: touch STOP, wait for the driver
python -m circlepack campaign plan campaigns/weekend.toml  # targets per priority, estimated hours
```

Paths in a campaign file (`dir`, `packomania_dir`, `mj_manifest`) are resolved
relative to the campaign file; `~` is expanded. `runs/` is git-ignored.

The wrapper locates the repository from its own path, sets `PYTHONPATH` to this
checkout (so an installed `circlepack` from elsewhere is not picked up), uses
`<repo>/.venv/bin/python` if it exists, else `python3` on `PATH` (override with
`PYTHON=/path/to/python`), and runs the driver under
`setsid nohup systemd-inhibit --what=sleep:idle:handle-lid-switch nice -n 10 ionice -c 3`.
`systemd-inhibit` needs no sudo in a local graphical session (polkit); while the
driver runs, `systemd-inhibit --list` shows a `circlepack` entry, and the
machine will not suspend on idle or lid close. If the inhibitor is not permitted
the wrapper says so and continues. Workers additionally lower themselves to
nice 15 and ionice idle.

Without the wrapper: `PYTHONPATH=$PWD python -m circlepack campaign run <file> [--dir DIR]`
(foreground; Ctrl-C = graceful stop, a second Ctrl-C kills the running starts).

## Output directory

| path | content |
|---|---|
| `state.sqlite` | all state (SQLite, WAL): targets, units, events, meta |
| `best/<table>/<table>_n<n>.json` | best packing per target (circlepack/1 JSON, written atomically) |
| `candidates/<table>_n<n>_r<r>.json` | copies of record candidates / marginal beats |
| `REPORT.md` | Markdown report, rewritten every `report_every` s (15 min) and on stop |
| `campaign.log` | driver log (one line per unit, `***` lines for candidates) |
| `campaign.lock`, `campaign.pid` | lock held by the running driver, its pid |
| `STOP` | create it to stop gracefully (removed at the next start) |

## How it works

* **Targets** come from `[[job]]` entries: `table` (Packomania code), `n`
  (`"10-48"`, `"10-max"` = up to the last n of the Packomania table, list or
  int), `priority`, `starts` (start budget per target), `hops` (basin-hopping
  moves per start), `skip_mj` / `only_mj` (drop / keep only n with a Moki &
  Julio entry), `idle_only` (run only when nothing else is runnable), optional
  `container` spec (default: Packomania normalisation, `references.TABLE_SPECS`).
  A target listed by several jobs keeps the highest-priority one.
* **Unit** = one target and a block of consecutive seeds, sized so it takes
  `unit_seconds` (300 s): seconds/start is measured per target after 3 starts,
  before that a built-in model x `contention`. A unit stops early (between
  starts) on `STOP`, on SIGTERM/SIGINT, or after `3 x unit_seconds`.
* **Scheduling**: score = `rounds x f + priority_lag x (priority - 1)` (lowest
  first), `rounds` = units done + in flight. So every target gets one unit
  before any gets two, and priority class `p+1` starts when class `p` targets
  have `priority_lag` (2) rounds. Deepening: `f = 1 + hits/4` (capped at 3), so
  targets that already reach the reference often are revisited less; near misses
  (no hit, relative gap < 1e-6) get `f x 0.75`.
* **Adaptive concurrency** (re-evaluated every `adapt_every` = 60 s):
  `workers = clamp(cpu_count - reserve_cpus - round(load1 - own_running), min_workers, max_workers)`
  = `clamp(16 - 2 - foreign load, 8, 12)` for `weekend.toml` on a 16-thread machine; if `MemAvailable < min_mem_gib`
  (2 GiB) it shrinks to (running - 1), down to 1. Running units are never
  killed for this; the pool shrinks as units finish (<= 5-10 min).
* **Resume**: seeds are reserved in the DB before a unit is submitted, so a
  seed is never run twice; units left `running` by a killed driver become
  `lost` (their starts are not counted). Best files are written (tmp + fsync +
  rename) before the DB commit; on start the driver adopts any best file better
  than the DB and re-classifies all bests against the current references.
  Changing budgets/priorities in the campaign file and restarting keeps all
  progress.
* **References**: Packomania from the records cache (`circlepack records fetch`,
  `$CIRCLEPACK_DATA` or the platform cache directory); an optional
  `[references] packomania_dir` with `<table>.csv` files (columns `n,radius`)
  overrides the cache table by table. Moki & Julio `new_radius` comes from their
  `MANIFEST.csv` if `[references] mj_manifest` is set (optional; without it there
  is no M&J reference, `skip_mj` is a no-op and `only_mj` jobs are empty).
  Every new best is verified (float + exact rational with `r - 1e-12`;
  regular polygons use the stored float half-planes, as the verifier states)
  and classified against `max(packomania, moki_julio)`:
  `RECORD CANDIDATE` = exact-verified and `r > best (1 + 1e-12)` by more than
  one unit of the reference's last printed digit (polygon tables print only 12
  decimals, so smaller "beats" may be truncation artefacts); `MARGINAL` = the
  same but within that printed precision; `MATCH` = within 1e-9; `BELOW`.
* `[[override]]` entries (`table`, `n`, `packomania` / `moki_julio`) replace a
  reference for testing (see `smoke.toml`); they never modify the data.

## weekend.toml

`python -m circlepack campaign plan campaigns/weekend.toml` (20 hops/start,
cost model x 1.5 contention; real speed under the user's other load will vary):

| priority | what | targets | starts/target | worker-hours | h at 10 workers |
|---|---|---:|---:|---:|---:|
| P1 | regular 7, 9, 10, 11, 12, 13, 14, 17-gons (chp cno cdc chd cdd ctd crd ced), n = 10-48 (Packomania tables end at 48); none has M&J entries | 312 | 800 | 542 | 54 |
| P2 | crc_100..crc_800, csc, crt, ccq, n = 10-80 without M&J entry | 641 | 600 | 1143 | 114 |
| P3 | same tables, n = 81-200 without M&J entry | 699 | 300 | 1694 | 169 |
| P4 | same tables, n = 10-200 *with* M&J entry (confirmation, idle only) | 761 | 64 | 368 | 37 |

Total ~3700 worker-hours, far more than a weekend (~600 worker-hours at 10
workers for 60 h), by design: the scheduler gives every P1 target one ~5-min
unit in the first ~2.6 h, two by ~5 h, then interleaves P2 coverage (P2 fully
covered once after ~13 h at 10 workers, P3 after ~35 h), and then deepens.
P4 runs only if everything else is exhausted.

The target counts above assume the full records cache and the Moki & Julio
manifest; set `mj_manifest` in `[references]` to reproduce them (without it P2
and P3 include the M&J n as well and P4 is empty).

## smoke.toml

Six small targets, a few minutes. Its `[[override]]` lowers the crc_300 n = 12
reference to 0.07 to produce a simulated `RECORD CANDIDATE`; crc_300 n = 22 is
a genuine one (r = 0.0568355387 vs Packomania 0.0568291964, found before).
