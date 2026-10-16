"""Campaign driver: references, record comparison, scheduler, state and resume."""
import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from circlepack.campaign import (CampaignConfig, Driver, State, build_report, choose_target, expand_targets,
                                 load_config, reconcile_best_files, run_unit, save_best, target_workers,
                                 unit_size)
from circlepack.containers import make_container
from circlepack.references import Reference, classify, load_moki_julio, load_packomania, table_spec


# ----------------------------------------------------------------- references / classification
def test_classify_uses_max_of_both_references():
    ref = Reference("0.100000000000", "0.100000001")
    assert ref.best == Decimal("0.100000001")
    assert classify(0.1000000005, ref, True) == "BELOW"          # beats Packomania only
    assert classify(0.10000001, ref, True) == "RECORD CANDIDATE"
    assert classify(0.10000001, ref, False) == "UNVERIFIED"


@pytest.mark.parametrize("pk, mj", [("0.250000000000", None), (None, "0.250000000000")])
def test_classify_with_a_single_reference(pk, mj):
    ref = Reference(pk, mj)
    assert ref.best == Decimal("0.25")
    assert classify(0.25, ref, True) == "MATCH"
    assert classify(0.2501, ref, True) == "RECORD CANDIDATE"
    assert classify(0.2499, ref, True) == "BELOW"


def test_classify_without_reference():
    ref = Reference(None, None)
    assert ref.best is None and ref.best_float is None and ref.print_ulp is None
    assert classify(0.3, ref, True) == "NO REFERENCE"


def test_classify_threshold_and_print_precision():
    ref = Reference("0.123456789012", None)          # 12 printed decimals -> ulp 1e-12
    r0 = 0.123456789012
    assert classify(r0 * (1 + 5e-13), ref, True) == "MATCH"         # below the 1e-12 relative margin
    assert classify(r0 + 5e-13, ref, True) == "MARGINAL"       # > 1e-12 rel but < 1 printed ulp
    assert classify(r0 + 3e-12, ref, True) == "RECORD CANDIDATE"
    long = Reference("0.056829196367008116655910085286", None)
    assert classify(0.0568291963670081 * (1 + 2e-12), long, True) == "RECORD CANDIDATE"


def test_load_moki_julio_and_packomania(tmp_path, empty_cache):
    (tmp_path / "MANIFEST.csv").write_text(
        "shelf,N,published_radius,new_radius,relative_gain,kind,precision\n"
        "crc_300,20,0.1,0.10001,1e-4,X,hp\ncrc_300,20,0.1,0.10002,2e-4,X,hp\nccq,7,0.2,bad,0,X,hp\n")
    mj = load_moki_julio(tmp_path / "MANIFEST.csv")
    assert mj == {("crc_300", 20): "0.10002"}
    assert load_moki_julio(tmp_path / "missing.csv") == {}
    (tmp_path / "chp.csv").write_text("n,radius\n10,0.243931374794\n11,0.237517122658\n")
    assert load_packomania("chp", tmp_path) == {10: "0.243931374794", 11: "0.237517122658"}
    # without a CSV: the records cache (here a synthetic table), else no reference
    empty_cache.mkdir()
    (empty_cache / "crc_300.json").write_text(json.dumps({"radii": {"22": "0.056829196367"}}))
    assert load_packomania("crc_300", tmp_path) == {22: "0.056829196367"}
    assert load_packomania("crc_300", None) == {22: "0.056829196367"}
    (tmp_path / "crc_300.csv").write_text("n,radius\n22,0.05\n")       # CSV overrides the cache
    assert load_packomania("crc_300", tmp_path) == {22: "0.05"}
    assert load_packomania("ctd", tmp_path) == {}
    assert load_packomania("nope", None) == {}


def test_table_specs_match_packomania_scale():
    # N = 2 in a regular k-gon of circumradius 1 / an isosceles right triangle with legs 1
    assert make_container(**table_spec("chp")).spec["k"] == 7
    with pytest.raises(KeyError):
        table_spec("nope")


# ----------------------------------------------------------------- config / targets
def _write_campaign(tmp_path: Path, extra: str = "") -> Path:
    pk = tmp_path / "pk"
    pk.mkdir(exist_ok=True)
    (pk / "chp.csv").write_text("n,radius\n" + "".join(f"{n},0.{300 - n}\n" for n in range(1, 13)))
    (tmp_path / "MANIFEST.csv").write_text("shelf,N,published_radius,new_radius\nchp,11,0.1,0.29\n")
    f = tmp_path / "c.toml"
    f.write_text(f"""
[campaign]
name = "t"
unit_seconds = 10
seed_base = 100
[references]
packomania_dir = "pk"
mj_manifest = "MANIFEST.csv"
[[override]]
table = "chp"
n = 12
packomania = "0.010000000000"
[[job]]
table = "chp"
n = "9-max"
priority = 1
starts = 20
skip_mj = true
[[job]]
table = "chp"
n = "10-11"
priority = 4
starts = 5
only_mj = true
idle_only = true
{extra}
""")
    return f


