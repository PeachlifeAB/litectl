# QA contract

Policy: `tests/qa-policy.yml` (materialized in step 3 from
`setup-harness/resources/qa-policy.yml`, format `setup-harness-policy/v1`).
Routing procedure: `setup-harness/resources/ROUTING.md`.

Local check command: `uv run poe validate`.

## Classification

| Field | Value | Evidence |
| :---- | :---- | :------- |
| Tier | T1 | `pyproject.toml` declares `[project]`, `uv_build` backend, and the `litectl` entry point |
| Architecture profile | `modulithic_hexagonal_ddd` | Policy `routing.tiers.T1.architecture`; `src/litectl/modules/<id>/{domain,application,api,infrastructure}` matches the profile shape |
| Authorization | normal | No documented pre-authorized model for QA adoption; not an emergency |
| Adoption | initial | No `.harness-hash`, no `tests/qa-policy.yml`; policy `cadence.initial_adoption: full_applicable` |

`.repo.yaml` is absent and is created on the task branch during materialization.

## Baseline (verified before edits)

Branch `feat/openrouter-provider`, from commit `33370ee`.

| Check | Command | Result |
| :---- | :------ | :----- |
| tests | `uv run poe test` | 80 passed, 1 skipped |
| lint | `uv run poe lint` | All checks passed |
| format | `uv run poe fmt-check` | clean |
| types | `uv run poe typecheck` | no issues, 67 source files |
| quality | `uv run poe quality` | No issues |

## Resolved tool releases

Retrieved 2026-09-17 from official registries.

| Tool | Version | Requires | Source |
| :--- | :------ | :------- | :----- |
| import-linter | 2.15 | Python >=3.10 | `https://pypi.org/pypi/import-linter/json` |
| coverage | 7.16.1 | Python >=3.10 | `https://pypi.org/pypi/coverage/json` |
| @intentsolutions/audit-harness | 1.4.0 | Node >=18 | npm; gitHead `1003196bbfbd6e37875c8ebc3041b2d3221f51a9` |

Host runtimes: uv 0.12.15, Python 3.14.7, Node v26.8.2, npm 12.0.2.

## Gate rows

`owner | source scope | command | threshold | report | negative probe`

### Enforced today

| Gate | Owner | Source scope | Command | Threshold | Report | Negative probe |
| :--- | :---- | :----------- | :------ | :-------- | :----- | :------------- |
| static (lint) | ruff 0.16.4 | `src`, `tests` | `uv run poe lint` | 0 findings | stdout | introduce an unused import; require non-zero exit |
| static (format) | ruff | `src`, `tests` | `uv run poe fmt-check` | clean | stdout | reformat a file; require non-zero exit |
| static (types) | mypy 2.3.1 strict | `src`, `tests` | `uv run poe typecheck` | 0 errors | stdout | assign `str` to an `int`; require non-zero exit |
| tests | pytest 9.0 | `tests/` | `uv run poe test` | 0 failures, non-zero collection | stdout | break one assertion; require non-zero exit |
| repository_scan | qlty (bandit, trufflehog, ripgrep) | repository | `uv run poe quality` | 0 unresolved actionable | stdout | add a synthetic secret; require a finding |
| architecture | import-linter 2.15 (isolated tool) | `litectl` package graph | `uv run poe arch` | 0 violations | stdout | add a scratch internal import; require a finding |

### Required, not yet enforced

