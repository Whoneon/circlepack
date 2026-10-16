"""Command line interface: ``python -m circlepack {run,verify,bench,records,campaign}``."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__
from .containers import CONTAINER_NAMES, make_container
from .polish import POLISH_METHODS
from .parallel import default_workers, print_progress, run_many
from . import records as _records
from .records import POLYGON_TABLES, TABLES, RecordTableMissing, known_radius
from .search import SearchConfig
from .solution import save_solution


def _parse_params(items: list[str] | None) -> dict:
    out: dict = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--param expects key=value, got {it!r}")
        k, v = it.split("=", 1)
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def record_key(name: str, params: dict) -> str | None:
    """Name of the Packomania record table matching this container, if one is supported.

    The table itself may still have to be downloaded (``circlepack records fetch``).
    """
    if name == "rectangle":
        w, h = float(params.get("width", 1.0)), float(params.get("height", 1.0))
        if w == 1.0 and h == 1.0:
            return "square"
        key = f"rectangle_{h:g}" if w == 1.0 else None
        return key if key in TABLES else None
    if name in ("regular_polygon", "pentagon", "hexagon", "nonagon", "dodecagon"):
        k = int(params.get("k", CONTAINER_NAMES[name][1].get("k", 6) if name != "regular_polygon" else 6))
        if float(params.get("circumradius", 1.0)) != 1.0 or "rotation" in params:
            return None
        return POLYGON_TABLES.get(k)
    if params:
        return None
    return name if name in TABLES else None


def _optional_record(rkey: str | None, n: int) -> float | None:
    """Known radius for ``run`` (informational): a missing cache is only a note."""
    if not rkey:
        return None
    try:
        return known_radius(rkey, n)
    except RecordTableMissing as e:
        print(f"note: {e} to compare with the best known radius", file=sys.stderr)
        return None


def _build(args):
    params = _parse_params(args.param)
    if args.spec:
        spec = json.loads(Path(args.spec).read_text()) if os.path.exists(args.spec) else json.loads(args.spec)
        return make_container(**spec), None
    if args.container not in CONTAINER_NAMES:
        raise SystemExit(f"unknown container {args.container!r}; choose from {sorted(CONTAINER_NAMES)}")
    return make_container(args.container, **params), record_key(args.container, params)


def _cfg(args) -> SearchConfig:
    return SearchConfig(hops=args.hops, patience=args.patience, polish_method=args.polish_method)


def _nice(level: int) -> None:
    if level and hasattr(os, "nice"):
        try:
            os.nice(level)
        except OSError:
            pass


def _add_search_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--container", default="square", help=f"one of {sorted(CONTAINER_NAMES)}")
    p.add_argument("--param", action="append", metavar="KEY=VALUE",
                   help="container parameter, e.g. --param height=0.5 or --param k=7")
    p.add_argument("--spec", help="container spec as JSON string or file (overrides --container)")
    p.add_argument("--starts", type=int, default=32)
    p.add_argument("--workers", type=int, default=None, help=f"default {default_workers()}")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--hops", type=int, default=20, help="basin-hopping moves per start")
    p.add_argument("--patience", type=int, default=None)
    p.add_argument("--polish-method", default="auto", choices=list(POLISH_METHODS),
                   help="auto = dense SLSQP for n <= 60, sparse SLP (HiGHS) above")
    p.add_argument("--nice", type=int, default=10)
    p.add_argument("--quiet", action="store_true")


def cmd_run(args) -> int:
    container, rkey = _build(args)
    _nice(args.nice)
    cfg = _cfg(args)
    rec = _optional_record(rkey, args.n)
    print(f"circlepack {__version__}: n = {args.n} in {container.name}, {args.starts} starts", file=sys.stderr)
    res = run_many(container, args.n, args.starts, workers=args.workers, cfg=cfg, seed=args.seed,
                   nice=args.nice, progress=None if args.quiet else print_progress)
    best = res.best
    meta = {"generator": f"circlepack {__version__}", "seed": best.seed, "starts": args.starts,
            "first_seed": args.seed, "hops": args.hops, "wall_seconds": round(res.seconds, 3),
            "record_table": rkey, "known_best": rec}
    out = Path(args.out) if args.out else Path("results") / f"{rkey or 'custom'}_n{args.n}.json"
    if out.suffix != ".json":
        out = out / f"{rkey or 'custom'}_n{args.n}.json"
    save_solution(out, container, best.X, best.r, meta)
    line = f"best r = {best.r:.15f}  (seed {best.seed})"
    if rec:
        line += f"  known {rec:.15f}  gap {rec - best.r:+.3e}  hits {res.hits(rec)}/{args.starts}"
    print(line)
    print(f"wrote {out}  [{res.seconds:.1f}s wall]")
    return 0


def cmd_verify(args) -> int:
    from .verify import main as vmain

    argv = list(args.files) + ["--tol", str(args.tol), "--eps", args.eps] + (["--exact"] if args.exact else [])
    return vmain(argv)


def _parse_range(s: str) -> list[int]:
    out: list[int] = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def cmd_bench(args) -> int:
    container, rkey = _build(args)
    if rkey is None:
        raise SystemExit("bench needs a container with a Packomania record table (see `circlepack records list`)")
    try:
        _records.load_records(rkey)
    except RecordTableMissing as e:
        raise SystemExit(f"error: {e}") from None
    _nice(args.nice)
    cfg = _cfg(args)
    outdir = Path(args.out or f"results/bench_{rkey}")
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    hdr = f"| n | known best | ours | gap | hits | s/start |\n|---:|---:|---:|---:|---:|---:|"
    print(f"benchmark: {container.name} ({rkey}), {args.starts} starts, {args.hops} hops/start")
    print(hdr)
    for n in _parse_range(args.n):
        rec = known_radius(rkey, n)
        res = run_many(container, n, args.starts, workers=args.workers, cfg=cfg, seed=args.seed,
                       nice=args.nice, progress=None)
        best = res.best
        cpu = sum(r.seconds for r in res.results) / len(res.results)
        save_solution(outdir / f"{rkey}_n{n}.json", container, best.X, best.r,
                      {"generator": f"circlepack {__version__}", "seed": best.seed, "known_best": rec})
        gap = (rec - best.r) if rec else float("nan")
        hits = res.hits(rec, args.rtol) if rec else 0
        row = {"n": n, "known": rec, "ours": best.r, "gap": gap, "hits": hits, "starts": args.starts,
               "sec_per_start": cpu, "wall": res.seconds}
        rows.append(row)
        flag = "  **NEW?**" if rec and best.r > rec * (1 + 1e-11) else ""
        print(f"| {n} | {rec:.12f} | {best.r:.12f} | {gap:+.1e} | {hits}/{args.starts} | {cpu:.2f} |{flag}",
              flush=True)
    (outdir / "summary.json").write_text(json.dumps(rows, indent=1) + "\n")
    tot = sum(r["hits"] > 0 for r in rows)
    print(f"\nreached known best (rtol {args.rtol:g}) for {tot}/{len(rows)} values of n; "
          f"summary in {outdir / 'summary.json'}")
    return 0


def cmd_records_list(args) -> int:
    print(f"# record tables (cache: {_records.cache_dir()})")
    for name in _records.supported():
        t = TABLES[name]
        try:
            m = _records.load_table_meta(name)
            state = f"{m['count']} radii, n = {m['n_min']}..{m['n_max']}, last update {m['table_last_update']}"
        except RecordTableMissing:
            state = "not fetched"
        print(f"{name:<15} {t.code:<8} {state}")
    return 0


def cmd_records_show(args) -> int:
    try:
        recs = _records.load_records(args.name)
    except RecordTableMissing as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyError as e:
        print(f"error: {e.args[0]}", file=sys.stderr)
        return 2
    for n in _parse_range(args.n or "1-30"):
        if n in recs:
            print(n, recs[n] if args.digits else float(recs[n]))
    return 0


def cmd_records_fetch(args) -> int:
    try:
        status = _records.fetch_records(args.tables, force=args.force, delay=args.delay,
                                        offline_from=args.offline_from, dest=args.dest,
                                        save_html=args.save_html, timeout=args.timeout)
    except (KeyError, _records.FetchError) as e:
        print(f"error: {e.args[0] if isinstance(e, KeyError) else e}", file=sys.stderr)
        return 2
    bad = sorted(k for k, v in status.items() if v.startswith("error"))
    ok = sum(v == "fetched" for v in status.values())
    print(f"{ok} fetched, {sum(v == 'cached' for v in status.values())} already cached, {len(bad)} failed"
          + (f": {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


def cmd_records_path(args) -> int:
    print(_records.cache_dir())
    return 0


_RECORDS_SUB = ("list", "show", "fetch", "path")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="circlepack",
                                 description="Pack n equal circles of maximal radius in a fixed container.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="multi-start search for one n")
    _add_search_args(p)
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--out", help="output .json file or directory (default results/)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("verify", help="verify solution files (see circlepack/verify.py)")
    p.add_argument("files", nargs="+")
    p.add_argument("--tol", type=float, default=1e-12)
    p.add_argument("--exact", action="store_true")
    p.add_argument("--eps", default="1e-12")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("bench", help="compare against Packomania records (needs `records fetch`)")
    _add_search_args(p)
    p.add_argument("--n", default="10-30", help="e.g. 10-30 or 5,7,12")
    p.add_argument("--rtol", type=float, default=1e-9, help="relative tolerance for a hit")
    p.add_argument("--out", help="output directory")
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("records", help="download, list and print Packomania record tables",
                       description="Packomania tables are not bundled: `records fetch` downloads them "
                                   "into a local cache ($CIRCLEPACK_DATA or the platform cache directory). "
                                   "`circlepack records NAME` is short for `records show NAME`.")
    p.set_defaults(func=cmd_records_list)
    rsub = p.add_subparsers(dest="records_cmd")
    q = rsub.add_parser("list", help="supported tables and cache status (default)")
    q.set_defaults(func=cmd_records_list)
    q = rsub.add_parser("show", help='print "n radius" lines of a cached table')
    q.add_argument("name")
    q.add_argument("--n", default=None, help="range, default 1-30")
    q.add_argument("--digits", action="store_true", help="print the radius exactly as on the site")
    q.set_defaults(func=cmd_records_show)
    q = rsub.add_parser("fetch", help="download tables from packomania.com into the cache")
    q.add_argument("--tables", action="append", metavar="NAMES",
                   help="comma-separated names or Packomania codes (default: all supported)")
    q.add_argument("--force", action="store_true", help="re-download tables already cached")
    q.add_argument("--delay", type=float, default=_records.DEFAULT_DELAY,
                   help="seconds between requests (default %(default)s; values below 2 are raised to 2)")
    q.add_argument("--offline-from", metavar="DIR", help="parse pages previously saved in DIR, no network")
    q.add_argument("--save-html", metavar="DIR", help="also keep a copy of every downloaded page in DIR")
    q.add_argument("--dest", metavar="DIR", help="cache directory (default: $CIRCLEPACK_DATA or platform cache)")
    q.add_argument("--timeout", type=float, default=_records.DEFAULT_TIMEOUT)
    q.set_defaults(func=cmd_records_fetch)
    q = rsub.add_parser("path", help="print the cache directory")
    q.set_defaults(func=cmd_records_path)

    from .campaign import add_parser as add_campaign_parser

    add_campaign_parser(sub)

    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "records" and not argv[1].startswith("-") and argv[1] not in _RECORDS_SUB:
        argv.insert(1, "show")       # backward-compatible `circlepack records NAME`
    args = ap.parse_args(argv)
    t = time.perf_counter()
    rc = args.func(args)
    if args.cmd in ("run", "bench"):
        print(f"[total {time.perf_counter() - t:.1f}s]", file=sys.stderr)
    return rc
