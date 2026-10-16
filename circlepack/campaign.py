"""Long-running, resumable search campaigns over many (table, n) targets.

A *campaign file* (TOML or JSON) lists jobs; each job expands to targets
``(table, n)`` (a Packomania table code and a number of circles). The driver
splits the work into *units* -- one batch of consecutive seeds for one target,
sized to take about ``unit_seconds`` -- and runs them on a process pool whose
size adapts to the machine load. All state lives in ``<dir>/state.sqlite``;
best packings are written atomically to ``<dir>/best/<table>/<table>_n<n>.json``.
Killing the driver at any moment loses at most the starts of the units in
flight; their seeds are never reused. See ``campaigns/README.md``.
"""
from __future__ import annotations

import ctypes
import fcntl
import json
import math
import multiprocessing as mp
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .references import (Reference, classify, load_moki_julio, load_packomania, table_spec)

__all__ = ["CampaignConfig", "Job", "load_config", "expand_targets", "State", "choose_target",
           "unit_size", "target_workers", "est_seconds_per_start", "run_campaign", "build_report",
           "plan_text"]

HIT_RTOL = 1e-9
NEW_BEST_RTOL = 1e-14   # ignore float-noise 'improvements' of an identical packing


# --------------------------------------------------------------------------- config
@dataclass
class Job:
    table: str
    n: object                       # "10-48", "10-max", [10, 12], 17
    priority: int = 1
    starts: int = 200               # start budget per target
    hops: int = 20
    skip_mj: bool = False           # drop n with a Moki & Julio entry
    only_mj: bool = False           # keep only n with a Moki & Julio entry
    idle_only: bool = False         # scheduled only when nothing else is runnable
    container: dict | None = None   # spec override (default: Packomania normalisation)
    name: str = ""


@dataclass
class CampaignConfig:
    name: str = "campaign"
    path: Path | None = None
    dir: Path | None = None
    unit_seconds: float = 300.0     # target wall time of one unit
    unit_min_starts: int = 1
    unit_max_starts: int = 64
    unit_timeout_factor: float = 3.0  # a unit stops early after this many unit_seconds
    min_workers: int = 2
    max_workers: int = 12
    reserve_cpus: int = 2
    min_mem_gib: float = 2.0
    nice: int = 15
    ionice_idle: bool = True
    adapt_every: float = 60.0
    report_every: float = 900.0
    priority_lag: float = 2.0       # rounds a priority class gets ahead of the next one
    seed_base: int = 1_000_000
    stop_grace: float = 120.0       # seconds to wait for running starts on a graceful stop
    verify_eps: str = "1e-12"
    contention: float = 1.5         # slowdown of one start when the pool is full (SMT, thermals)
    speed_factor: float = 1.0       # scales the built-in seconds-per-start model
    packomania_dir: Path | None = None
    mj_manifest: Path | None = None
    overrides: dict = field(default_factory=dict)   # {(table, n): {"packomania": str, "moki_julio": str}}
    jobs: list[Job] = field(default_factory=list)


def _resolve(base: Path | None, p: str | None) -> Path | None:
    if p is None:
        return None
    q = Path(os.path.expanduser(str(p)))
    return q if q.is_absolute() or base is None else (base / q).resolve()


