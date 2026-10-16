"""Best-known radii from Packomania, downloaded on demand into a local cache.

The record tables are *not* distributed with circlepack. ``circlepack records
fetch`` (or :func:`fetch_records`) downloads the per-table summary pages from
www.packomania.com (E. Specht), extracts ``n -> radius`` with all printed digits
and writes one JSON file per table into the cache directory:

* ``$CIRCLEPACK_DATA`` if set, otherwise
* Linux/BSD: ``$XDG_CACHE_HOME/circlepack/records`` (default ``~/.cache/...``),
* macOS: ``~/Library/Caches/circlepack/records``,
* Windows: ``%LOCALAPPDATA%\\circlepack\\Cache\\records``.

Each cache file ``<code>.json`` (``code`` = Packomania prefix, e.g. ``csq``)
holds the radii as strings plus provenance: source URL, fetch time, the "Last
update" date printed on the page and the normalisation applied. Only the
standard library is used (``urllib``).
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable

__all__ = ["TABLES", "Table", "RecordTableMissing", "FetchError", "cache_dir", "supported",
           "available", "table_info", "has_table", "load_records", "known_radius", "load_table_meta",
           "parse_table_html", "fetch_records", "BASE_URL", "USER_AGENT"]

BASE_URL = "https://www.packomania.com/"
REPO_URL = "https://github.com/Whoneon/circlepack"
CACHE_FORMAT = "circlepack-records/1"
DEFAULT_DELAY = 2.5
MIN_DELAY = 2.0   # politeness floor between two requests to the site
DEFAULT_TIMEOUT = 30.0


def _user_agent() -> str:
    from . import __version__

    return f"circlepack/{__version__} (+{REPO_URL}; research tool, polite one-off fetch)"


USER_AGENT = _user_agent()


@dataclass(frozen=True)
class Table:
    name: str            # circlepack name, e.g. "square", "rectangle_0.3", "nonagon"
    code: str            # Packomania prefix, e.g. "csq", "crc_300", "cno"
    path: str            # page path relative to BASE_URL
    normalization: str   # container normalisation used by the site
    drop: tuple[int, ...] = ()   # rows not used (inconsistent on the site)

    @property
    def url(self) -> str:
        return BASE_URL + self.path


_POLY = {5: ("pentagon", "cpt"), 6: ("hexagon", "chx"), 7: ("heptagon", "chp"), 8: ("octagon", "coc"),
         9: ("nonagon", "cno"), 10: ("decagon", "cdc"), 11: ("hendecagon", "chd"), 12: ("dodecagon", "cdd"),
         13: ("tridecagon", "ctd"), 14: ("tetradecagon", "crd"), 15: ("pentadecagon", "cpd"),
         16: ("hexadecagon", "cxd"), 17: ("heptadecagon", "ced")}
#: Regular polygon side count -> table name.
POLYGON_TABLES = {k: v[0] for k, v in _POLY.items()}

_N1_NOTE = ("N=1 dropped: the site row is half the inradius cos(pi/k), inconsistent with the "
            "circumradius-1 convention of the rows N>=2")


def _tables() -> dict[str, Table]:
    t = [
        Table("square", "csq", "csq/csq.html", "square of side 1, [-1/2, 1/2]^2"),
        Table("circle", "cci", "cci/cci.html", "circle of radius 1 centred at the origin"),
        Table("right_triangle", "crt", "crt/crt.html",
              "isosceles right triangle, legs 1, vertices (0,0), (1,0), (0,1)"),
        Table("quadrant", "ccq", "ccq/ccq.html", "circular quadrant (quarter disk) of radius 1"),
        Table("semicircle", "csc", "csc/csc.html", "semicircle (half disk) of radius 1"),
    ]
    for k in range(1, 9):
        t.append(Table(f"rectangle_0.{k}", f"crc_{k}00", f"crc_{k}00/crc.html",
                       f"rectangle 1 x 0.{k} (long side 1)"))
    for k, (name, code) in _POLY.items():
        t.append(Table(name, code, f"{code}/{code}.html", f"regular {k}-gon with circumradius 1",
                       drop=(1,) if code in ("cno", "cdc") else ()))
    return {x.name: x for x in t}


#: All supported tables, keyed by circlepack name.
TABLES: dict[str, Table] = _tables()
_BY_CODE = {t.code: t for t in TABLES.values()}


class RecordTableMissing(LookupError):
    """A supported record table has not been downloaded into the cache."""

    def __init__(self, name: str, directory: Path | None = None):
        self.name = name
        where = f" in {directory}" if directory else ""
        super().__init__(f"record table {name} not found{where}; run `circlepack records fetch --tables {name}`")

    def __str__(self) -> str:  # KeyError-like quoting is not wanted
        return self.args[0]


class FetchError(RuntimeError):
    """Download or parsing of a Packomania page failed."""


# ------------------------------------------------------------------ cache
def cache_dir() -> Path:
    """Directory holding the downloaded tables (not created here)."""
    env = os.environ.get("CIRCLEPACK_DATA")
    if env:
        return Path(env).expanduser()
    home = Path.home()
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return base / "circlepack" / "Cache" / "records"
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "circlepack" / "records"
    base = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    return base / "circlepack" / "records"


def table_info(name: str) -> Table:
    """Look a table up by circlepack name (``square``) or Packomania code (``csq``)."""
    if name in TABLES:
        return TABLES[name]
    if name in _BY_CODE:
        return _BY_CODE[name]
    raise KeyError(f"unknown record table {name!r}; supported: {supported()}")


def supported() -> list[str]:
    return sorted(TABLES)


def _path(t: Table, directory: Path | None = None) -> Path:
    return (directory or cache_dir()) / f"{t.code}.json"


def has_table(name: str) -> bool:
    return _path(table_info(name)).is_file()


def available() -> list[str]:
    """Names of the supported tables present in the cache."""
    d = cache_dir()
    return sorted(t.name for t in TABLES.values() if _path(t, d).is_file())


@lru_cache(maxsize=64)
def _read(path: str, mtime_ns: int) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load(name: str) -> dict:
    t = table_info(name)
    p = _path(t)
    try:
        return _read(str(p), p.stat().st_mtime_ns)
    except FileNotFoundError:
        raise RecordTableMissing(t.name, p.parent) from None


def load_table_meta(name: str) -> dict:
    """Provenance metadata of a cached table (everything except the radii)."""
    return {k: v for k, v in _load(name).items() if k != "radii"}


def load_records(name: str) -> dict[int, str]:
    """``{n: radius_string}`` for a table (strings keep all printed digits).

    Raises :class:`RecordTableMissing` if the table has not been fetched and
    ``KeyError`` for an unknown name.
    """
    return {int(n): r for n, r in _load(name)["radii"].items()}


def known_radius(name: str, n: int) -> float | None:
    """Best-known radius as float, ``None`` if the table has no entry for ``n``.

    Raises :class:`RecordTableMissing` if the table is not cached.
    """
    r = _load(name)["radii"].get(str(n))
    return None if r is None else float(r)


# ------------------------------------------------------------------ parsing
_TAG = re.compile(r"<[^>]*>")
_NUM = re.compile(r"^[0-9]+\.[0-9]+$")


def _text(s: str) -> str:
    return " ".join(html.unescape(_TAG.sub("", s)).split())


def parse_table_html(text: str) -> tuple[str | None, list[tuple[int, str, bool]]]:
    """Parse a Packomania summary page.

    Returns ``(last_update, rows)`` with rows ``(n, radius_string, bold)``
    in page order (``bold`` = printed in bold, i.e. proven optimal on the site).
    Rows whose first cell is not an integer or whose radius cell is not a
    plain decimal (references, footers) are ignored.
    """
    m = re.search(r"Last update:\s*([0-9]{1,2}-[A-Za-z]{3}-[0-9]{4})", text)
    last_update = m.group(1) if m else None
    heads = [_text(h).lower() for h in re.findall(r"<th\b[^>]*>(.*?)</th>", text, re.S | re.I)]
    col = next((i for i, h in enumerate(heads) if h == "radius"), 1)
    rows = []
    for row in re.split(r"<tr\b[^>]*>", text, flags=re.I)[1:]:
        row = re.split(r"</table>", row, flags=re.I)[0]
        cells = re.split(r"<td\b[^>]*>", row, flags=re.I)[1:]
        if len(cells) <= col:
            continue
        n_txt, r_raw = _text(cells[0]), cells[col]
        r_txt = _text(r_raw)
        if not n_txt.isdigit() or not _NUM.match(r_txt):
            continue
        rows.append((int(n_txt), r_txt, bool(re.search(r"<(strong|b)>", r_raw, re.I))))
    return last_update, rows


def _normalise(t: Table, rows: list[tuple[int, str, bool]]) -> tuple[dict[str, str], list[int], list[str]]:
    best: dict[int, tuple[str, bool]] = {}
    notes: list[str] = []
    dups: list[int] = []
    for n, r, bold in rows:
        if n in best:
            dups.append(n)
            if Decimal(r) <= Decimal(best[n][0]):
                continue
        best[n] = (r, bold)
    if dups:
        notes.append(f"duplicate rows for N={sorted(set(dups))}: kept the largest radius")
    dropped = [n for n in t.drop if n in best]
    for n in dropped:
        del best[n]
    if dropped:
        notes.append(_N1_NOTE if dropped == [1] else f"rows N={dropped} dropped")
    ns = sorted(best)
    return ({str(n): best[n][0] for n in ns}, [n for n in ns if best[n][1]], notes)


def build_cache_entry(t: Table, page: str, *, source: str, fetched_at: str | None = None) -> dict:
    """Parse a page into the JSON structure stored in the cache."""
    last_update, rows = parse_table_html(page)
    if not rows:
        raise FetchError(f"{t.name}: no record rows found in the page from {source} "
                         "(page layout changed or not a Packomania table page?)")
    radii, proven, notes = _normalise(t, rows)
    return {
        "format": CACHE_FORMAT,
        "name": t.name,
        "code": t.code,
        "source_url": t.url,
        "retrieved_from": source,
        "fetched_at": fetched_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "table_last_update": last_update,
        "normalization": t.normalization,
        "notes": notes,
        "attribution": "E. Specht, Packomania (www.packomania.com); radii are the work of their "
                       "respective discoverers. Not redistributed by circlepack.",
        "n_min": min(int(n) for n in radii),
        "n_max": max(int(n) for n in radii),
        "count": len(radii),
        "proven_optimal": proven,
        "radii": radii,
    }


# ------------------------------------------------------------------ fetching
def _download(url: str, timeout: float) -> tuple[bytes, str]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            charset = resp.headers.get_content_charset() or "latin-1"
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code} {e.reason} for {url}") from None
    except urllib.error.URLError as e:
        raise FetchError(f"cannot reach {url}: {e.reason} (offline? try again later or use --offline-from)") from None
    except (TimeoutError, OSError) as e:
        raise FetchError(f"network error for {url}: {e}") from None
    try:
        return data, data.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return data, data.decode("latin-1")


def _offline_page(t: Table, directory: Path) -> tuple[str, Path]:
    base = t.path.rsplit("/", 1)[-1]
    tried = [directory / f"{t.code}.html", directory / f"{t.code}_{base}", directory / t.path]
    for p in tried:
        if p.is_file():
            return p.read_bytes().decode("latin-1"), p
    raise FetchError(f"{t.name}: no saved page in {directory} (tried {', '.join(p.name for p in tried[:2])}, "
                     f"{t.path})")


def _resolve(tables: Iterable[str] | None) -> list[Table]:
    if not tables:
        return list(TABLES.values())
    out: list[Table] = []
    for item in tables:
        for name in str(item).split(","):
            name = name.strip()
            if not name:
                continue
            if name == "all":
                out.extend(TABLES.values())
                continue
            t = table_info(name)
            if t not in out:
                out.append(t)
    return out


def fetch_records(tables: Iterable[str] | None = None, *, force: bool = False,
                  delay: float = DEFAULT_DELAY, offline_from: str | os.PathLike | None = None,
                  dest: str | os.PathLike | None = None, save_html: str | os.PathLike | None = None,
                  timeout: float = DEFAULT_TIMEOUT,
                  log: Callable[[str], None] | None = print) -> dict[str, str]:
    """Download (or read saved) Packomania pages and write the cache.

    ``tables``: names or codes (``None`` = all supported tables). Tables
    already cached are skipped unless ``force``. ``delay`` seconds are waited
    between consecutive network requests (at least ``MIN_DELAY``). ``offline_from`` parses pages saved
    in a directory instead of downloading (no network access). ``save_html``
    keeps a copy of every downloaded page.

    Returns ``{name: status}`` with status ``"fetched"``, ``"cached"`` or
    ``"error: <message>"``.
    """
    log = log or (lambda s: None)
    delay = max(float(delay), MIN_DELAY)
    dest_dir = Path(dest).expanduser() if dest else cache_dir()
    off = Path(offline_from).expanduser() if offline_from is not None else None
    if off is not None and not off.is_dir():
        raise FetchError(f"--offline-from: {off} is not a directory")
    status: dict[str, str] = {}
    last_request: float | None = None
    for t in _resolve(tables):
        target = _path(t, dest_dir)
        if target.is_file() and not force:
            status[t.name] = "cached"
            log(f"{t.name} ({t.code}): already cached, skipped (use --force to refresh)")
            continue
        try:
            if off is not None:
                page, src = _offline_page(t, off)
                source = f"file:{src.name}"
            else:
                if last_request is not None:
                    time.sleep(max(0.0, delay - (time.monotonic() - last_request)))
                log(f"{t.name} ({t.code}): GET {t.url}")
                try:
                    raw, page = _download(t.url, timeout)
                finally:
                    last_request = time.monotonic()
                source = t.url
                if save_html:
                    sd = Path(save_html).expanduser()
                    sd.mkdir(parents=True, exist_ok=True)
                    (sd / f"{t.code}.html").write_bytes(raw)
            entry = build_cache_entry(t, page, source=source)
        except FetchError as e:
            status[t.name] = f"error: {e}"
            log(f"{t.name} ({t.code}): ERROR {e}")
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(entry, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, target)
        status[t.name] = "fetched"
        log(f"{t.name} ({t.code}): {entry['count']} radii, n = {entry['n_min']}..{entry['n_max']}, "
            f"last update {entry['table_last_update']} -> {target}")
    return status
