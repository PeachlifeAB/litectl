# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd prime` for full workflow context.

> **Architecture in one line:** Issues live in a local Dolt database
> (`.beads/dolt/`); cross-machine sync uses `bd dolt push/pull` (a
> git-compatible protocol), stored under `refs/dolt/data` on your git
> remote — separate from `refs/heads/*` where your code lives.
> `.beads/issues.jsonl` is a passive export, not the wire protocol.
>
> See [sync-concepts](https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md)
> for the one-screen overview and anti-patterns (don't treat JSONL as the
> source of truth; don't `bd import` during normal operation; don't
> reach for third-party Dolt hosting before trying the default).

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
bd dolt push          # Push beads data to remote
```

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

## Mutation Testing & Asyncio Gotchas (mutmut 3.8)

Hints from hard-won debugging, not rules. `qa-policy` covers the gate discipline
(scope, closure re-run, survivor and equivalence recording); these are the
tool-specific and asyncio traps it leaves out.

**Fast single-mutant iteration.** `mutmut run <name>` regenerates every mutant
(cheap, in-process) but *tests* a single named mutant — that per-mutant
subprocess run is the slow part. Fix a mutant, retest it with
`mutmut run <name>`, and repeat. Save the full `mutmut run` (no names) for a
*batch* or at closure, not after each single fix.

**`mutmut apply` writes into the working tree, and there is no unapply.** It reads
the original from `src/...` and writes the mutant back onto that same path. Check
`git status` before re-running: a leftover applied mutant makes the next
`mutmut run` generate mutants from already-mutated source. Restore with
`git checkout -- <file>`.

**Mutant indices are positional.** A key like `..._x_supervise__mutmut_3` is a
source-order position, so adding or removing a mutation-skip pragma line shifts
every later index in that function. After any source edit, re-identify a mutant
by its diff (`mutmut show <name>`), not by the number you remembered.

**Read the verdict from `mutants/<path>.meta`.** Its `exit_code_by_key` maps to
`0`=survived, `1`/`3`=killed, `5`/`33`=no tests, `-24`/`24`/`152`/`36`/`255`=
timeout, `-11`/`-9`=segfault, `None`=not checked, else suspicious. A **timeout**
on a supervise/loop test means the code *hung* (an `await` that never
resumes), not that an assertion failed — reproduce with `mutmut apply <name>` +
the focused test before trusting a kill.

**Asyncio loop tests (`supervise`).** The loop is
`asyncio.wait((change_task, child.wait_task, stop_task), return_when=FIRST_COMPLETED)`:

- `return_when` is load-bearing — a mutant that drops it defaults to
  `ALL_COMPLETED` and the loop hangs. If you monkeypatch `asyncio.wait`, accept
  and honor `return_when`.
- `asyncio.wait` returns without blocking if a passed task is already done (it lands in
  `done`); a fake `wait` must return the right `done` set per call, or the
  `if stop_task in done` / `if child.wait_task in done` checks spin or miss.
- The loop exits when `stop_task` or `child.wait_task` completes, so drive one
  of those in the test. A watch generator that yields once then blocks will hang
  the loop — bound the call with `asyncio.wait_for` and `aclose()` the generator.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:46cd31e7 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