| Gate | Owner | Source scope | Command | Threshold | Report | Negative probe |
| :--- | :---- | :----------- | :------ | :-------- | :----- | :------------- |
| coverage | coverage 7.16.1 + `tests/coverage_gate.py` | all first-party production | `uv run poe coverage` | line >=90, branch >=85, enforced separately | `coverage.json` | 9 probes, see below |
| crap | coverage + complexity | all production functions (first adoption) | `uv run poe crap` | per-function CRAP < 13 | JSON rows | add an uncovered complex function; require a finding |
| mutation | mutmut 3.3.1 | all first-party production (first adoption) | `uv run poe mutate` | 0 actionable survivors, 0 unresolved dispositions | `mutants/` results | 586 survivors + 890 untested observed; gate FAILS |
| integrity | audit-harness 1.4.0 | pinned enforcement inputs | `audit-harness verify` | manifest matches | JSON | edit a pinned byte; require failure |
| escape_scan | audit-harness | staged / push range | `audit-harness escape-scan --staged` | 0 escapes | JSON | stage a suppression; require failure |
| conformance_artifacts | audit-harness `conform` + JSON Schema | `src/litectl/resources/**/*.yaml`, installed `config.yaml` | `audit-harness conform` | 0 unvalidated declared artifacts | JSON | add an unknown key to a provider file; require rejection |
| install_smoke | uv + wheel | built distribution | fresh-env install + `litectl --help` | entry point runs from outside the checkout | log | remove a declared dependency; require install failure |
| test_bias | audit-harness `bias` | `tests/` | `audit-harness bias tests` | 0 unresolved actionable | JSON | add an assertion-free test; require a finding |
| documentation | markdownlint-cli2, cspell, write-good, lychee | `*.md` | `uv run poe docs` | 0 unresolved actionable | JSON | add a broken link; require a finding |
| testing_depth | audit-harness `audit` | declared pyramid layers | `audit-harness audit --fast --strict` | no absent declared layer | JSON | remove a declared layer; require failure |
| duplication | qlty smells | production and tests | `uv run poe quality` | duplicate <= 5%, clones >= 80 tokens reviewed | stdout | clone a 100-token block; require a finding |

### Not applicable

| Gate | Reason | Evidence |
| :--- | :----- | :------- |
| gherkin | No acceptance features in the repository | no `features/`, no `*.feature` |
| scaffold_output | litectl generates user configuration, not projects or QA harnesses | `MANIFEST` writes `config.yaml` and provider files only |

## Open findings

Recorded during inventory; each blocks verified closure until resolved.

1. **Dead qlty triage rules.** `.qlty/qlty.toml:96,105` suppress `bandit:B310`,
   `B404` and `B603` on `src/modules/workspace/infrastructure/*.py` and
   `template/tasks/infrastructure/*.py`. Neither path exists; the real path is
   `src/litectl/modules/workspace/infrastructure/`. Inert today because the call
   sites carry inline `# nosec`, so `poe quality` reports no issues, but the
   rules advertise coverage they do not provide.


2. **`duplication` runs advisory.** `.qlty/qlty.toml` sets `[smells] mode = "comment"`.
   Policy `execution.advisory_required_gate: fail` requires blocking mode once promoted.

3. **`vulture` exits zero with no output.** Policy `execution.unexpected_empty_scope: fail`
   requires a negative probe proving the check can fail.

4. **No CI.** `.github/` is absent, so the `pre_push` and `ci` cadence rows have
   no execution path. Pre-commit hooks exist in `.pre-commit-config.yaml`
   (`commit-check` on commit, `validate` on push).

## Architecture gate — materialized and proven

Contracts live in `[tool.importlinter]` in `pyproject.toml`. `uv run poe arch` is wired
into `poe validate` and now exits 0 on the current 87-file, 213-dependency graph.
import-linter runs as an isolated `uv tool` because LiteLLM pins an older `rich`.

| Contract | Status | Negative probe | Probe result |
| :------- | :----- | :------------- | :----------- |
| `module-layers` | KEPT | `domain/_probe.py` imports `infrastructure.storage` | BROKEN, only this contract |
| `bounded-contexts-independent` | KEPT | `workspace/domain/_probe.py` imports `catalog.domain.seed` | BROKEN, only this contract |
| `modules-not-app` | KEPT | `catalog/domain/_probe.py` imports `litectl.app.paths` | BROKEN, only this contract |
| `pure-domain` | KEPT | `catalog/domain/_probe.py` imports `subprocess` | BROKEN, only this contract |
| `app-uses-public-roots` | KEPT | scratch `app` import of module infrastructure | BROKEN, only this contract |

The public-root refactor added `catalog/index.py`, `workspace/index.py`, and
`workspace/__init__.py`; global composition now imports those roots only. The package
entrypoint lazy-loads `app.cli`, preventing an indirect bounded-context cycle.

## Coverage gate — materialized, currently FAILING

Command: `uv run poe coverage` (run -> json -> gate). The enforcement step is
`tests/coverage_gate.py`, a project-owned checker, because no single coverage
flag enforces both metrics separately: `--fail-under` compares one blended
percentage and policy sets `combined_percentage_as_substitute: forbidden`.

