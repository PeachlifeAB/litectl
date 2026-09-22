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

### Required and enforced

| Gate | Owner | Source scope | Command | Threshold | Report | Negative probe |
| :--- | :---- | :----------- | :------ | :-------- | :----- | :------------- |
| coverage | coverage 7.16.1 + `tests/coverage_gate.py` | all first-party production | `uv run poe coverage` | line >=90, branch >=85, enforced separately | `coverage.json` | 9 probes, see below |
| crap | coverage + complexity | all production functions (first adoption) | `uv run poe crap` | per-function CRAP < 13 | JSON rows | add an uncovered complex function; require a finding |
| mutation | mutmut 3.8.0 + `tests/mutation_gate.py` | all first-party production (first adoption) | `uv run poe mutate` (mutmut, then disposition parser) | 0 actionable survivors, 0 unresolved dispositions | `mutants/` results + stdout | focused reconcile check: 52 killed, 3 reviewed equivalent; full baseline failing |
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

## Coverage gate — enforced and green

Command: `uv run poe coverage` (run -> json -> gate). The project-owned
`tests/coverage_gate.py` enforces line and branch floors separately because
a blended `--fail-under` value cannot substitute for branch coverage.

Measured on the current candidate:

| Metric | Measured | Floor | Verdict |
| :----- | -------: | ----: | :------ |
| line (statements) | 93.79% | 90% | **PASS** |
| branch | 85.90% | 85% | **PASS** |

Startup reconciliation runs before `start` and `serve`, uses the recorded
provider base and key when process environment variables are absent, and
prunes stale local fallback aliases without rewriting unchanged config.

## CRAP gate — materialized and green

Command: `uv run poe crap`. It runs the project-owned scorer with the policy
thresholds (`production_max=13`, `project_avg_max=10`). It reads `coverage.json`
and uses the pinned Radon runtime.

Current result: 201 production methods scored; maximum CRAP 12.00; average
CRAP 3.02; 0 blockers.

## Mutation gate — focused evidence; full baseline failing

Command: `uv run poe mutate`. Configuration uses mutmut 3.8.0 with
`source_paths`, `pytest_add_cli_args_test_selection`, explicit
`mutate_only_covered_lines = false`, and the required `also_copy` files.

Focused `reconcile_local_models` run: 55 mutants generated, 52 killed, 3
survived, 0 segfaults, and 0 untested. The three survivors are reviewed
equivalences, not killed mutants:

- `config_path.exists() or True` is equivalent because `update_config`
  materializes `config.yaml` before the comparison.
- `encoding="UTF-8"` is the same codec name as `"utf-8"`.
- The fallback string `"XXXX"` is unreachable under the same config invariant.

Full current first-adoption run: 3,050 mutants; 2,023 killed, 853 survived,
169 had no tests, and 5 timed out. The mutation gate therefore remains FAIL
under the zero-survivor policy; focused evidence does not replace this gate.

## Verified architecture properties

Checked by hand during inventory; mechanical enforcement pending (finding 2).

- No sibling imports: `grep` for `litectl.modules.catalog` inside `workspace/`
  and `litectl.modules.workspace` inside `catalog/` returns nothing.
- Layer direction holds within each module: no `domain` file imports `api`,
  `application` or `infrastructure`.
- Domain purity is enforced narrowly by ruff `TID251`, which bans `subprocess`,
  `sys.stdin`, `argparse`, `urllib.request`, `urllib.error` and `requests` by
  name. That is an API ban, not a layer-direction check.
