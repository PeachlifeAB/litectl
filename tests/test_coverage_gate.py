from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from coverage_gate import EXIT_BREACH, EXIT_UNMEASURED, main

PASSING = {"percent_statements_covered": 95.5, "percent_branches_covered": 88.2}


def write_report(path: Path, totals: Mapping[str, object], **overrides: object) -> Path:
    payload: dict[str, object] = {
        "meta": {"branch_coverage": True},
        "files": {"a.py": {}},
        "totals": totals,
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_both_floors_met_passes(tmp_path: Path) -> None:
    report = write_report(tmp_path / "c.json", PASSING)

    assert main([str(report)]) == 0


@pytest.mark.parametrize(
    ("totals", "reason"),
    [
        (
            {"percent_statements_covered": 89.9, "percent_branches_covered": 99.0},
            "line",
        ),
        (
            {"percent_statements_covered": 99.0, "percent_branches_covered": 84.9},
            "branch",
        ),
    ],
)
def test_either_floor_breached_fails(
    tmp_path: Path, totals: dict[str, object], reason: str
) -> None:
    report = write_report(tmp_path / f"{reason}.json", totals)

    assert main([str(report)]) == EXIT_BREACH


def test_high_line_never_compensates_for_low_branch(tmp_path: Path) -> None:
    """The blended percentage would pass; separate enforcement must not."""
    report = write_report(
        tmp_path / "blend.json",
        {"percent_statements_covered": 92.0, "percent_branches_covered": 60.0},
        # A single --fail-under=85 against this blend would report success.
        totals_blend=86.0,
    )

    assert main([str(report)]) == EXIT_BREACH


def test_floor_is_inclusive(tmp_path: Path) -> None:
    report = write_report(
        tmp_path / "exact.json",
        {"percent_statements_covered": 90.0, "percent_branches_covered": 85.0},
    )

    assert main([str(report)]) == 0


def test_missing_report_is_blocked_not_passed(tmp_path: Path) -> None:
    assert main([str(tmp_path / "absent.json")]) == EXIT_UNMEASURED


def test_report_without_branch_measurement_is_blocked(tmp_path: Path) -> None:
    report = write_report(
        tmp_path / "nobranch.json", PASSING, meta={"branch_coverage": False}
    )

    assert main([str(report)]) == EXIT_UNMEASURED


def test_report_covering_no_files_is_blocked(tmp_path: Path) -> None:
    report = write_report(tmp_path / "empty.json", PASSING, files={})

    assert main([str(report)]) == EXIT_UNMEASURED


def test_unreadable_report_is_blocked(tmp_path: Path) -> None:
    report = tmp_path / "broken.json"
    report.write_text("{not json", encoding="utf-8")

    assert main([str(report)]) == EXIT_UNMEASURED


def test_non_numeric_percentage_is_blocked(tmp_path: Path) -> None:
    report = write_report(
        tmp_path / "rounded.json",
        {"percent_statements_covered": "95", "percent_branches_covered": 88.2},
    )

    assert main([str(report)]) == EXIT_UNMEASURED