Measured on the current tree, 2026-09-17:

| Metric | Measured | Floor | Verdict |
| :----- | -------: | ----: | :------ |
| line (statements) | 73.34% | 90% | **FAIL** |
| branch | 50.56% | 85% | **FAIL** |

The blended `percent_covered` is 68.97%, which is neither of the enforced
numbers; it is recorded here only to show why the blend is not the verdict.

Lowest-covered production files, for the work this gate implies:

| Coverage | Statements | File |
| -------: | ---------: | :--- |
| 0.0% | 2 | `src/litectl/__main__.py` |
| 0.0% | 4 | `src/litectl/app/bootstrap.py` |
| 16.0% | 38 | `src/litectl/modules/workspace/api/verify.py` |
| 20.9% | 31 | `src/litectl/modules/catalog/api/discover.py` |
| 22.6% | 23 | `src/litectl/modules/catalog/list_models.py` |
| 25.0% | 12 | `src/litectl/app/teardown.py` |
| 35.0% | 85 | `src/litectl/modules/workspace/infrastructure/healthcheck.py` |
| 36.8% | 30 | `src/litectl/modules/workspace/api/resolve.py` |

Gate behaviour proven by probe, and by `tests/test_coverage_gate.py` (10 tests):

| Probe | Expected | Observed |
| :---- | :------- | :------- |
| real report | exit 1, both FAIL | exit 1 |
| synthetic 95.5 / 88.2 | exit 0 | exit 0 |
| exactly 90.0 / 85.0 | exit 0, floor inclusive | exit 0 |
| line 89.9, branch 99.0 | exit 1 | exit 1 |
| line 99.0, branch 84.9 | exit 1 | exit 1 |
| line 92.0, branch 60.0 (blend 86) | exit 1 | exit 1 |
| missing report | exit 2 BLOCKED | exit 2 |
| `meta.branch_coverage: false` | exit 2 BLOCKED | exit 2 |
| empty `files` / malformed JSON | exit 2 BLOCKED | exit 2 |

The blend probe is the load-bearing one: a single `--fail-under=85` against
86% would report success while branch coverage sat at 60%.

An absent or unscoreable report exits 2 and is BLOCKED, never a pass, per
`coverage.unsupported_required_metric: blocked`. Percentages come from
`percent_statements_covered` and `percent_branches_covered`; the `*_display`
fields are pre-rounded strings and are not read.

`poe coverage` is wired into `poe validate` and fails it today, on the same
terms as `app-uses-public-roots`: a required gate is not disabled or deferred
because the code does not yet satisfy it
(`disabled_required_gate: fail`). Raising coverage to the floors is the work
this gate now blocks on; `poe validate` stays red until then.

## CRAP gate — materialized, currently FAILING

Command: `uv run poe crap`. Runs the harness scorer with `--threshold-prod 13`
passed explicitly, because the tool's own default is 30 and policy sets
`crap.exclusive_max: 13`. Needs `coverage.json`, so `poe coverage` runs first,
and `radon==6.0.1` (dev group) for complexity.

193 production methods scored; average CRAP 4.15; **6 blockers** over 13:

| CRAP | Complexity | File coverage | Function |
| ---: | ---------: | ------------: | :------- |
| 41.48 | 11 | 36.8% | `workspace/api/resolve.py::ensure_provider` |
| 37.52 | 10 | 35.0% | `workspace/infrastructure/healthcheck.py::list_models` |
| 31.89 | 9 | 34.4% | `catalog/api/prompts.py::prompt_for_recovery` |
| 20.49 | 7 | 35.0% | `workspace/infrastructure/healthcheck.py::_completion_content` |
| 15.91 | 6 | 35.0% | `workspace/infrastructure/healthcheck.py::choose_model` |
| 13.48 | 4 | 16.0% | `workspace/api/verify.py::verify` |

Every blocker is coverage-driven, not complexity-driven: the highest cyclomatic
complexity is 11 and `verify` is only 4. These clear when the coverage gate
does; they are the same debt seen per function.

Probed both ways: at `--threshold-prod 50` the gate returns PASS with 0
blockers, at 13 it returns FAIL with 6. The gate is threshold-bound, not
permanently red.