def load_config(path: str | Path) -> CampaignConfig:
    path = Path(path).resolve()
    text = path.read_text()
    if path.suffix == ".json":
        doc = json.loads(text)
    else:
        try:
            import tomllib
        except ImportError:  # Python 3.10
            raise SystemExit("TOML campaign files need Python >= 3.11; use a .json campaign file") from None
        doc = tomllib.loads(text)
    base = path.parent
    c = doc.get("campaign", {})
    cfg = CampaignConfig(path=path)
    for k, v in c.items():
        if k in ("dir", "path"):
            continue
        if not hasattr(cfg, k):
            raise ValueError(f"unknown [campaign] key {k!r}")
        setattr(cfg, k, type(getattr(cfg, k))(v) if getattr(cfg, k) is not None else v)
    cfg.dir = _resolve(base, c.get("dir"))
    refs = doc.get("references", {})
    cfg.packomania_dir = _resolve(base, refs.get("packomania_dir"))
    cfg.mj_manifest = _resolve(base, refs.get("mj_manifest"))
    for o in doc.get("override", []):
        key = (str(o["table"]), int(o["n"]))
        cfg.overrides[key] = {k: str(o[k]) for k in ("packomania", "moki_julio") if k in o}
    for j in doc.get("job", []):
        unknown = set(j) - set(Job.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown job keys {sorted(unknown)}")
        cfg.jobs.append(Job(**j))
    if not cfg.jobs:
        raise ValueError("campaign file has no [[job]] entries")
    return cfg


def _parse_n(spec, nmax: int | None) -> list[int]:
    if isinstance(spec, int):
        return [spec]
    if isinstance(spec, list):
        return [int(x) for x in spec]
    out: list[int] = []
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            if b == "max":
                if nmax is None:
                    raise ValueError(f"'{spec}': table size unknown (no Packomania table)")
                b = nmax
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def expand_targets(cfg: CampaignConfig) -> list[dict]:
    """Targets in job order; a (table, n) listed twice keeps its first (job) occurrence."""
    mj = load_moki_julio(cfg.mj_manifest)
    pk_cache: dict[str, dict[int, str]] = {}
    seen: dict[tuple[str, int], dict] = {}
    for ji, job in enumerate(sorted(cfg.jobs, key=lambda j: j.priority)):
        pk = pk_cache.setdefault(job.table, load_packomania(job.table, cfg.packomania_dir))
        spec = dict(job.container) if job.container else table_spec(job.table)
        try:
            ns = _parse_n(job.n, max(pk) if pk else None)
        except ValueError as e:
            raise ValueError(f"job {job.name or job.table!r}, table {job.table}: {e}; run "
                             f"`circlepack records fetch --tables {job.table}` or give an explicit range") from None
        for n in ns:
            key = (job.table, n)
            if key in seen:
                continue
            has_mj = key in mj
            if (job.skip_mj and has_mj) or (job.only_mj and not has_mj):
                continue
            ov = cfg.overrides.get(key, {})
            seen[key] = {
                "table": job.table, "n": n, "priority": int(job.priority), "max_starts": int(job.starts),
                "hops": int(job.hops), "idle_only": int(bool(job.idle_only)), "spec": json.dumps(spec),
                "job": job.name or f"job{ji}",
                "ref_pk": ov.get("packomania", pk.get(n)), "ref_mj": ov.get("moki_julio", mj.get(key)),
            }
    return list(seen.values())


# --------------------------------------------------------------------------- cost model
#: measured seconds per start (20 hops, one idle core) vs n, see benchmarks/
_MODEL = [(1, 0.2), (10, 1.5), (20, 3.5), (30, 6.0), (40, 7.0), (60, 10.0), (100, 14.0),
          (200, 28.0), (300, 45.0), (600, 100.0)]


def est_seconds_per_start(n: int, hops: int = 20, speed_factor: float = 1.0) -> float:
    pts = _MODEL
    base = pts[-1][1]
    if n <= pts[0][0]:
        base = pts[0][1]
    elif n >= pts[-1][0]:
        base = pts[-1][1] * n / pts[-1][0]
    else:
        for (n0, t0), (n1, t1) in zip(pts, pts[1:]):
            if n0 <= n <= n1:
                base = t0 + (t1 - t0) * (n - n0) / (n1 - n0)
                break
    return base * (0.3 + 0.7 * hops / 20.0) * speed_factor


# --------------------------------------------------------------------------- state
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS targets (
  tbl TEXT NOT NULL, n INTEGER NOT NULL,
  priority INTEGER, max_starts INTEGER, hops INTEGER, idle_only INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
  spec TEXT, job TEXT, ref_pk TEXT, ref_mj TEXT,
  next_seed INTEGER NOT NULL,
  starts_done INTEGER DEFAULT 0, units_done INTEGER DEFAULT 0, cpu_seconds REAL DEFAULT 0,
  hits INTEGER DEFAULT 0, errors INTEGER DEFAULT 0,
  best_r REAL, best_seed INTEGER, best_file TEXT, best_at REAL,
  verified INTEGER, verdict TEXT,
  PRIMARY KEY (tbl, n));
CREATE TABLE IF NOT EXISTS units (
  id INTEGER PRIMARY KEY AUTOINCREMENT, tbl TEXT, n INTEGER, seed0 INTEGER, starts INTEGER, hops INTEGER,
  status TEXT, submitted_at REAL, finished_at REAL, starts_done INTEGER DEFAULT 0,
  best_r REAL, cpu_seconds REAL, wall_seconds REAL, note TEXT);
CREATE INDEX IF NOT EXISTS units_status ON units(status);
CREATE INDEX IF NOT EXISTS units_finished ON units(finished_at);
CREATE TABLE IF NOT EXISTS events (ts REAL, kind TEXT, tbl TEXT, n INTEGER, msg TEXT);
"""


class State:
    """SQLite-backed campaign state (single writer: the driver)."""

    def __init__(self, path: str | Path, readonly: bool = False):
        self.path = Path(path)
        if readonly:
            self.db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30)
        else:
            self.db = sqlite3.connect(self.path, timeout=30)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript(_SCHEMA)
        self.db.row_factory = sqlite3.Row

    def close(self) -> None:
        self.db.close()

    # meta
    def set_meta(self, **kv) -> None:
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                                [(k, json.dumps(v)) for k, v in kv.items()])

    def meta(self) -> dict:
        return {r["key"]: json.loads(r["value"]) for r in self.db.execute("SELECT * FROM meta")}

    def event(self, kind: str, tbl: str | None, n: int | None, msg: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (time.time(), kind, tbl, n, msg))

    # targets
    def sync_targets(self, targets: list[dict], seed_base: int) -> None:
        """Insert new targets, update parameters of existing ones; never touch progress."""
        with self.db:
            self.db.execute("UPDATE targets SET active = 0")
            for t in targets:
                self.db.execute(
                    """INSERT INTO targets (tbl, n, priority, max_starts, hops, idle_only, active, spec, job,
                                            ref_pk, ref_mj, next_seed)
                       VALUES (:table, :n, :priority, :max_starts, :hops, :idle_only, 1, :spec, :job,
                               :ref_pk, :ref_mj, :seed)
                       ON CONFLICT (tbl, n) DO UPDATE SET priority = excluded.priority,
                         max_starts = excluded.max_starts, hops = excluded.hops, idle_only = excluded.idle_only,
                         active = 1, spec = excluded.spec, job = excluded.job, ref_pk = excluded.ref_pk,
                         ref_mj = excluded.ref_mj""",
                    {**t, "seed": seed_base})

    def targets(self, active_only: bool = True) -> list[sqlite3.Row]:
        q = "SELECT * FROM targets" + (" WHERE active = 1" if active_only else "")
        return list(self.db.execute(q + " ORDER BY priority, tbl, n"))

    def target(self, tbl: str, n: int) -> sqlite3.Row:
        return self.db.execute("SELECT * FROM targets WHERE tbl = ? AND n = ?", (tbl, n)).fetchone()

    # units
    def recover(self) -> int:
        """Mark units left 'running' by a previous (killed) driver as lost."""
        with self.db:
            cur = self.db.execute("UPDATE units SET status = 'lost', finished_at = ? WHERE status = 'running'",
                                  (time.time(),))
        return cur.rowcount

    def allocate_unit(self, tbl: str, n: int, starts: int) -> sqlite3.Row:
        """Reserve ``starts`` fresh seeds for a target (committed before the unit is submitted)."""
        with self.db:
            t = self.target(tbl, n)
            seed0 = int(t["next_seed"])
            self.db.execute("UPDATE targets SET next_seed = ? WHERE tbl = ? AND n = ?", (seed0 + starts, tbl, n))
            cur = self.db.execute(
                "INSERT INTO units (tbl, n, seed0, starts, hops, status, submitted_at) VALUES (?,?,?,?,?,?,?)",
                (tbl, n, seed0, starts, int(t["hops"]), "running", time.time()))
        return self.db.execute("SELECT * FROM units WHERE id = ?", (cur.lastrowid,)).fetchone()

    def finish_unit(self, unit_id: int, res: dict, ref_best: float | None, new_best: dict | None) -> None:
        """Record a finished (or partial) unit and, if given, the new best of its target."""
        u = self.db.execute("SELECT * FROM units WHERE id = ?", (unit_id,)).fetchone()
        if u is None or u["status"] not in ("running", "lost"):
            return                                   # already recorded (idempotent)
        k = int(res["starts_done"])
        hits = sum(r >= ref_best * (1 - HIT_RTOL) for r in res["radii"]) if ref_best else 0
        status = "done" if k >= u["starts"] else "partial"
        with self.db:
            self.db.execute("""UPDATE units SET status = ?, finished_at = ?, starts_done = ?, best_r = ?,
                               cpu_seconds = ?, wall_seconds = ? WHERE id = ?""",
                            (status, time.time(), k, res.get("best_r"), res["cpu_seconds"], res["wall_seconds"],
                             unit_id))
            self.db.execute("""UPDATE targets SET starts_done = starts_done + ?, units_done = units_done + 1,
                               cpu_seconds = cpu_seconds + ?, hits = hits + ? WHERE tbl = ? AND n = ?""",
                            (k, res["cpu_seconds"], hits, u["tbl"], u["n"]))
            if new_best:
                self.db.execute("""UPDATE targets SET best_r = :r, best_seed = :seed, best_file = :file,
                                   best_at = :at, verified = :verified, verdict = :verdict
                                   WHERE tbl = :tbl AND n = :n""", {**new_best, "tbl": u["tbl"], "n": u["n"]})

    def fail_unit(self, unit_id: int, note: str) -> None:
        u = self.db.execute("SELECT * FROM units WHERE id = ?", (unit_id,)).fetchone()
        with self.db:
            self.db.execute("UPDATE units SET status = 'error', finished_at = ?, note = ? WHERE id = ?",
                            (time.time(), note[:2000], unit_id))
            self.db.execute("UPDATE targets SET errors = errors + 1 WHERE tbl = ? AND n = ?", (u["tbl"], u["n"]))

    def mark_lost(self, unit_id: int, note: str = "") -> None:
        with self.db:
            self.db.execute("UPDATE units SET status = 'lost', finished_at = ?, note = ? WHERE id = ?"
                            " AND status = 'running'", (time.time(), note, unit_id))

    def set_best(self, tbl: str, n: int, best: dict) -> None:
        with self.db:
            self.db.execute("""UPDATE targets SET best_r = :r, best_seed = :seed, best_file = :file,
                               best_at = :at, verified = :verified, verdict = :verdict
                               WHERE tbl = :tbl AND n = :n""", {**best, "tbl": tbl, "n": n})


# --------------------------------------------------------------------------- scheduling
MAX_ERRORS = 3


def _ref(t) -> Reference:
    return Reference(t["ref_pk"], t["ref_mj"])


def remaining_starts(t, inflight_starts: int = 0) -> int:
    return int(t["max_starts"]) - int(t["starts_done"]) - inflight_starts


def target_score(t, inflight_units: int, lag: float) -> tuple:
    """Smaller is scheduled first.

    ``rounds`` (units done + in flight) gives round-robin coverage; a priority
    class ``p`` is offset by ``lag * (p - 1)`` rounds. Targets that already
    reach the reference often are deepened more slowly (factor ``1 + hits/4``,
    capped at 3); near misses (no hit, relative gap below 1e-6) are favoured.
    """
    rounds = int(t["units_done"]) + inflight_units
    f = 1.0 + 0.25 * min(int(t["hits"]), 8)
    ref = _ref(t).best_float
    if t["hits"] == 0 and ref and t["best_r"] is not None:
        gap = (ref - float(t["best_r"])) / ref
        if 0 < gap < 1e-6:
            f *= 0.75
    return (rounds * f + lag * (int(t["priority"]) - 1), int(t["priority"]), int(t["n"]), t["tbl"])


def choose_target(targets, inflight: dict[tuple[str, int], tuple[int, int]], lag: float = 2.0):
    """Pick the next target (a row of ``targets``) or ``None``.

    ``inflight`` maps ``(table, n)`` to ``(units, starts)`` currently running.
    Idle-only targets are considered only if no other target is runnable.
    """
    best: dict[int, tuple | None] = {0: None, 1: None}
    for t in targets:
        if not t["active"] or int(t["errors"]) >= MAX_ERRORS:
            continue
        u, s = inflight.get((t["tbl"], int(t["n"])), (0, 0))
        if remaining_starts(t, s) <= 0:
            continue
        key = target_score(t, u, lag)
        slot = 1 if t["idle_only"] else 0
        cur = best[slot]
        if cur is None or key < cur[0]:
            best[slot] = (key, t)
    pick = best[0] or best[1]
    return None if pick is None else pick[1]


def unit_size(t, cfg: CampaignConfig, inflight_starts: int = 0) -> int:
    """Starts for the next unit of target ``t`` so that it takes about ``unit_seconds``."""
    done = int(t["starts_done"])
    if done >= 3 and t["cpu_seconds"]:
        sps = float(t["cpu_seconds"]) / done
    else:
        sps = est_seconds_per_start(int(t["n"]), int(t["hops"]), cfg.speed_factor) * cfg.contention
    k = int(round(cfg.unit_seconds / max(sps, 1e-3)))
    k = max(cfg.unit_min_starts, min(cfg.unit_max_starts, k))
    return max(0, min(k, remaining_starts(t, inflight_starts)))


def target_workers(cpu: int, load1: float, own_active: int, mem_avail_gib: float | None,
                   cfg: CampaignConfig) -> int:
    """``clamp(cpu - reserve - round(load1 - own_active), min, max)``; memory pressure overrides."""
    excess = max(0.0, load1 - own_active)
    t = cpu - cfg.reserve_cpus - int(round(excess))
    t = max(cfg.min_workers, min(cfg.max_workers, t))
    if mem_avail_gib is not None and mem_avail_gib < cfg.min_mem_gib:
        t = max(1, min(t, own_active - 1))
    return t


def mem_available_gib() -> float | None:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 2**20
    except OSError:
        pass
    return None


# --------------------------------------------------------------------------- worker side
def _worker_init(nice: int, ionice_idle: bool) -> None:
    for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, "1")
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:  # die with the driver (Linux)
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass
    try:
        cur = os.getpriority(os.PRIO_PROCESS, 0)
        if nice > cur:
            os.setpriority(os.PRIO_PROCESS, 0, nice)
    except (OSError, AttributeError):
        pass
    if ionice_idle and shutil.which("ionice"):
        subprocess.run(["ionice", "-c", "3", "-p", str(os.getpid())], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_unit(spec: dict, n: int, seed0: int, starts: int, hops: int, stop_files: list[str],
             max_wall: float) -> dict:
    """Run starts ``seed0 .. seed0+starts-1``; stop early (between starts) on a stop file or timeout."""
    from .containers import make_container
    from .search import SearchConfig, run_start

    t0 = time.perf_counter()
    c = make_container(**spec)
    cfg = SearchConfig(hops=hops)
    best = None
    radii, cpu = [], 0.0
    for s in range(seed0, seed0 + starts):
        if radii and (any(os.path.exists(p) for p in stop_files) or time.perf_counter() - t0 > max_wall):
            break
        res = run_start(c, n, s, cfg)
        radii.append(float(res.r))
        cpu += res.seconds
        if best is None or res.r > best.r:
            best = res
    out = {"starts_done": len(radii), "radii": radii, "cpu_seconds": cpu,
           "wall_seconds": time.perf_counter() - t0, "best_r": None}
    if best is not None:
        out.update(best_r=float(best.r), best_seed=int(best.seed), best_X=best.X.tolist())
    return out


# --------------------------------------------------------------------------- best solutions
def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        dfd = os.open(path.parent, os.O_DIRECTORY)
        os.fsync(dfd)
        os.close(dfd)
    except OSError:
        pass


def save_best(outdir: Path, t, X, r: float, seed: int, eps: str, campaign: str) -> dict:
    """Write the best packing of target ``t`` atomically, verify it, classify it."""
    import numpy as np

    from . import __version__
    from .containers import make_container
    from .verify import verify, verify_exact

    tbl, n = t["tbl"], int(t["n"])
    ref = _ref(t)
    c = make_container(**json.loads(t["spec"]))
    X = np.asarray(X, float)
    meta = {"generator": f"circlepack {__version__} campaign {campaign}", "table": tbl, "seed": int(seed),
            "hops": int(t["hops"]), "packomania": ref.packomania, "moki_julio": ref.moki_julio,
            "found_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    doc = {"format": "circlepack/1", "container": c.to_dict(), "n": n, "r": float(r),
           "centers": [[float(x), float(y)] for x, y in X], "meta": meta}
    path = outdir / "best" / tbl / f"{tbl}_n{n}.json"
    _atomic_write(path, json.dumps(doc, indent=1) + "\n")
    ok_f, _ = verify(path)
    ok_x, rep = verify_exact(path, eps=eps)
    verdict = classify(r, ref, ok_f and ok_x)
    if verdict in ("RECORD CANDIDATE", "MARGINAL"):
        doc["meta"].update(verdict=verdict, exact_verify=rep.get("primitives"), eps=eps)
        _atomic_write(outdir / "candidates" / f"{tbl}_n{n}_r{r:.15f}.json", json.dumps(doc, indent=1) + "\n")
    return {"r": float(r), "seed": int(seed), "file": str(path.relative_to(outdir)), "at": time.time(),
            "verified": int(ok_f and ok_x), "verdict": verdict}


def reconcile_best_files(outdir: Path, state: State) -> int:
    """Adopt best files better than the DB (a crash between file write and DB commit)."""
    fixed = 0
    for t in state.targets(active_only=False):
        p = outdir / "best" / t["tbl"] / f"{t['tbl']}_n{t['n']}.json"
        if not p.is_file():
            continue
        try:
            doc = json.loads(p.read_text())
            r = float(doc["r"])
        except (ValueError, KeyError, OSError):
            continue
        if t["best_r"] is None or r > float(t["best_r"]):
            from .verify import verify, verify_exact
            eps = state.meta().get("verify_eps", "1e-12")
            ok = verify(p)[0] and verify_exact(p, eps=eps)[0]
            state.set_best(t["tbl"], int(t["n"]), {
                "r": r, "seed": doc.get("meta", {}).get("seed"), "file": str(p.relative_to(outdir)),
                "at": p.stat().st_mtime, "verified": int(ok), "verdict": classify(r, _ref(t), ok)})
            fixed += 1
    # references may change between runs (edited campaign file, overrides): refresh verdicts
    with state.db:
        for t in state.targets(active_only=False):
            if t["best_r"] is not None:
                v = classify(float(t["best_r"]), _ref(t), bool(t["verified"]))
                if v != t["verdict"]:
                    state.db.execute("UPDATE targets SET verdict = ? WHERE tbl = ? AND n = ?", (v, t["tbl"], t["n"]))
                    src = outdir / str(t["best_file"])
                    if v in ("RECORD CANDIDATE", "MARGINAL") and src.is_file():
                        dst = outdir / "candidates" / f"{t['tbl']}_n{t['n']}_r{float(t['best_r']):.15f}.json"
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(src, dst)
    return fixed


# --------------------------------------------------------------------------- report
def _fmt_h(sec: float) -> str:
    sec = float(sec or 0)
    return f"{sec / 3600:.1f} h" if sec >= 3600 else f"{sec / 60:.1f} min"


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def build_report(state: State, outdir: Path | None = None, now: float | None = None) -> str:
    now = now or time.time()
    meta = state.meta()
    T = state.targets(active_only=True)
    db = state.db
    running = db.execute("SELECT COUNT(*), COALESCE(SUM(starts),0) FROM units WHERE status='running'").fetchone()
    first = db.execute("SELECT MIN(submitted_at) FROM units").fetchone()[0]
    last_h = db.execute("SELECT COALESCE(SUM(starts_done),0), COALESCE(SUM(cpu_seconds),0) FROM units "
                        "WHERE finished_at > ? AND status IN ('done','partial')", (now - 3600,)).fetchone()
    tot_starts = sum(int(t["starts_done"]) for t in T)
    tot_cpu = sum(float(t["cpu_seconds"] or 0) for t in T)
    alive = _pid_alive(meta.get("pid")) and (now - float(meta.get("heartbeat", 0))) < 300
    L = [f"# Campaign `{meta.get('name', '?')}`", "",
         f"Generated {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}. "
         f"Driver: **{'RUNNING' if alive else 'stopped'}** (pid {meta.get('pid') or '-'}, "
         f"last heartbeat {time.strftime('%H:%M:%S', time.localtime(float(meta.get('heartbeat', 0))))}).", ""]
    if first:
        L.append(f"- campaign file: `{meta.get('campaign_file', '?')}`; first unit "
                 f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(first))}, {_fmt_h(now - first)} ago")
    L.append(f"- workers: target {meta.get('target_workers', '-')}, in flight {running[0]} units "
             f"({running[1]} starts); load {meta.get('load1', '-')}, MemAvailable {meta.get('mem_gib', '-')} GiB")
    L.append(f"- starts done: {tot_starts}, CPU time {_fmt_h(tot_cpu)}; last hour: {last_h[0]} starts, "
             f"{_fmt_h(last_h[1])} CPU ({last_h[1] / 3600:.1f} busy workers)")
    rem_sec = 0.0
    for t in T:
        rem = max(0, remaining_starts(t))
        if rem:
            sps = (float(t["cpu_seconds"]) / int(t["starts_done"])) if int(t["starts_done"]) >= 3 else \
                est_seconds_per_start(int(t["n"]), int(t["hops"])) * 1.5
            rem_sec += rem * sps
    tw = int(meta.get("target_workers") or 10)
    L.append(f"- remaining budget: ~{rem_sec / 3600:.0f} worker-hours (~{rem_sec / 3600 / max(tw, 1):.1f} h at "
             f"{tw} workers)")
    L += ["", "## Progress by priority", "",
          "| priority | targets | covered | starts done / budget | CPU | reached ref | beats (cand/marginal) |",
          "|---:|---:|---:|---:|---:|---:|---:|"]
    for p in sorted({int(t["priority"]) for t in T}):
        S = [t for t in T if int(t["priority"]) == p]
        cov = sum(int(t["starts_done"]) > 0 for t in S)
        sd = sum(int(t["starts_done"]) for t in S)
        bud = sum(int(t["max_starts"]) for t in S)
        cpu = sum(float(t["cpu_seconds"] or 0) for t in S)
        reach = sum(1 for t in S if t["verdict"] in ("MATCH", "RECORD CANDIDATE", "MARGINAL"))
        cand = sum(t["verdict"] == "RECORD CANDIDATE" for t in S)
        marg = sum(t["verdict"] == "MARGINAL" for t in S)
        L.append(f"| P{p} | {len(S)} | {cov} | {sd} / {bud} ({100 * sd / max(bud, 1):.1f}%) | {_fmt_h(cpu)} "
                 f"| {reach} | {cand} / {marg} |")
    L += ["", "## Record candidates", "",
          "Beats max(Packomania, Moki & Julio) by > 1e-12 relative, exact-verified "
          "(`MARGINAL`: by less than one unit of the reference's last printed digit).", ""]
    C = [t for t in T if t["verdict"] in ("RECORD CANDIDATE", "MARGINAL")]
    if C:
        L += ["| table | n | ours | Packomania | Moki & Julio | rel. gain | verdict | file |",
              "|---|---:|---:|---:|---:|---:|---|---|"]
        for t in sorted(C, key=lambda t: (t["tbl"], t["n"])):
            ref = _ref(t).best
            # references may have been edited since the verdict was stored
            gain = f"{float((Decimal(repr(float(t['best_r']))) - ref) / ref):.2e}" if ref else "-"
            L.append(f"| {t['tbl']} | {t['n']} | {float(t['best_r']):.15f} | {t['ref_pk'] or '-'} | "
                     f"{t['ref_mj'] or '-'} | {gain} | **{t['verdict']}** | `{t['best_file']}` |")
    else:
        L.append("None yet.")
    near: list[tuple[float, float, sqlite3.Row]] = []
    for t in T:
        rb = _ref(t).best_float
        if t["verdict"] == "BELOW" and rb and t["best_r"] is not None:
            near.append(((rb - float(t["best_r"])) / rb, rb, t))
    near.sort(key=lambda x: x[0])
    L += ["", "## Closest misses (top 15)", "", "| table | n | ours | best ref | rel. gap | starts |",
          "|---|---:|---:|---:|---:|---:|"]
    for _, rb, t in near[:15]:
        L.append(f"| {t['tbl']} | {t['n']} | {float(t['best_r']):.12f} | {rb:.12f} | "
                 f"{(rb - float(t['best_r'])) / rb:.2e} | {t['starts_done']} |")
    L += ["", "## By table", "", "| table | priorities | targets | covered | reached ref | below | starts | CPU |",
          "|---|---|---:|---:|---:|---:|---:|---:|"]
    for tbl in sorted({t["tbl"] for t in T}):
        S = [t for t in T if t["tbl"] == tbl]
        prios = ",".join(sorted({"P%d" % t["priority"] for t in S}))
        L.append(f"| {tbl} | {prios} | {len(S)} | "
                 f"{sum(int(t['starts_done']) > 0 for t in S)} | "
                 f"{sum(t['verdict'] in ('MATCH', 'RECORD CANDIDATE', 'MARGINAL') for t in S)} | "
                 f"{sum(t['verdict'] == 'BELOW' for t in S)} | {sum(int(t['starts_done']) for t in S)} | "
                 f"{_fmt_h(sum(float(t['cpu_seconds'] or 0) for t in S))} |")
    ev = list(db.execute("SELECT * FROM events WHERE kind != 'best' ORDER BY ts DESC LIMIT 15"))
    if ev:
        L += ["", "## Recent events", ""]
        L += [f"- {time.strftime('%m-%d %H:%M:%S', time.localtime(e['ts']))} {e['kind']}"
              f"{' ' + e['tbl'] + ' n=' + str(e['n']) if e['tbl'] else ''}: {e['msg']}" for e in ev]
    errs = [t for t in T if int(t["errors"]) >= MAX_ERRORS]
    if errs:
        L += ["", f"Disabled after {MAX_ERRORS} errors: " + ", ".join(f"{t['tbl']} n={t['n']}" for t in errs)]
    return "\n".join(L) + "\n"


def write_report(state: State, outdir: Path) -> Path:
    p = outdir / "REPORT.md"
    _atomic_write(p, build_report(state, outdir))
    return p


def plan_text(cfg: CampaignConfig, workers: int = 10) -> str:
    T = expand_targets(cfg)
    L = [f"campaign {cfg.name}: {len(T)} targets; seconds/start model x contention {cfg.contention} "
         f"x speed {cfg.speed_factor}", "",
         "| priority | tables | targets | n range | starts | worker-hours | hours at %d workers |" % workers,
         "|---:|---|---:|---|---:|---:|---:|"]
    tot = 0.0
    for p in sorted({t["priority"] for t in T}):
        S = [t for t in T if t["priority"] == p]
        wh = sum(t["max_starts"] * est_seconds_per_start(t["n"], t["hops"], cfg.speed_factor) * cfg.contention
                 for t in S) / 3600
        tot += wh
        tables = sorted({t["table"] for t in S})
        L.append(f"| P{p}{' (idle)' if any(t['idle_only'] for t in S) else ''} | {' '.join(tables)} | {len(S)} | "
                 f"{min(t['n'] for t in S)}-{max(t['n'] for t in S)} | {sum(t['max_starts'] for t in S)} | "
                 f"{wh:.0f} | {wh / workers:.1f} |")
    L.append(f"| total | | {len(T)} | | {sum(t['max_starts'] for t in T)} | {tot:.0f} | {tot / workers:.1f} |")
    return "\n".join(L)


# --------------------------------------------------------------------------- driver
def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


class _Lock:
    def __init__(self, path: Path):
        self.path = path
        self.fd = None

    def acquire(self) -> bool:
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            return False
        os.ftruncate(self.fd, 0)
        os.write(self.fd, f"{os.getpid()}\n".encode())
        return True

    def release(self) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


class Driver:
    def __init__(self, cfg: CampaignConfig, outdir: Path):
        self.cfg = cfg
        self.outdir = outdir
        self.stop_reason: str | None = None
        self.hard_stop = False
        self.pool: ProcessPoolExecutor | None = None
        self.inflight: dict = {}    # future -> unit row

    # signals
    def _on_signal(self, signum, _frame) -> None:
        name = signal.Signals(signum).name
        if self.stop_reason is not None and signum == signal.SIGINT:
            self.hard_stop = True
        self.stop_reason = self.stop_reason or name

    def _make_pool(self) -> ProcessPoolExecutor:
        return ProcessPoolExecutor(max_workers=self.cfg.max_workers, mp_context=mp.get_context("spawn"),
                                   initializer=_worker_init, initargs=(self.cfg.nice, self.cfg.ionice_idle),
                                   max_tasks_per_child=50)

    def _kill_pool(self) -> None:
        if self.pool is None:
            return
        procs = list(getattr(self.pool, "_processes", {}).values())
        self.pool.shutdown(wait=False, cancel_futures=True)
        for p in procs:
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass
        self.pool = None

    def _inflight_by_target(self) -> dict:
        d: dict = {}
        for u in self.inflight.values():
            k = (u["tbl"], int(u["n"]))
            a, b = d.get(k, (0, 0))
            d[k] = (a + 1, b + int(u["starts"]))
        return d

    def _submit(self, state: State, t) -> bool:
        k = unit_size(t, self.cfg, self._inflight_by_target().get((t["tbl"], int(t["n"])), (0, 0))[1])
        if k <= 0:
            return False
        assert self.pool is not None
        u = state.allocate_unit(t["tbl"], int(t["n"]), k)
        stops = [str(self.outdir / "STOP"), str(self.outdir / ".stopping")]
        fut = self.pool.submit(run_unit, json.loads(t["spec"]), int(t["n"]), int(u["seed0"]), k, int(u["hops"]),
                               stops, self.cfg.unit_timeout_factor * self.cfg.unit_seconds)
        self.inflight[fut] = u
        return True

    def _handle(self, state: State, fut, u) -> None:
        tbl, n = u["tbl"], int(u["n"])
        try:
            res = fut.result()
        except BrokenProcessPool:
            state.mark_lost(u["id"], "worker pool broken")
            raise
        except Exception as e:  # noqa: BLE001 - a bug for one target must not stop the campaign
            state.fail_unit(u["id"], repr(e))
            state.event("error", tbl, n, repr(e)[:300])
            log(f"ERROR unit {u['id']} {tbl} n={n}: {e!r}")
            return
        t = state.target(tbl, n)
        new_best = None
        if res["best_r"] is not None and (t["best_r"] is None
                                          or res["best_r"] > float(t["best_r"]) * (1 + NEW_BEST_RTOL)):
            new_best = save_best(self.outdir, t, res["best_X"], res["best_r"], res["best_seed"],
                                 self.cfg.verify_eps, self.cfg.name)
        state.finish_unit(u["id"], res, _ref(t).best_float, new_best)
        rb = "-" if res["best_r"] is None else f"{res['best_r']:.13f}"
        msg = (f"unit {u['id']} {tbl} n={n}: {res['starts_done']}/{u['starts']} starts, best {rb}, "
               f"{res['wall_seconds']:.0f}s wall")
        if new_best:
            ref = _ref(t).best_float
            gap = f", gap {(ref - new_best['r']) / ref:+.2e}" if ref else ""
            msg += f"  NEW BEST{gap} [{new_best['verdict']}]"
            state.event("best", tbl, n, f"r={new_best['r']:.15f} {new_best['verdict']}")
            if new_best["verdict"] in ("RECORD CANDIDATE", "MARGINAL", "UNVERIFIED"):
                state.event(new_best["verdict"].lower().replace(" ", "_"), tbl, n,
                            f"r={new_best['r']:.15f} vs Packomania {t['ref_pk']} / M&J {t['ref_mj']}")
                log(f"*** {new_best['verdict']}: {tbl} n={n} r={new_best['r']:.15f} "
                    f"(Packomania {t['ref_pk']}, M&J {t['ref_mj']}) -> {new_best['file']}")
        log(msg)

    def run(self) -> int:
        cfg, outdir = self.cfg, self.outdir
        outdir.mkdir(parents=True, exist_ok=True)
        lock = _Lock(outdir / "campaign.lock")
        if not lock.acquire():
            log(f"another driver holds {outdir / 'campaign.lock'}; exiting")
            return 3
        for f in ("STOP", ".stopping"):
            if (outdir / f).exists():
                log(f"removing stale {f}")
                (outdir / f).unlink()
        state = State(outdir / "state.sqlite")
        try:
            return self._run(state, lock)
        finally:
            try:
                state.set_meta(pid=None, heartbeat=time.time())
                write_report(state, outdir)
            finally:
                state.close()
                for f in (".stopping", "campaign.pid"):
                    try:
                        (outdir / f).unlink()
                    except FileNotFoundError:
                        pass
                lock.release()

    def _run(self, state: State, lock: _Lock) -> int:
        cfg, outdir = self.cfg, self.outdir
        (outdir / "campaign.pid").write_text(f"{os.getpid()}\n")
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        try:
            os.setpriority(os.PRIO_PROCESS, 0, max(os.getpriority(os.PRIO_PROCESS, 0), min(cfg.nice, 10)))
        except (OSError, AttributeError):
            pass
        targets = expand_targets(cfg)
        state.sync_targets(targets, cfg.seed_base)
        state.set_meta(name=cfg.name, campaign_file=str(cfg.path), pid=os.getpid(), heartbeat=time.time(),
                       verify_eps=cfg.verify_eps, started_at=time.time())
        lost = state.recover()
        fixed = reconcile_best_files(outdir, state)
        state.event("start", None, None, f"pid {os.getpid()}, {len(targets)} targets, recovered {lost} lost units"
                    f", adopted {fixed} best files")
        log(f"campaign {cfg.name}: {len(targets)} targets in {outdir}; {lost} interrupted units marked lost, "
            f"{fixed} best files adopted; pid {os.getpid()}")
        self.pool = self._make_pool()
        cpu = os.cpu_count() or 4
        next_adapt = next_report = 0.0
        tw = cfg.min_workers
        exhausted_logged = False
        while not self.stop_reason:
            now = time.time()
            if (outdir / "STOP").exists():
                self.stop_reason = "STOP file"
                break
            if now >= next_adapt:
                load1 = os.getloadavg()[0]
                mem = mem_available_gib()
                new = target_workers(cpu, load1, len(self.inflight), mem, cfg)
                if new != tw:
                    log(f"workers {tw} -> {new} (load {load1:.2f}, own {len(self.inflight)}, "
                        f"MemAvailable {mem if mem is None else round(mem, 1)} GiB)")
                tw = new
                state.set_meta(target_workers=tw, load1=round(load1, 2),
                               mem_gib=None if mem is None else round(mem, 1), heartbeat=now)
                next_adapt = now + cfg.adapt_every
            T = None
            while len(self.inflight) < tw:
                T = T or state.targets()
                t = choose_target(T, self._inflight_by_target(), cfg.priority_lag)
                if t is None or not self._submit(state, t):
                    break
                T = None   # refresh rows (next_seed / scores) after an allocation
            if not self.inflight:
                if not exhausted_logged:
                    log("queue exhausted: every target reached its start budget")
                    exhausted_logged = True
                self.stop_reason = "queue exhausted"
                break
            done, _ = wait(list(self.inflight), timeout=5.0, return_when=FIRST_COMPLETED)
            for fut in done:
                u = self.inflight.pop(fut)
                try:
                    self._handle(state, fut, u)
                except BrokenProcessPool:
                    log("worker pool broken; marking in-flight units lost and restarting the pool")
                    for u2 in self.inflight.values():
                        state.mark_lost(u2["id"], "worker pool broken")
                    self.inflight.clear()
                    self._kill_pool()
                    self.pool = self._make_pool()
                    break
            if time.time() >= next_report:
                write_report(state, outdir)
                next_report = time.time() + cfg.report_every
        return self._drain(state)

    def _drain(self, state: State) -> int:
        cfg, outdir = self.cfg, self.outdir
        log(f"stopping ({self.stop_reason}); {len(self.inflight)} units in flight, grace {cfg.stop_grace:.0f}s")
        state.event("stop", None, None, str(self.stop_reason))
        if self.inflight:
            (outdir / ".stopping").touch()
        deadline = time.time() + cfg.stop_grace
        while self.inflight and time.time() < deadline and not self.hard_stop:
            done, _ = wait(list(self.inflight), timeout=2.0, return_when=FIRST_COMPLETED)
            for fut in done:
                u = self.inflight.pop(fut)
                try:
                    self._handle(state, fut, u)
                except BrokenProcessPool:
                    state.mark_lost(u["id"], "worker pool broken")
        for u in self.inflight.values():
            state.mark_lost(u["id"], f"killed on stop ({self.stop_reason})")
        if self.inflight:
            log(f"killing {len(self.inflight)} unfinished units")
        self.inflight.clear()
        self._kill_pool()
        log("stopped cleanly")
        return 0


def run_campaign(cfg: CampaignConfig, outdir: str | Path) -> int:
    return Driver(cfg, Path(outdir).resolve()).run()


# --------------------------------------------------------------------------- CLI
def cmd_campaign(args) -> int:
    if args.action == "plan":
        try:
            text = plan_text(load_config(args.target), workers=args.workers)
        except ValueError as e:
            raise SystemExit(f"campaign plan: {e}") from None
        print(text)
        return 0
    if args.action == "run":
        cfg = load_config(args.target)
        outdir = Path(args.dir) if args.dir else cfg.dir
        if outdir is None:
            raise SystemExit("no output directory: pass --dir or set [campaign] dir")
        return run_campaign(cfg, outdir)
    # status / report
    outdir = Path(args.target)
    db = outdir / "state.sqlite"
    if not db.is_file():
        raise SystemExit(f"no campaign state in {outdir}")
    state = State(db, readonly=args.action == "status")
    try:
        text = build_report(state, outdir)
        if args.action == "report" or args.write:
            _atomic_write(outdir / "REPORT.md", text)
    finally:
        state.close()
    if args.action == "status":
        cut = text.split("\n## Closest misses")[0] if not args.full else text
        print(cut.rstrip())
        print(f"\n(full report: {outdir / 'REPORT.md'}; log: {outdir / 'campaign.log'})")
    else:
        print(outdir / "REPORT.md")
    return 0


def add_parser(sub) -> None:
    p = sub.add_parser("campaign", help="long-running resumable campaign over many (table, n) targets")
    p.add_argument("action", choices=["run", "status", "report", "plan"],
                   help="run <file>: start/resume; status <dir>: summary; report <dir>: rewrite REPORT.md; "
                        "plan <file>: list targets and estimated hours")
    p.add_argument("target", help="campaign file (run, plan) or campaign directory (status, report)")
    p.add_argument("--dir", help="output directory for run (default: [campaign] dir)")
    p.add_argument("--workers", type=int, default=10, help="plan: worker count for the hour estimate")
    p.add_argument("--full", action="store_true", help="status: print the whole report")
    p.add_argument("--write", action="store_true", help="status: also rewrite REPORT.md (needs write access)")
    p.set_defaults(func=cmd_campaign)
