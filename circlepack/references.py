"""Reference radii for campaigns: Packomania tables and Moki & Julio claims.

* Packomania: the local records cache filled by ``circlepack records fetch``
  (see :mod:`circlepack.records`) is the primary source. Optionally a directory
  of CSV tables ``<dir>/<code>.csv`` (columns ``n, radius, ...``) overrides the
  cache table by table (``packomania_dir`` in a campaign file). A table found in
  neither place gives no Packomania reference.
* Moki & Julio (optional): ``MANIFEST.csv`` of
  github.com/Hashirama1337s/moki-julio-circle-packing (columns ``shelf, N,
  published_radius, new_radius, ...``); only ``new_radius`` (their claimed
  radius) is used. Without a manifest there is no Moki & Julio reference.

Radii are kept as decimal strings (Packomania prints 12 to 30 digits) and
compared with :class:`decimal.Decimal`; see :func:`classify`.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, getcontext
from pathlib import Path

from .records import RecordTableMissing, load_records

getcontext().prec = 50

__all__ = ["TABLE_SPECS", "table_spec", "load_packomania", "load_moki_julio", "Reference",
           "classify", "REL_TOL"]

#: Packomania code -> container spec (Packomania normalisation, checked against
#: the tables at small n: polygons circumradius 1, rectangles 1 x h centred at
#: the origin, crt legs 1, ccq/csc radius 1).
TABLE_SPECS: dict[str, dict] = {
    "csq": {"type": "square"},
    "cci": {"type": "circle"},
    "crt": {"type": "right_isosceles_triangle"},
    "ccq": {"type": "quadrant"},
    "csc": {"type": "semicircle"},
    **{f"crc_{h}": {"type": "rectangle", "width": 1.0, "height": h / 1000} for h in range(100, 900, 100)},
    **{code: {"type": "regular_polygon", "k": k} for code, k in [
        ("cpt", 5), ("chx", 6), ("chp", 7), ("coc", 8), ("cno", 9), ("cdc", 10), ("chd", 11),
        ("cdd", 12), ("ctd", 13), ("crd", 14), ("cpd", 15), ("cxd", 16), ("ced", 17)]},
}

#: relative margin by which a radius must exceed the best reference to count as a beat
REL_TOL = Decimal("1e-12")


def table_spec(code: str) -> dict:
    try:
        return dict(TABLE_SPECS[code])
    except KeyError:
        raise KeyError(f"unknown Packomania table {code!r}; known: {sorted(TABLE_SPECS)}") from None


def load_packomania(code: str, directory: str | Path | None) -> dict[int, str]:
    """``{n: radius_string}`` for a Packomania code; empty if no table is found.

    ``<directory>/<code>.csv`` is used if it exists (optional override),
    otherwise the records cache (``circlepack records fetch``).
    """
    if directory is not None:
        p = Path(directory) / f"{code}.csv"
        if p.is_file():
            with open(p, newline="") as f:
                return {int(row["n"]): row["radius"].strip() for row in csv.DictReader(f)
                        if row.get("radius", "").strip()}
    try:
        return load_records(code)
    except (RecordTableMissing, KeyError):
        return {}


def load_moki_julio(manifest: str | Path | None) -> dict[tuple[str, int], str]:
    """``{(shelf, n): claimed_radius_string}`` from their MANIFEST.csv (empty if absent)."""
    if manifest is None or not Path(manifest).is_file():
        return {}
    out: dict[tuple[str, int], str] = {}
    with open(manifest, newline="") as f:
        for row in csv.DictReader(f):
            try:
                key = (row["shelf"].strip(), int(row["N"]))
                r = row["new_radius"].strip()
                Decimal(r)
            except (KeyError, ValueError, ArithmeticError):
                continue
            if key not in out or Decimal(r) > Decimal(out[key]):
                out[key] = r
    return out


def _decimals(s: str | None) -> int | None:
    if not s or "." not in s or "e" in s.lower():
        return None
    return len(s.split(".", 1)[1])


@dataclass(frozen=True)
class Reference:
    packomania: str | None = None
    moki_julio: str | None = None

    @property
    def best(self) -> Decimal | None:
        vals = [Decimal(v) for v in (self.packomania, self.moki_julio) if v]
        return max(vals) if vals else None

    @property
    def best_float(self) -> float | None:
        b = self.best
        return None if b is None else float(b)

    @property
    def print_ulp(self) -> Decimal | None:
        """One unit in the last printed digit of the best reference (truncation uncertainty)."""
        b = self.best
        if b is None:
            return None
        s = self.packomania if self.packomania and Decimal(self.packomania) == b else self.moki_julio
        d = _decimals(s)
        return None if d is None else Decimal(1).scaleb(-d)


def classify(r: float, ref: Reference, exact_ok: bool, rel_tol: Decimal = REL_TOL) -> str:
    """Compare a radius with ``max(packomania, moki_julio)``.

    Returns one of

    ``RECORD CANDIDATE``  exact verification passed and ``r > best * (1 + rel_tol)``
                          and the excess is larger than the printed precision of the
                          reference (so it cannot be a truncation artefact);
    ``MARGINAL``          exact verification passed and ``r > best * (1 + rel_tol)``,
                          but by less than one unit in the last printed digit;
    ``MATCH``             ``|r - best| <= 1e-9 best``;
    ``BELOW``             otherwise; ``NO REFERENCE`` / ``UNVERIFIED`` as named.
    """
    best = ref.best
    if best is None:
        return "NO REFERENCE"
    R = Decimal(repr(float(r)))
    if R > best * (1 + rel_tol):
        if not exact_ok:
            return "UNVERIFIED"
        ulp = ref.print_ulp
        return "RECORD CANDIDATE" if ulp is None or R - best > ulp else "MARGINAL"
    if R >= best * (1 - Decimal("1e-9")):
        return "MATCH"
    return "BELOW"
