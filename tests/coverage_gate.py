"""Enforce line and branch coverage floors separately.

`coverage --fail-under` compares one blended percentage, which policy rejects
(`combined_percentage_as_substitute: forbidden`): in this report `percent_covered`
is 68.97 while statements are 73.34 and branches 50.56, so the blend hides which
metric actually breached. This reads the JSON report and checks each metric
against its own floor, using the unrounded values coverage already computed. The
`*_display` fields are rounded strings and must not be used
(`rounding_before_comparison: forbidden`).

Schema verified against coverage 7.16.1, report format 3; see
`.gdog/docs/coverage-json-schema.txt`.

Exits 0 when both floors hold, 1 on a breach, 2 when the report is missing,
empty, unreadable, or was produced without branch measurement -- an absent
measurement is a blocked gate, never a pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LINE_FLOOR = 90.0
BRANCH_FLOOR = 85.0
EXIT_BREACH = 1
EXIT_UNMEASURED = 2


class Unmeasured(Exception):
    """The report cannot support a verdict."""


def read_totals(path: Path) -> dict[str, object]:
    """Parse a coverage JSON report, refusing anything that cannot be scored."""
    if not path.exists():
        raise Unmeasured(f"no coverage report at {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Unmeasured(f"unreadable coverage report: {error}") from error
    if not isinstance(payload, dict):
        raise Unmeasured("coverage report is not an object")
    if not payload.get("files"):
        raise Unmeasured("coverage report covers no files")
    meta = payload.get("meta")
    if not isinstance(meta, dict) or not meta.get("branch_coverage"):
        raise Unmeasured("report was produced without branch measurement")
    totals = payload.get("totals")
    if not isinstance(totals, dict):
        raise Unmeasured("coverage report has no totals block")
    return totals


def measured(totals: dict[str, object], key: str) -> float:
    """One unrounded percentage from the totals block."""
    value = totals.get(key)
    if not isinstance(value, (int, float)):
        raise Unmeasured(f"totals.{key} is missing or not numeric")
    return float(value)


def evaluate(totals: dict[str, object]) -> list[tuple[str, float, float, bool]]:
    """Each metric with its floor and whether it holds."""
    line = measured(totals, "percent_statements_covered")
    branch = measured(totals, "percent_branches_covered")
    return [
        ("line", line, LINE_FLOOR, line >= LINE_FLOOR),
        ("branch", branch, BRANCH_FLOOR, branch >= BRANCH_FLOOR),
    ]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    report = Path(args[0]) if args else Path("coverage.json")
    try:
        results = evaluate(read_totals(report))
    except Unmeasured as error:
        print(f"BLOCKED  coverage unmeasured: {error}", file=sys.stderr)
        return EXIT_UNMEASURED

    for metric, value, floor, ok in results:
        verdict = "PASS" if ok else "FAIL"
        print(f"{verdict}  {metric:6} {value:6.2f}%  floor {floor:.1f}%")
    return 0 if all(ok for *_, ok in results) else EXIT_BREACH


if __name__ == "__main__":
    raise SystemExit(main())