def test_expand_targets(tmp_path):
    cfg = load_config(_write_campaign(tmp_path))
    T = {(t["table"], t["n"]): t for t in expand_targets(cfg)}
    assert sorted(n for _, n in T) == [9, 10, 11, 12]
    assert T[("chp", 9)]["priority"] == 1 and T[("chp", 9)]["ref_pk"] == "0.291"
    assert T[("chp", 11)]["priority"] == 4 and T[("chp", 11)]["idle_only"] == 1   # M&J entry -> P4 only
    assert T[("chp", 11)]["ref_mj"] == "0.29"
    assert T[("chp", 12)]["ref_pk"] == "0.010000000000"                                   # override
    with pytest.raises(ValueError):
        load_config(_write_campaign(tmp_path, "[[job]]\ntable='chp'\nn=3\nbogus=1\n"))


# ----------------------------------------------------------------- scheduler
def _rows(**over):
    base = dict(tbl="a", n=10, priority=1, max_starts=100, hops=20, idle_only=0, active=1, errors=0,
                units_done=0, starts_done=0, cpu_seconds=0.0, hits=0, best_r=None, ref_pk="0.5", ref_mj=None)
    base.update(over)
    return base


def _pick(*a, **k):
    t = choose_target(*a, **k)
    assert t is not None
    return t


def test_choose_target_round_robin_priority_and_idle():
    T = [_rows(tbl="a", n=10, units_done=1), _rows(tbl="b", n=10), _rows(tbl="c", n=10, priority=2),
         _rows(tbl="d", n=10, idle_only=1, priority=4)]
    assert _pick(T, {})["tbl"] == "b"                          # uncovered first
    assert _pick(T, {("b", 10): (1, 5)})["tbl"] == "a"         # in-flight counts as a round
    # P2 starts once P1 targets have priority_lag rounds
    T2 = [_rows(tbl="a", units_done=2), _rows(tbl="c", priority=2)]
    assert _pick(T2, {}, lag=2.0)["n"] == 10
    assert _pick([_rows(tbl="a", units_done=3), _rows(tbl="c", priority=2)], {}, 2.0)["tbl"] == "c"
    # exhausted / erroring targets are skipped; idle-only only when nothing else is runnable
    T3 = [_rows(tbl="a", starts_done=100), _rows(tbl="b", errors=3), _rows(tbl="d", idle_only=1, priority=4)]
    assert _pick(T3, {})["tbl"] == "d"
    assert choose_target([_rows(tbl="a", starts_done=100)], {}) is None
    assert choose_target([_rows(tbl="a", max_starts=10)], {("a", 10): (1, 10)}) is None


def test_choose_target_deepening_prefers_few_hits_and_near_misses():
    sat = _rows(tbl="sat", units_done=4, hits=8)
    hard = _rows(tbl="hard", units_done=5, hits=0, best_r=0.4)
    assert _pick([sat, hard], {})["tbl"] == "hard"
    near = _rows(tbl="near", units_done=6, hits=0, best_r=0.5 * (1 - 1e-8))
    far = _rows(tbl="far", units_done=5, hits=0, best_r=0.4)
    assert _pick([far, near], {})["tbl"] == "near"     # 6 * 0.75 < 5


def test_unit_size_and_worker_target():
    cfg = CampaignConfig(unit_seconds=300, unit_max_starts=64, contention=1.0)
    assert unit_size(_rows(starts_done=10, cpu_seconds=100.0), cfg) == 30     # measured 10 s/start
    assert unit_size(_rows(starts_done=95, cpu_seconds=950.0), cfg) == 5      # remaining budget
    assert 30 < unit_size(_rows(n=10), cfg) <= 64                            # model ~1.5 s/start
    cfg = CampaignConfig(min_workers=2, max_workers=12, reserve_cpus=2, min_mem_gib=2.0)
    assert target_workers(16, 0.5, 0, 10.0, cfg) == 12
    assert target_workers(16, 10.0, 10, 10.0, cfg) == 12           # own load does not count
    assert target_workers(16, 16.0, 10, 10.0, cfg) == 8            # 6 foreign
    assert target_workers(16, 40.0, 4, 10.0, cfg) == 2             # floor
    assert target_workers(16, 4.0, 6, 1.5, cfg) == 5               # memory pressure: shrink by one
    assert target_workers(16, 4.0, 1, 0.5, cfg) == 1


