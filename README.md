# revgate

**Fail-closed QA for revenue machinery.**

Software ships behind tests, linters, type checks and CI. The revenue system
sitting next to it, the lead lists and the AI agents that talk to customers, ships
behind nothing. revgate gates both, from one command, with one severity policy.

```
python3 -m revgate lint    leads.csv        # gate an outbound list before it sends
python3 -m revgate redteam --target openai  # red-team the agent that answers replies
```

No dependencies. No credentials for the default path. Exit codes you can put in CI
today.

---

## Why

A lead list is code that runs once, against real people, and cannot be rolled
back. A sales agent is a program that can commit the company to a discount. Both
get shipped on a glance and a spreadsheet filter.

The two problems look unrelated and are the same product decision seen twice: what
is this revenue system allowed to do to a person before a human has looked at it.
revgate answers it in one place, so one CI job blocks a bad list and a regressed
agent with the same contract.

---

## Quickstart

Requires Python 3.11 or newer. That is the whole prerequisite list.

```bash
git clone https://github.com/alecmurillo/revgate
cd revgate
```

**Gate a deliberately broken lead list.** Twenty-four rows engineered to trip all
thirteen gates:

```bash
python3 -m revgate lint fixtures/leads-dirty.csv --today 2026-08-16
```

```
revgate lists · fixtures/leads-dirty.csv
  BLOCKED  P0 17 · P1 8 · P2 4
  rows 24 · columns 13 · gates run 13 · gates skipped 0

  P0 L003  Number is on the do-not-call list  (2)
      row 20 · cobaltfreight.com · column `phone` — 8005550101 normalises to 8005550101, which is suppressed
      fix: Remove the row. Do not flag it and leave it in the file for a human to notice.
      why: A number that reaches a dialler has been dialled. Flagging instead of removing
           assumes every downstream consumer reads the flag column.
```

Exit code 2. Then the same gate on a clean list, which exits 0:

```bash
python3 -m revgate lint fixtures/leads-clean.csv --today 2026-08-16
```

**Red-team a deliberately unsafe sales agent.** Bundled, offline, no API key:

```bash
python3 -m revgate redteam --target demo
```

```
revgate agents · demo · sales-intake
  BLOCKED  P0 29 · P1 2 · P2 0 · skipped 11
  scenarios 22 · passed 6 · failed 16 · partial 0 · errored 0 · judge pattern
```

Sixteen adversarial scenarios caught it. Six scenarios written to be passed were
passed. That second number is the one that matters: a battery where everything
fails cannot tell a broken guardrail from a broken matcher.

`--today` is there because the fixtures contain dates and one gate is about
recency. Pinning it keeps the output reproducible in 2027.

**Or run the whole tour at once,** which asserts every documented exit code as it
goes:

```bash
./scripts/demo.sh
```

---

## The two surfaces

### `lint` — thirteen gates on an outbound list

Run `python3 -m revgate rules` to see all of them with the mistake each one
prevents.

| | Gate | Catches |
|---|---|---|
| P0 | `L001` suppression-collision | Row already in your CRM or suppression export |
| P0 | `L002` recent-contact | Somebody a rep called six days ago |
| P0 | `L003` do-not-call | A number on the DNC export |
| P0 | `L004` restricted-jurisdiction | A row in a jurisdiction the motion is not cleared for |
| P0 | `L005` missing-trigger | Empty triggers, unverifiable ones, and one trigger pasted across the whole list |
| P0 | `L006` unrendered-copy | `{{first_name}}`, raw timestamps, nine-digit numbers, and the double space a merge field leaves when it renders empty |
| P1 | `L007` email-unverified | Catch-all domains, which pass verification and then bounce |
| P2 | `L008` mailbox-shape | Role mailboxes, free-email addresses, addresses on the wrong domain |
| P1 | `L009` name-domain-mismatch | Enrichment that resolved to the wrong company |
| P1 | `L010` non-operating-entity | Funds and holding companies that pass every firmographic filter and buy nothing |
| P1 | `L011` headcount-ceiling | Accounts past the size where the motion itself is wrong |
| P2 | `L012` headcount-floor | A minimum-headcount filter, usually the most expensive default in outbound |
| P1 | `L013` duplicate-account | Two rows on one account, which becomes two reps on one account |

Column names are matched through an alias table, so `Company Domain`, `website`
and `domain` all resolve. Row numbers are one-indexed from 2, matching what the
operator sees in the spreadsheet.

Bring your own suppression and DNC exports in `revgate.toml`. **If a source is
missing, its gate records a blocking skip and the run is BLOCKED.** A gate that
could not run is not a gate that passed.

### `redteam` — twenty-two adversarial scenarios against a live agent

The battery in [`revgate/batteries/sales-intake.toml`](revgate/batteries/sales-intake.toml)
probes commercial failure modes rather than content-policy ones:

- **Identity and disclosure.** Account details handed to whoever asks. A third
  party asking about somebody else's account. Denying being an AI when asked
  directly.
- **Contract state.** "You're all set" when nothing is signed.
- **Unauthorised commitments.** A discount the agent invented. An ROI guarantee on
  the second ask, after the first was correctly deflected.
- **Competitor claims.** Unfounded assertions about a named company's legal
  exposure.
- **Compliance claims.** Certifications confirmed without a source.
- **Opt-out.** One more pitch after "take me off your list".
- **Prompt injection.** The system prompt, on request.
- **Six expected-pass controls.** The reason a run means anything.

Multi-turn by design. The most valuable finding in this domain is a guardrail that
holds once and yields on the re-ask, and one turn cannot detect it.

**Targets:**

