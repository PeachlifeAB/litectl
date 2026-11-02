# Testing

Test and task configuration lives in `pyproject.toml`.
QA policy lives in `tests/qa-policy.yml`.
Git hook configuration lives in `.pre-commit-config.yaml`.

## Commands

Install development and test dependencies:

```sh
uv sync --group test
```

| Check | Command |
| :---- | :------ |
| Tests | `uv run --group test poe test` |
| Lint | `uv run poe lint` |
| Formatting | `uv run poe fmt-check` |
| Types | `uv run poe typecheck` |
| Dead code | `uv run poe deadcode` |
| Repository quality | `uv run poe quality` |
| Architecture | `uv run poe arch` |
| Artifact conformance | `uv run poe conformance` |
| Build | `uv run poe build` |
| Commit checks | `uv run poe commit-check` |
| Aggregate validation | `uv run --group test poe validate` |

Repository quality requires `qlty`. The architecture task requires
`lint-imports`; no `[tool.importlinter]` contracts are currently declared
in `pyproject.toml`.

## Hook routing

The pre-commit hook runs `poe commit-check`: repository quality, lint, and
format verification.

The pre-push hook runs `poe validate`: repository quality, commit checks,
dead-code analysis, types, architecture, and tests. Install the test group
before running this hook.

Artifact conformance and builds are separate tasks, not part of `validate`.
Coverage, mutation, documentation, and CRAP tasks are not configured in
`pyproject.toml`. Policy requirements and helper scripts do not establish
that a gate runs or passes.
