import os

import pytest

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "records(*tables): needs downloaded Packomania tables; skipped when they are not "
                   "in the cache ($CIRCLEPACK_DATA or the platform cache, see `circlepack records fetch`)")


def pytest_runtest_setup(item):
    from circlepack.records import has_table

    for mark in item.iter_markers(name="records"):
        missing = [t for t in mark.args if not has_table(t)]
        if missing:
            pytest.skip(f"Packomania record table(s) {', '.join(missing)} not cached; run "
                        f"`circlepack records fetch --tables {','.join(missing)}`")


@pytest.fixture
def empty_cache(tmp_path, monkeypatch):
    """Point the record cache to an empty directory for the duration of a test."""
    d = tmp_path / "records-cache"
    monkeypatch.setenv("CIRCLEPACK_DATA", str(d))
    return d
