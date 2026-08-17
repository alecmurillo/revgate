# revgate — One Pager

## What it is

A command-line tool that gates two artifacts a revenue system points at real people and nobody tests: the outbound lead list and the AI agent that answers the reply. One tool, one severity contract, exit codes you can put in CI today.

## The problem

A lead list is code that runs once, against real people, and cannot be rolled back. A sales agent is a program that can commit the company to a discount. Both get shipped on a glance and a spreadsheet filter. Software ships behind tests, linters, type checks, and CI. The revenue system sitting next to it ships behind nothing.

## What it does

### `revgate lint` — 22 gates on an outbound lead list

Checks a CSV before it reaches a dialer or sending tool: suppression collisions, do-not-call numbers, restricted jurisdictions, unrendered merge fields, stale enrichment, duplicate phones across accounts, missing recipient names, wrong-seniority titles, and more. Each gate carries the specific mistake it prevents, printed in the report.

### `revgate redteam` — 27 adversarial scenarios against a sales agent

Probes commercial failure modes (not content-policy ones): fabricated discounts, false signature confirmations, competitor defamation, invented refund terms, escalation promises, integration fabrication, data security claims, prompt injection, opt-out violations, customer data exfiltration. 21 adversarial scenarios designed to fail, 6 controls designed to pass — because a battery where everything fails can't tell a broken guardrail from a broken matcher.

### `revgate audit` — multi-agent audit with parallel droid exec sessions

Six-phase workflow: planning, pattern gates, parallel agent review (one `droid exec` per finding group, run concurrently), root cause analysis (one session sees ALL findings and identifies systemic patterns no individual gate can see), cross-validation synthesis (a final session checks the other agents' work), final report. Each phase is a milestone. Fail-closed if droid is unavailable.

### `revgate serve` — HTTP API with Clay/HubSpot/Apollo adapters

POST `/v1/lint` with Clay, HubSpot, Apollo, or generic payloads. Shared-secret auth. Per-row writeback fields. Optional writeback to Clay/HubSpot APIs via stdlib urllib.

### `revgate diff` — compare two exports and re-gate what changed

Match rows by domain, report added/removed/changed accounts, then run every gate on only the new and changed rows. Same exit-code contract.

### `revgate provenance` — verify Factory integration claims

Machine-checks every claim about how the repo uses Factory against the actual files, then walks the repo in reverse to flag undocumented surfaces. Run history counts real `droid exec` sessions.

## The invariant

**A check that could not run is never a pass.** A missing suppression file records a blocking skip, not zero findings. An unjudged assertion blocks. Skips print above findings in every output format. Most tooling in this space skips quietly and reports green — a green report that means nothing is worse than no report, because somebody trusts it.

## How it uses Factory/Droid

- **2 skills**: list-review triage, agent-redteam grouping
- **3 custom droids**: list-gate-reviewer (read-only), scenario-author (edit/create), origin-auditor (read-only, attacks the repo's own claims)
- **Hooks**: PostToolUse lints lead lists on write, PreToolUse blocks commits staging bad lists
- **`droid exec`**: the semantic judge borrows the operator's existing authenticated session — no second API key, no vendor SDK
- **Multi-agent audit**: `revgate audit --judge droid` splits the audit across parallel `droid exec` sessions — one per finding group — with a cross-validation synthesis session that checks the other agents' work
- **CI**: one job asserts exit codes, one `droid exec` job runs reviewer droids on changed gates

All 12 claims in `factory-usage.toml` are machine-verified by `revgate provenance`.

## What's genuinely new (and what isn't)

**Not new**: agent red-teaming (promptfoo, garak, PyRIT, DeepTeam, Giskard all do this, most with more breadth). Data-quality frameworks (Great Expectations, Soda, dbt) exist for column-level contracts.

**Appears to be empty**: an open-source, opinionated, runnable linter for outbound lead lists with a severity policy. No equivalent was found as of August 2026.

**Genuinely new (small, specific)**:
1. One severity contract across a spreadsheet and a conversation
2. Fail-closed skip semantics as a load-bearing invariant
3. Every rule carries the mistake it prevents (enforced by dataclass)
4. Verified provenance — a build step that falsifies its own integration manifest

## Technical specs

- Zero dependencies, zero credentials for the default path
- Python 3.11+, stdlib only
- 245 tests, no network
- Exit codes: 0 clean, 1 advisory+strict, 2 blocked, 3 usage error
- Bundled demo agent runs offline and deterministic
- Shell target for testing any agent that speaks JSON on stdin/stdout
- HTTP API server with Clay/HubSpot/Apollo adapters, shared-secret auth
- Optional writeback adapters (Clay, HubSpot) via stdlib urllib
- Dockerfile included for containerized deployment
- Example configs for cold outbound, warm intro, and ABM motions
- Output: text, JSON, Markdown (for PR comments), HTML (for sharing)

## Current state

Pushed to github.com/alecmurillo/revgate. 245 tests pass. Demo asserts all exit codes. Provenance 12/12 verified. CI green.
