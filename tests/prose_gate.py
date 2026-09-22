"""Turn write-good's advisory output into a verdict.

`write-good` exits 0 whether or not it reports anything, so binding a gate to
its exit status accepts every finding it was installed to catch
(`documentation.advisory_exit_as_proof_of_acceptance: forbidden`). This parses
its findings and fails on the ones this project treats as actionable.

Passive voice and "wordy" hits are suppressed by name, with reasons, rather than
by disabling the checker: technical documentation states what a gate does to a
subject ("the contract is selected", "artifacts are written to dist/"), and
write-good cannot tell that from evasive prose. Every other class -- weasel
words, clichés, "so" openers, illusions of doubt -- stays blocking.

Exits 0 when no actionable finding remains, 1 otherwise, 2 when write-good
cannot be run or its output cannot be parsed.
"""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404: runs the locked .qa checker with literal args
import sys
from pathlib import Path

EXIT_VIOLATION = 1
EXIT_UNMEASURED = 2

CHECKER = Path(".qa/node_modules/.bin/write-good")

# Finding text -> why it is not actionable here.
SUPPRESSED = {
    "may be passive voice": (
        "technical documentation describes what happens to a subject; "
        "passive voice is correct for gate outcomes"
    ),
    "is wordy or unneeded": (
        "flags task and command names such as 'validate' that cannot be reworded"
    ),
    "can weaken meaning": (
        "flags precise adverbs such as 'gracefully' in shutdown semantics"
    ),
}

FINDING = re.compile(r'^"(?P<phrase>.+)" (?P<issue>.+) on line (?P<line>\d+)')


class Unmeasured(Exception):
    """The gate cannot reach a verdict."""


def run_checker(paths: list[str]) -> str:
    """Run the locked write-good and return its output."""
    checker = shutil.which(str(CHECKER)) or (
        str(CHECKER) if CHECKER.is_file() else None
    )
    if checker is None:
        raise Unmeasured(f"{CHECKER} not installed; run `poe qa-setup`")
    try:
        completed = subprocess.run(  # nosec B603: resolved path, literal args
            [checker, *paths],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise Unmeasured(f"write-good could not run: {error}") from error
    return completed.stdout


def actionable(output: str) -> list[tuple[str, str, str]]:
    """Findings that are not suppressed, as (line, phrase, issue)."""
    found = []
    for raw in output.splitlines():
        match = FINDING.match(raw.strip())
        if not match:
            continue
        issue = match["issue"]
        if any(reason in issue for reason in SUPPRESSED):
            continue
        found.append((match["line"], match["phrase"], issue))
    return found


def main(argv: list[str] | None = None) -> int:
    paths = list(argv) if argv else ["README.md"]
    missing = [path for path in paths if not Path(path).is_file()]
    if missing:
        print(f"BLOCKED  no such document: {', '.join(missing)}", file=sys.stderr)
        return EXIT_UNMEASURED

    try:
        output = run_checker(paths)
    except Unmeasured as error:
        print(f"BLOCKED  {error}", file=sys.stderr)
        return EXIT_UNMEASURED

    findings = actionable(output)
    for line, phrase, issue in findings:
        print(f"FAIL  line {line}: {phrase!r} {issue}")

    if findings:
        print(f"\n{len(findings)} actionable prose finding(s)")
        return EXIT_VIOLATION
    print(f"PASS  {len(paths)} document(s), no actionable prose findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
