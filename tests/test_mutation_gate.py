from __future__ import annotations

import json
from pathlib import Path

import pytest
from mutation_gate import Disposition, load_dispositions, main, parse_results


def write_record(path: Path, dispositions: list[dict[str, str]]) -> Path:
    path.write_text(
        json.dumps({"version": 1, "dispositions": dispositions}),
        encoding="utf-8",
    )
    return path


def test_load_dispositions_accepts_empty_record(tmp_path: Path) -> None:
    record = write_record(tmp_path / "dispositions.json", [])

    assert load_dispositions(record) == {}


def test_load_dispositions_indexes_valid_entries(tmp_path: Path) -> None:
    record = write_record(
        tmp_path / "dispositions.json",
        [
            {
                "id": "litectl.serve.x_mutant__mutmut_1",
                "category": "equivalent",
                "reason": "The branch is unreachable under the validated config.",
                "date": "2026-09-22",
            }
        ],
    )

    assert load_dispositions(record) == {
        "litectl.serve.x_mutant__mutmut_1": Disposition(
            mutant_id="litectl.serve.x_mutant__mutmut_1",
            category="equivalent",
            reason="The branch is unreachable under the validated config.",
            date="2026-09-22",
        )
    }


@pytest.mark.parametrize("category", ["", "killed", "ignored"])
def test_load_dispositions_rejects_unknown_categories(
    tmp_path: Path, category: str
) -> None:
    record = write_record(
        tmp_path / "dispositions.json",
        [
            {
                "id": "mutant",
                "category": category,
                "reason": "reason",
                "date": "2026-09-22",
            }
        ],
    )

    with pytest.raises(ValueError, match="category"):
        load_dispositions(record)


def test_parse_results_reads_mutant_rows_only() -> None:
    output = """
    litectl.serve.x_first__mutmut_1: killed
    litectl.serve.x_second__mutmut_1: no tests
3050 matches in 1 files:
"""

    assert parse_results(output) == {
        "litectl.serve.x_first__mutmut_1": "killed",
        "litectl.serve.x_second__mutmut_1": "no tests",
    }


def test_main_fails_unrecorded_survivors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = write_record(tmp_path / "dispositions.json", [])
    output = "    litectl.serve.x_first__mutmut_1: survived\n"

    assert main([str(record)], lambda: output) == 1
    assert capsys.readouterr().out == (
        "FAIL mutation gate: 1 actionable result(s).\n"
        "  litectl.serve.x_first__mutmut_1: survived\n"
    )


def test_main_accepts_dispositioned_survivors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = write_record(
        tmp_path / "dispositions.json",
        [
            {
                "id": "litectl.serve.x_first__mutmut_1",
                "category": "equivalent",
                "reason": "The branch is unreachable under the validated config.",
                "date": "2026-09-22",
            }
        ],
    )
    output = "    litectl.serve.x_first__mutmut_1: survived\n"

    assert main([str(record)], lambda: output) == 0
    assert capsys.readouterr().out == "PASS mutation gate: 1 result(s).\n"