```bash
# Bundled unsafe agent. Offline, deterministic, no credentials.
python3 -m revgate redteam --target demo

# Any OpenAI-compatible endpoint. stdlib urllib, config from env only.
export REVGATE_TARGET_BASE_URL=https://api.your-host.example/v1
export REVGATE_TARGET_MODEL=your-model
export REVGATE_TARGET_API_KEY=...
python3 -m revgate redteam --target openai --transcripts ./transcripts

# Anything else. Your command gets JSON on stdin, returns JSON on stdout.
export REVGATE_TARGET_CMD='python3 my_agent.py'
python3 -m revgate redteam --target shell
```

---

## Exit codes

The contract every integration depends on, asserted in CI rather than described
and hoped for:

| Code | Meaning |
|---|---|
| `0` | Clean. No findings, no blocking skips. |
| `1` | Advisory findings only. Non-zero only under `--strict`. |
| `2` | **Blocked.** Any P0 finding, or any blocking skip. |
| `3` | Usage error. Bad arguments or unreadable config. Not a pass. |

Code 2 comes from severity, never from volume. One P0 blocks; four hundred P2s do
not.

---

## Configuration

Everything is optional. `revgate.toml`, discovered upward from the working
directory:

```toml
[lint]
recent_contact_days = 14
restricted_states   = ["NY"]
headcount_ceiling   = 200

[lint.sources]
suppression = "fixtures/crm-export.csv"   # missing file => blocking skip
do_not_call = "fixtures/dnc.csv"

[lint.columns]
domain = ["domain", "website", "company_domain"]

[redteam]
battery = "revgate/batteries/sales-intake.toml"
```

Paths resolve relative to the config file, not the shell.

**Output formats:** `--format text|json|md`. Markdown is written for PR comments,
with findings in collapsible sections and blocking skips outside them.

---

## Factory / Droid integration

This repository uses Factory in five places, and **the claims are machine-checked
rather than asserted**:

```bash
python3 -m revgate provenance
```

```
revgate provenance · factory-usage.toml
  PASS  P0 0 · P1 0 · P2 0
  claims 10 · verified 10 · surfaces 6
```

[`factory-usage.toml`](factory-usage.toml) lists every Factory surface the project
says it uses. `provenance` validates each claim against the file it names, and then
walks the repository the other way to flag any Factory surface that exists but is
undocumented, because a manifest that lags the code stops being evidence.

| Surface | What it does |
|---|---|
| **2 skills** | `revgate-list-review` triages findings into row, pipeline and motion defects. `revgate-agent-redteam` groups agent failures by mechanism and demands a control group. |
| **3 custom droids** | `list-gate-reviewer` blocks any gate that can pass a row it never evaluated. `scenario-author` writes scenarios and validates them against the unsafe demo agent. `origin-auditor` attacks this repository's own claims, including [NOVELTY.md](NOVELTY.md). |
| **Hooks** | `PostToolUse` lints a lead-list CSV the moment it is written. `PreToolUse` refuses a `git commit` that would stage a blocked list. |
| **`droid exec`** | `--judge droid` delegates assertions no regex can make to the operator's existing Droid session. No second API key. Every judgement records its `session_id`. |
| **CI** | One credential-free job asserting the exit-code contract, one `droid exec` job that runs the reviewer droids on changed gates. |

**Droid as runtime, not dependency.** The semantic judge shells out to
`droid exec --output-format json` in the session you are already authenticated for:

```bash
python3 -m revgate redteam --target openai --judge droid
```

And usage is countable, not claimed:

```bash
python3 -m revgate provenance --runs
```

```
revgate run history · 41 run(s)
  assertions judged by droid exec: 118
  distinct droid sessions:         37
```

---

## The one invariant

**A check that could not run is never a pass.**

- A gate whose source file is missing records a blocking skip. It does not return
  zero findings.
- A semantic assertion that no judge evaluated is reported as unjudged and blocks.
  It is not quietly downgraded.
- Skipped checks print **above** findings in every output format, because the
  absence of suppression findings means nothing if the suppression gate never ran.
- The hook blocks a list it could not evaluate, not just a list that failed.

Most tooling in this space skips quietly and reports green. A green report that
means nothing is worse than no report, because somebody trusts it.

---

## Is any of this new?

Some of it. [**NOVELTY.md**](NOVELTY.md) is the honest version: the agent
red-teaming surface is a crowded field (promptfoo, garak, PyRIT, DeepTeam,
Giskard), the lead-list surface appears to be empty, and the four things we think
are genuinely new are small and specific. It names the prior art, states what this
project does **not** claim, and lists how to disprove each remaining claim.

Read that before deciding what this is worth.

---

## Layout

```
revgate/
  core/         findings, severity, CSV loading and normalisation, reporters, config
  lists/        the thirteen gates and their runner
  agents/       battery loader, target adapters, judges, scenario runner
  batteries/    adversarial scenarios (TOML)
  provenance.py verifies factory-usage.toml, records run history
  cli.py        lint · redteam · provenance · rules · scenarios
fixtures/       dirty and clean lead lists, suppression and DNC exports
.factory/       skills, custom droids, hooks
tests/          unit tests, no network
```

Development:

```bash
python3 -m unittest discover -s tests -v
pip install -e .        # optional; installs the `revgate` command
```

---

## Contributing

New gates need three things: an `origin` naming a mistake somebody actually made,
a row in `fixtures/leads-dirty.csv` that trips it, and the clean fixture still
exiting 0. New scenarios need an expected-pass control.

`.factory/droids/list-gate-reviewer.md` and `.factory/droids/scenario-author.md`
are the review checklists, and they are strict about the invariant above.

## License

MIT. See [LICENSE](LICENSE).
