"""Record-table cache: parser, offline/online fetch (network mocked), CLI, errors.

Nothing here touches the network: ``tests/data/packomania/csq.html`` is a
hand-written page with made-up numbers that imitates the Packomania layout.
"""
import io
import json
import shutil
import urllib.error
from pathlib import Path

import pytest

from circlepack import records
from circlepack.cli import main as cli_main
from circlepack.records import (RecordTableMissing, available, cache_dir, fetch_records, known_radius,
                                load_records, load_table_meta, parse_table_html)

FIXTURE = Path(__file__).parent / "data" / "packomania" / "csq.html"
PAGE = FIXTURE.read_bytes().decode("latin-1")


def test_parse_fixture():
    last, rows = parse_table_html(PAGE)
    assert last == "01-Feb-2003"
    assert [(n, r) for n, r, _ in rows] == [
        (1, "0.500000000000"), (2, "0.311111111111"), (3, "0.262626262626262626262626262626"),
        (4, "0.240000000001"), (4, "0.240000000002"), (6, "0.190000000000")]
    assert [b for *_, b in rows] == [True, True, False, False, False, False]


def test_parse_rejects_non_table_page():
    assert parse_table_html("<html><body>Service unavailable</body></html>") == (None, [])


def test_cache_dir_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("CIRCLEPACK_DATA", str(tmp_path / "x"))
    assert cache_dir() == tmp_path / "x"
    monkeypatch.delenv("CIRCLEPACK_DATA")
    monkeypatch.setattr(records.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert cache_dir() == tmp_path / "xdg" / "circlepack" / "records"
    monkeypatch.delenv("XDG_CACHE_HOME")
    assert cache_dir() == Path.home() / ".cache" / "circlepack" / "records"
    monkeypatch.setattr(records.sys, "platform", "darwin")
    assert cache_dir() == Path.home() / "Library" / "Caches" / "circlepack" / "records"
    monkeypatch.setattr(records.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    assert cache_dir() == tmp_path / "lad" / "circlepack" / "Cache" / "records"


def test_missing_table_error(empty_cache):
    assert available() == []
    with pytest.raises(RecordTableMissing, match=r"record table square not found.*"
                                                 r"circlepack records fetch --tables square"):
        load_records("square")
    with pytest.raises(RecordTableMissing):
        known_radius("square", 4)
    with pytest.raises(KeyError):
        load_records("torus")


def test_offline_fetch_and_load(empty_cache):
    st = fetch_records(["square"], offline_from=FIXTURE.parent, log=None)
    assert st == {"square": "fetched"}
    assert available() == ["square"]
    recs = load_records("csq")                       # code or name
    assert recs == {1: "0.500000000000", 2: "0.311111111111", 3: "0.262626262626262626262626262626",
                    4: "0.240000000002", 6: "0.190000000000"}   # duplicate N=4: larger radius kept
    assert known_radius("square", 4) == 0.240000000002
    assert known_radius("square", 5) is None
    meta = load_table_meta("square")
    assert meta["source_url"] == "https://www.packomania.com/csq/csq.html"
    assert meta["table_last_update"] == "01-Feb-2003"
    assert meta["retrieved_from"] == "file:csq.html"
    assert meta["proven_optimal"] == [1, 2]
    assert "N=[4]" in meta["notes"][0]
    assert "radii" not in meta and meta["fetched_at"].endswith("+00:00")
    # second call does nothing without force; with force it rewrites
    assert fetch_records(["square"], offline_from=FIXTURE.parent, log=None) == {"square": "cached"}
    assert fetch_records(["square"], offline_from=FIXTURE.parent, force=True, log=None) == {"square": "fetched"}


def test_offline_polygon_drops_inconsistent_n1(empty_cache, tmp_path):
    src = tmp_path / "saved"
    src.mkdir()
    shutil.copy(FIXTURE, src / "cno.html")
    assert fetch_records(["nonagon", "square"], offline_from=src, log=None)["square"].startswith("error")
    assert 1 not in load_records("nonagon") and 2 in load_records("nonagon")
    assert any("N=1 dropped" in s for s in load_table_meta("nonagon")["notes"])


class _Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = type("H", (), {"get_content_charset": staticmethod(lambda: "iso-8859-1")})()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_network_fetch_mocked(empty_cache, tmp_path, monkeypatch):
    calls, sleeps = [], []

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, req.get_header("User-agent"), timeout))
        if "chx" in req.full_url:
            raise urllib.error.URLError("Name or service not known")
        if "cpt" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", None, None)
        return _Resp(FIXTURE.read_bytes())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(records.time, "sleep", lambda s: sleeps.append(s))
    st = fetch_records(["square", "hexagon", "pentagon"], delay=0.1, save_html=tmp_path / "html", log=None)
    assert st["square"] == "fetched"
    assert "cannot reach" in st["hexagon"] and "Name or service" in st["hexagon"]
    assert "HTTP 503" in st["pentagon"]
    assert [c[0] for c in calls] == ["https://www.packomania.com/csq/csq.html",
                                     "https://www.packomania.com/chx/chx.html",
                                     "https://www.packomania.com/cpt/cpt.html"]
    assert all(c[1].startswith("circlepack/") for c in calls)
    assert len(sleeps) == 2 and all(s > 1.9 for s in sleeps)     # delay floor of 2 s
    assert (tmp_path / "html" / "csq.html").read_bytes() == FIXTURE.read_bytes()
    assert load_table_meta("square")["retrieved_from"] == "https://www.packomania.com/csq/csq.html"


def test_cli_records_fetch_list_show(empty_cache, capsys):
    assert cli_main(["records", "fetch", "--tables", "square,hexagon", "--offline-from", str(FIXTURE.parent)]) == 1
    out = capsys.readouterr().out
    assert "1 fetched" in out and "1 failed: hexagon" in out
    assert cli_main(["records"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any(ln.startswith("square") and "5 radii" in ln for ln in lines)
    assert any(ln.startswith("hexagon") and "not fetched" in ln for ln in lines)
    assert cli_main(["records", "square", "--n", "3-4", "--digits"]) == 0
    assert capsys.readouterr().out.split() == ["3", "0.262626262626262626262626262626", "4", "0.240000000002"]
    assert cli_main(["records", "show", "hexagon"]) == 1
    assert "circlepack records fetch --tables hexagon" in capsys.readouterr().err
    assert cli_main(["records", "path"]) == 0
    assert capsys.readouterr().out.strip() == str(empty_cache)
    assert cli_main(["records", "fetch", "--tables", "torus"]) == 2


def test_commands_without_records_work_with_empty_cache(empty_cache, tmp_path, capsys):
    out = tmp_path / "sq.json"
    assert cli_main(["run", "--container", "square", "--n", "3", "--starts", "1", "--workers", "1",
                     "--hops", "1", "--nice", "0", "--quiet", "--out", str(out)]) == 0
    assert "records fetch --tables square" in capsys.readouterr().err
    assert json.loads(out.read_text())["meta"]["known_best"] is None
    assert cli_main(["verify", str(out)]) == 0
    with pytest.raises(SystemExit, match="records fetch --tables square"):
        cli_main(["bench", "--container", "square", "--n", "2", "--starts", "1", "--workers", "1"])