# ----------------------------------------------------------------- state / resume
def test_state_allocation_finish_and_resume(tmp_path):
    cfg = load_config(_write_campaign(tmp_path))
    st = State(tmp_path / "s.sqlite")
    st.sync_targets(expand_targets(cfg), cfg.seed_base)
    u1 = st.allocate_unit("chp", 9, 4)
    u2 = st.allocate_unit("chp", 9, 3)
    assert (u1["seed0"], u2["seed0"]) == (100, 104)
    st.finish_unit(u1["id"], {"starts_done": 4, "radii": [0.291, 0.2, 0.291, 0.1], "cpu_seconds": 8.0,
                              "wall_seconds": 8.0, "best_r": 0.291}, 0.291, None)
    st.finish_unit(u1["id"], {"starts_done": 4, "radii": [], "cpu_seconds": 8.0, "wall_seconds": 8.0},
                   None, None)                                    # second call is a no-op
    st.close()
    # "kill": u2 is left running; a new driver marks it lost and never reuses its seeds
    st = State(tmp_path / "s.sqlite")
    assert st.recover() == 1
    st.sync_targets(expand_targets(cfg), cfg.seed_base)           # re-sync keeps progress
    t = st.target("chp", 9)
    assert (t["starts_done"], t["units_done"], t["hits"], t["next_seed"]) == (4, 1, 2, 107)
    assert st.allocate_unit("chp", 9, 2)["seed0"] == 107
    statuses = [r["status"] for r in st.db.execute("SELECT status FROM units ORDER BY id")]
    assert statuses == ["done", "lost", "running"]
    st.close()


def test_save_best_reconcile_and_report(tmp_path):
    cfg = load_config(_write_campaign(tmp_path))
    out = tmp_path / "run"
    out.mkdir()
    st = State(out / "s.sqlite")
    st.sync_targets(expand_targets(cfg), cfg.seed_base)
    st.set_meta(name="t", verify_eps="1e-12")
    res = run_unit(table_spec("chp"), 3, 0, 2, 3, [], 60.0)
    assert res["starts_done"] == 2 and res["best_r"] > 0
    # target n=12 has the (test-only) lowered reference 0.01 -> simulated record candidate
    t = st.target("chp", 12)
    res12 = run_unit(table_spec("chp"), 12, 0, 1, 2, [], 60.0)
    nb = save_best(out, t, res12["best_X"], res12["best_r"], res12["best_seed"], "1e-12", "t")
    assert nb["verified"] == 1 and nb["verdict"] == "RECORD CANDIDATE"
    assert (out / nb["file"]).is_file() and len(list((out / "candidates").iterdir())) == 1
    u = st.allocate_unit("chp", 12, 1)
    st.finish_unit(u["id"], res12, 0.01, nb)
    rep = build_report(st, out)
    assert "RECORD CANDIDATE" in rep and "| chp | 12 |" in rep
    # a best file newer than the DB (crash between write and commit) is adopted on restart
    t9 = st.target("chp", 9)
    res9 = run_unit(table_spec("chp"), 9, 5, 1, 2, [], 60.0)
    save_best(out, t9, res9["best_X"], res9["best_r"], 5, "1e-12", "t")
    assert st.target("chp", 9)["best_r"] is None
    assert reconcile_best_files(out, st) == 1
    assert st.target("chp", 9)["best_r"] == pytest.approx(res9["best_r"])
    doc = json.loads((out / "best" / "chp" / "chp_n9.json").read_text())
    assert doc["n"] == 9 and doc["container"]["spec"]["k"] == 7
    st.close()


def test_run_unit_stops_on_stop_file(tmp_path):
    stop = tmp_path / "STOP"
    stop.touch()
    res = run_unit(table_spec("crc_300"), 5, 0, 10, 2, [str(stop)], 60.0)
    assert res["starts_done"] == 1        # always at least one start, then the stop file is honoured


@pytest.mark.slow
def test_driver_runs_to_exhaustion_and_resumes(tmp_path):
    f = _write_campaign(tmp_path, "")
    text = f.read_text().replace("starts = 20", "starts = 2").replace("unit_seconds = 10", "unit_seconds = 1\n"
                                                                    "max_workers = 2\nadapt_every = 1\nnice = 0\nionice_idle = false")
    f.write_text(text.replace('n = "9-max"', 'n = "9-10"'))
    cfg = load_config(f)
    out = tmp_path / "run"
    assert Driver(cfg, out).run() == 0
    st = State(out / "state.sqlite")
    T = {t["n"]: t for t in st.targets()}
    assert T[9]["starts_done"] == 2 and T[10]["starts_done"] == 2 and T[9]["best_r"] > 0
    st.close()
    assert (out / "REPORT.md").read_text().startswith("# Campaign `t`")
    assert Driver(cfg, out).run() == 0            # resume: nothing left, idempotent
    st = State(out / "state.sqlite")
    assert st.target("chp", 9)["starts_done"] == 2
    st.close()
