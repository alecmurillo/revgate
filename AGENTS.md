# AGENTS.md

## What this project is

revgate is fail-closed QA for revenue machinery: a linter for outbound lead lists and a red-team harness for customer-facing AI agents. One tool, one severity contract, exit codes you can put in CI.

## The one invariant

**A check that could not run is never a pass.** A gate whose source file is missing records a blocking skip. An unjudged assertion blocks. An empty finding list is never "clean" when it means "did not look." Every change to this codebase must preserve this invariant.

## Architecture

```
revgate/
  core/         findings, severity, CSV loading, reporters, config
  lists/        22 gates (L001–L022) and their runner
  agents/       battery loader, target adapters, judges, scenario runner
  batteries/    27 adversarial scenarios (TOML)
  api/          HTTP gating server, source adapters (Clay/HubSpot/Apollo), writeback
  audit.py      multi-agent audit: 5 phases, parallel droid exec, cross-validation
  provenance.py verifies factory-usage.toml, records run history
  cli.py        lint · redteam · diff · provenance · rules · scenarios · serve · audit
```

## How to run things

```bash
# Tests (no network, no deps)
python3 -m unittest discover -s tests -v

# Demo (asserts every documented exit code)
bash scripts/demo.sh

# Lint a list
python3 -m revgate lint fixtures/leads-dirty.csv --today 2026-08-16 --no-record

# Red-team the demo agent
python3 -m revgate redteam --target demo --no-record

# Verify Factory integration claims
python3 -m revgate provenance
```

## Factory surfaces

This repo uses Factory in 7 places, machine-verified by `revgate provenance`:

1. **2 skills** — list-review triage, agent-redteam grouping
2. **3 custom droids** — list-gate-reviewer, scenario-author, origin-auditor
3. **Hooks** — PostToolUse lints on write, PreToolUse blocks bad commits
4. **`droid exec` as judge** — semantic assertions delegated to the operator's session, no second API key
5. **Multi-agent audit** — parallel `droid exec` sessions with cross-validation synthesis
6. **CI** — gate job (credential-free), droid-review, docker-smoke, droid-audit
7. **This file** — AGENTS.md, loaded by droid on every session

All claims are in `factory-usage.toml` and verified by `revgate provenance`.

## Conventions

- **Zero dependencies.** stdlib only. If you need a third-party package, you're solving the wrong problem.
- **Every gate has an `origin`** naming the specific mistake it prevents. Not a description of the check — the mistake.
- **Every new gate needs a dirty-fixture row** that trips it, and the clean fixture must still exit 0.
- **Every new adversarial scenario needs an expected-pass control.** A battery where everything fails cannot tell a broken guardrail from a broken matcher.
- **Exit codes are the contract:** 0 clean, 1 advisory+strict, 2 blocked, 3 usage error. CI depends on these meaning exactly what the README says.
- **`droid exec` is a runtime, not a dependency.** The tool works without it. Unjudged is never a pass.

## What not to do

- Don't add a dependency.
- Don't add a gate without a dirty-fixture row and an origin.
- Don't change exit code semantics without updating every test and the README.
- Don't silently skip a check. If it can't run, it blocks.
- Don't parse stderr for droid errors — the reason is in the stdout JSON envelope.