The scorer uses **file-level** `percent_covered` as each function's coverage,
not a per-function fraction. Policy asks for `measured_function_fraction`, so
this is a conservative approximation recorded as such: a well-covered file can
mask a poorly covered function inside it. Verdicts are bound-based, and the
coverage gate retains its own separate measurement requirement.

## Mutation gate — RUNNING, currently FAILING

Command: `uv run poe mutate`. Configured in `[tool.mutmut]`:
`paths_to_mutate = ["src/litectl/"]`, `tests_dir = ["tests/"]`,
`also_copy = ["README.md", "uv.lock", ".python-version", "install.sh"]`.

2640 mutants across first-party production:

| Outcome | Count |
| :------ | ----: |
| killed | 1160 |
| survived | **586** |
| no tests | **890** |
| timeout | 4 |

FAIL under `mutation.actionable_survivors_max: 0`. 586 survivors and 890
untested mutants are the finding; no exclusion is claimed and none is needed.

Survivors concentrate in `catalog.infrastructure` (206), `workspace.infrastructure`
(113) and `app` (111). Untested mutants concentrate in
`workspace.infrastructure` (287), `workspace.api` (160) and `catalog` (151) --
the same install and service paths the coverage gate reports at 35-40%.

### Correction: the earlier segfault diagnosis was wrong

An earlier run reported 1750 segfaults and 0 tested mutants, which was recorded
here as BLOCKED with a claim that `src/litectl/serve.py` re-importing `uvicorn`
and `watchfiles` in-process crashed the interpreter, and that excluding it via
`do_not_mutate` would need approval as a scope exclusion.

That diagnosis was incorrect. The cause was `tests/conftest.py::project_root`,
which walks parents for a directory containing both `pyproject.toml` and
`install.sh`. `install.sh` was missing from `also_copy`, so the fixture raised
inside `mutants/` and every test using it failed before running. Adding
`install.sh` resolved all 1750 segfaults. No native-extension problem exists,
no exclusion is required, and the approval previously requested was unnecessary.

Two missing-file defects of the same class were found in sequence:
`README.md` (declared as `readme` in `pyproject.toml`, needed by the build) and
`install.sh` (needed by a test fixture). Both produced 0 tested mutants while
`mutmut run` exited 0.

### Superseded run history

Command: `uv run poe mutate`. Configured in `[tool.mutmut]`:
`paths_to_mutate = ["src/litectl/"]`, `tests_dir = ["tests/"]`,
`also_copy = ["README.md", "uv.lock", ".python-version"]`.

2640 mutants are generated across first-party production. **None can currently
be validly tested**, so the gate is BLOCKED under
`mutation.untested_mutants: fail`, `unresolved_mutation_errors: fail` and
`zero_mutants_with_eligible_source: unverified`. It is not a pass and must not
be recorded as one.

Run history, each a distinct defect:

| Run | Result | Cause |
| :-- | :----- | :---- |
| 1, `--max-children 4` | 2640 mutants, 0 killed, 0 survived | `mutants/` copy lacked `README.md`, which `pyproject.toml` declares as `readme`; the wheel build failed so no test ran |
| 2, after `also_copy` | crash mid-run | parallel mutants share pytest's `tmp_path` root and race deleting `pytest-current` |
| 3, `--max-children 1` | 2640 mutants: 1750 segfault, 890 no tests | `install.sh` missing from `also_copy`; fixture raised before any test ran |
| 4, after `install.sh` | 1160 killed, 586 survived, 890 no tests, 4 timeout | gate operational; survivors are the real finding |

`mutmut run` exits 0 in every one of these cases, including when nothing was
tested. The exit status is not the verdict; result rows are, and the task must
parse them.

Run serially. With `--max-children 4`, parallel mutants share pytest's
`tmp_path` root and race deleting `pytest-current`, which crashes the run.

## Verified architecture properties

Checked by hand during inventory; mechanical enforcement pending (finding 2).

- No sibling imports: `grep` for `litectl.modules.catalog` inside `workspace/`
  and `litectl.modules.workspace` inside `catalog/` returns nothing.
- Layer direction holds within each module: no `domain` file imports `api`,
  `application` or `infrastructure`.
- Domain purity is enforced narrowly by ruff `TID251`, which bans `subprocess`,
  `sys.stdin`, `argparse`, `urllib.request`, `urllib.error` and `requests` by
  name. That is an API ban, not a layer-direction check.
