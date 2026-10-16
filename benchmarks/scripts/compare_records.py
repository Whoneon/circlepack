"""Compare the stored benchmark results with the Packomania radii in the local cache.

The repository stores only our own results (``benchmarks/<table>/summary.json``
and the packings); the reference radii are not redistributed. Fetch them first::

    circlepack records fetch --tables square,circle,...
    python benchmarks/scripts/compare_records.py [benchmarks/square ...]

Prints, per n, the known radius, ours and the gap (known - ours).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from circlepack.records import RecordTableMissing, known_radius

ROOT = Path(__file__).resolve().parents[1]
#: benchmark directory -> record table (same name unless listed)
TABLE = {"large_circle": "circle", "large_square": "square"}


def compare(bench_dir: Path) -> int:
    table = TABLE.get(bench_dir.name, bench_dir.name)
    rows = json.loads((bench_dir / "summary.json").read_text())
    print(f"\n## {bench_dir.name} (table {table})\n")
    print("| n | known best | ours | gap |\n|---:|---:|---:|---:|")
    try:
        for row in rows:
            rec = known_radius(table, row["n"])
            gap = f"{rec - row['ours']:+.1e}" if rec is not None else "-"
            print(f"| {row['n']} | {rec if rec is not None else '-'} | {row['ours']:.12f} | {gap} |")
    except RecordTableMissing as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    dirs = [Path(a) for a in (argv if argv is not None else sys.argv[1:])]
    dirs = dirs or sorted(p.parent for p in ROOT.glob("*/summary.json"))
    return max((compare(d) for d in dirs), default=0)


if __name__ == "__main__":
    sys.exit(main())
