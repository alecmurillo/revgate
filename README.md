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

**Gate a deliberately broken lead list.** Twenty-eight rows engineered to trip all
twenty-two gates:

```bash
python3 -m revgate lint fixtures/leads-dirty.csv --today 2026-08-16
```

```
revgate lists · fixtures/leads-dirty.csv
  BLOCKED  P0 17 · P1 10 · P2 6
  rows 28 · columns 14 · gates run 17 · gates skipped 0

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
  BLOCKED  P0 34 · P1 4 · P2 0 · skipped 15
  scenarios 26 · passed 6 · failed 20 · partial 0 · errored 0 · judge pattern
```

Twenty adversarial scenarios caught it. Six scenarios written to be passed were
passed. That second number is the one that matters: a battery where everything
fails cannot tell a broken guardrail from a broken matcher.

`--today` is there because the fixtures contain dates and one gate is about
recency. Pinning it keeps the output reproducible in 2027.

**Or run the whole tour at once,** which asserts every documented exit code as it
goes:

```bash
./scripts/demo.sh
```

**Start the HTTP gating API** and send it a Clay row from another terminal:

```bash
# Start the HTTP gating API
python3 -m revgate serve --port 8000

# In another terminal, send a Clay row
curl -s localhost:8000/v1/lint -H 'Content-Type: application/json' \
  -d '{"source":"clay","rows":[{"Company Name":"Acme","Domain":"acme.com","Email":"ops@acme.com","Trigger":"opened new DC","Copy":"Saw the new DC"}]}'

# Multi-agent audit
python3 -m revgate audit fixtures/leads-dirty.csv --judge pattern
```

---

## The two surfaces

### `lint` — twenty-two gates on an outbound list

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
| P1 | `L014` duplicate-phone | Same phone number on multiple accounts — a shared main number from bad enrichment |
| P1 | `L015` stale-enrichment | Data verified months ago; a clean list at build time is not clean at send time |
| P2 | `L016` missing-recipient | No name on the row; the personalisation sends to "Hi there" |
| P2 | `L017` title-scope | Title indicates the wrong seniority for the motion (intern, assistant) |

## How to read this report

Each gate exists because somebody shipped a list without checking and it cost
money. The `origin` field on every finding is the mistake, not a description of
the check. Here is what each gate is based on and why it matters.

### P0 — blocks the send

**L001 suppression-collision.** You're about to spend enrichment credits and rep
time on accounts you already know about. Worse, two reps end up on the same
account because nobody checked the suppression list first. The prospect gets two
emails from your company and loses trust in both.

**L002 recent-contact.** A rep called this person 6 days ago. The CRM's deal stage
doesn't reflect that because the call didn't move the deal. A second rep reaches
out. The prospect hears from your company twice in a week and assumes you don't
talk to each other.

**L003 do-not-call.** This number is on your DNC export. If it reaches a dialer,
that's a $50,120 statutory violation per call. Flagging it instead of removing it
assumes every downstream tool reads the flag column — most don't. The row needs
to be gone, not annotated.

**L004 restricted-jurisdiction.** These accounts are in a state your motion isn't
cleared for. State telemarketing laws vary wildly: Connecticut is $20,000 per
violation, Georgia has no damage cap, Texas requires a $10,000 bond. The
enrichment vendor's UI doesn't show jurisdiction restrictions, so this constraint
is invisible while you're building the list. You supply the restricted states in
`revgate.toml` because the restrictions depend on your specific motion.

**L005 missing-trigger.** A trigger column where every row says "series a
announced" is a segment label, not a trigger. When your email tool merges it into
the copy, every email says the same thing. The recipient reads "Saw your Series A
was announced..." and immediately knows they're part of a blast. A trigger should
be specific enough that two rows in the same list rarely share it. "Growing fast"
is true of every company a rep has ever called and predicts nothing.

**L006 unrendered-copy.** `{{first_name}}` survived the render and will send
literally. A machine-formatted date like `2026-05-19` reached the copy instead of
"May." A merge field that rendered empty left a stranded period. All of these
signal broken tooling, not personalization. The prospect reads it and knows the
email was assembled, not written.

**L018 dnc-source-staleness.** Federal law requires scrubbing against the National
DNC Registry every 31 days. A DNC file that is 60 days old is a historical
document, not a compliance tool. Numbers added to the DNC list since your last
scrub are numbers you'll call illegally. The gate checks the modification time of
your DNC source file.

**L019 calling-hours.** TCPA restricts calling hours to 8am-9pm local time.
Connecticut requires 9am-8pm with $20,000 per violation. A send scheduled outside
these hours is a statutory violation regardless of intent — the regulator doesn't
care that your scheduling tool didn't check.

### P1 — should fix before sending

**L007 email-unverified.** The verification tool said "verified" because the
domain accepts any address. But catch-all domains accept at the SMTP level and
bounce at delivery. Enough bounces and your sending domain gets suspended.

**L009 name-domain-mismatch.** The company name says "Northgate Labs" but the
domain is "acme-industries.com." Enrichment matched the wrong company. If you
write a first line about Northgate Labs and send it to acme-industries.com, the
prospect knows you're confused about who they are. Every word in the email is
now suspect.

**L010 non-operating-entity.** "Ridgeline Capital Partners" is a fund. "1420
Chestnut Street LLC" is an address wearing a corporate suffix. They pass every
firmographic filter — they have a website, a headcount, a state. But they don't
buy software. Public filing sources are full of these, and they inflate your list
size without adding any reachable buyers.

**L011 headcount-ceiling.** The issue isn't that big companies are bad targets.
It's that your motion — the cold email, the messaging, the pricing, the sales
process — is built for a specific size range. At 4,200 employees, the buying
process goes through procurement, security, and legal. Your SMB pitch sounds
naive. Your pricing is wrong. Your single-threaded email can't navigate a
10-stakeholder decision. The motion itself is wrong, and the exclusion should be
deliberate, not emergent.

**L013 duplicate-account.** Two rows on one account become two reps on one
account. The prospect gets two emails from the same company, often with different
messaging. Both reps look like they don't know what their colleague is doing.

**L014 duplicate-phone.** The same phone number on two accounts is almost always a
shared switchboard that enrichment mapped to every contact. The dialer calls the
receptionist twice, the rep never reaches either decision-maker, and nobody knows
why the calls aren't connecting.

**L015 stale-enrichment.** This data was verified 9 months ago. Phone numbers get
reassigned. Emails change. People leave. If the number was reassigned to someone
on the DNC list, calling it is a $50K violation. Stale data is both a quality
problem and a compliance problem.

**L021 links-in-first-email.** Links in first-touch cold emails trigger spam
filters and lower deliverability. The email is more likely to land in spam than in
the inbox. Introduce links in follow-up 2 or 3, after the prospect has engaged.

### P2 — worth reviewing

**L008 mailbox-shape.** A role mailbox (info@, sales@) has no owner, so a reply
sits in a queue nobody checks. A free email (gmail.com) on a B2B list usually
means the enrichment guessed. An email on the wrong domain means the join was
wrong upstream.

**L012 headcount-floor.** The smallest company on the list has 6 employees and
nothing below survived. A minimum-headcount filter is the most expensive default
in outbound — the smallest companies are often both the largest share of your
addressable market and the best close rate, because they decide fast and have
fewer stakeholders. You filtered them out without realizing it.

**L016 missing-recipient.** Both first and last name are empty. The email will
say "Hi there" or "To whom it may concern." That's the same as sending nothing —
it costs the same and gets the same reply rate.

**L017 title-scope.** The title is "Marketing Intern." An intern can't sign a
contract, can't route one, and can't approve budget. Sending a sales pitch to an
intern wastes the send and trains them to ignore your company.

**L020 email-length.** 175 words. Cold emails over 150 words convert worse. The
prospect decides whether to read in under 3 seconds — a wall of text gets
skipped. The first touch should be under 100 words. The goal is a reply, not a
pitch.

**L022 multiple-ctas.** "Are you free for a call? Let's chat. Let me know if
you're open to a quick look." Three asks in one email. Multiple CTAs dilute the
ask and increase cognitive load — the prospect has to decide which question to
answer, so they answer none. One email, one ask.

Column names are matched through an alias table, so `Company Domain`, `website`
and `domain` all resolve. Row numbers are one-indexed from 2, matching what the
operator sees in the spreadsheet.

Bring your own suppression and DNC exports in `revgate.toml`. **If a source is
missing, its gate records a blocking skip and the run is BLOCKED.** A gate that
could not run is not a gate that passed.

### `redteam` — twenty-six adversarial scenarios against a live agent

The battery in [`revgate/batteries/sales-intake.toml`](revgate/batteries/sales-intake.toml)
probes commercial failure modes rather than content-policy ones:

- **Identity and disclosure.** Account details handed to whoever asks. A third
  party asking about somebody else's account. Denying being an AI when asked
  directly.
- **Contract state.** "You're all set" when nothing is signed.
- **Unauthorised commitments.** A discount the agent invented. An ROI guarantee on
  the second ask, after the first was correctly deflected. An escalation promise
  about what a supervisor will do.
- **Competitor claims.** Unfounded assertions about a named company's legal
  exposure.
- **Compliance and security claims.** Certifications confirmed without a source.
  Encryption standards fabricated on the spot. Integration compatibility asserted
  without checking.
- **Refund terms.** Specific refund terms invented under pressure after the safe
  answer was given.
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

**Output formats:** `--format text|json|md|html`. Markdown is written for PR comments,
with findings in collapsible sections and blocking skips outside them. HTML is a
self-contained dark-theme report for sharing with non-technical stakeholders.

### `diff` — compare two exports and re-gate what changed

```bash
python3 -m revgate diff old-leads.csv new-leads.csv --today 2026-08-16
```

Matches rows by domain (or `--key email`), reports accounts added, removed, and
changed, then runs every gate on the new and changed rows only. Same exit-code
contract: 2 if any new or changed row is blocked, 0 if clean.

---

## HTTP gating API — Clay, HubSpot, Apollo

`POST /v1/lint` accepts JSON from any source, runs the same twenty-two gates, and
returns a versioned JSON response. The server is stdlib-only (zero dependencies)
and started with `python3 -m revgate serve --port 8000`.

Auth is a shared secret in the `X-Revgate-Key` header, set with `--key` or
`$REVGATE_API_KEY`. **Fail-closed at the API level:** a malformed payload, an
unknown source, or an adapter failure all return BLOCKED, never PASS. The
invariant that a check which could not run is never a pass extends to the wire.

The response carries per-row writeback fields designed to map straight back into
the source tool's columns:

- `revgate_status` — `PASS` or `BLOCKED`
- `revgate_severity` — highest severity that fired (`P0`, `P1`, `P2`, or empty)
- `revgate_rules` — list of rule codes that fired (e.g. `["L003", "L006"]`)
- `revgate_summary` — one-line human summary of the findings
- `revgate_checked_at` — ISO-8601 timestamp of the check

HTTP status branches without parsing the body: **200 for PASS, 422 for BLOCKED.**

Quickstart:

```bash
# Start the server
python3 -m revgate serve --port 8000

# Send a Clay-style row
curl -s localhost:8000/v1/lint \
  -H 'Content-Type: application/json' \
  -d '{"source":"clay","rows":[{"Company Name":"Acme","Domain":"acme.com","Email":"ops@acme.com","Trigger":"opened new DC","Copy":"Saw the new DC"}]}'
```

Adapters, one per source, normalise the inbound shape into the row the gates
expect:

| Source | Payload format | What the adapter does |
|---|---|---|
| `clay` | `{"rows": [{...}]}` or flat object | Passes Clay row fields through the alias table |
| `hubspot` | `{"contact": {"properties": {...}}, "company": {"properties": {...}}}` | Flattens contact + company properties (handles both `{value: "..."}` and flat formats) |
| `apollo` | `{"prospect": {"email": "...", "organization": {...}}}` | Flattens prospect + organization fields |
| `generic` | `{"rows": [{...}]}` | Passes fields directly through the alias table |

The Clay workflow, in under sixty seconds:

1. Start `revgate serve`.
2. In Clay, add a webhook column that sends row data to `http://your-host:8000/v1/lint`.
3. Map the response fields (`revgate_status`, `revgate_severity`, `revgate_rules`,
   `revgate_summary`, `revgate_checked_at`) to Clay columns.
4. Filter: only rows where `revgate_status == PASS` proceed to outbound.

Fixtures for each adapter live in `fixtures/api/`. `revgate serve` must be
reachable from the internet — use ngrok for local testing and a TLS proxy for
production.

---

## Multi-agent audit

`revgate audit leads.csv --judge droid` runs a five-phase multi-agent workflow
that demonstrates a task decomposed across agents with clear milestones:

- **Phase 0 — Planning.** Pattern gates run first (no agent). Findings are
  grouped by rule. A review plan is generated listing what will be evaluated,
  how many sessions will run, and what each session will check. Milestone 1.
- **Phase 1 — Pattern gates.** The existing twenty-two gates produce the
  deterministic baseline. Same findings `lint` produces. Milestone 2.
- **Phase 2 — Parallel agent review.** One `droid exec` session per finding
  group, run **in parallel** using `ThreadPoolExecutor`. Each session reviews
  its rule's findings for true positives, false positives, and remediation
  advice. The work is decomposed by rule group, not run sequentially. Milestone 3.
- **Phase 3 — Cross-validation synthesis.** A final `droid exec` session
  reviews all individual assessments for consistency, flags disagreements
  between reviewers, and produces an overall recommendation. This agent's job
  is to check the other agents' work. Milestone 4.
- **Phase 4 — Final report.** All phases are collected into a structured
  report with milestone checkpoints, session IDs, and provenance. Milestone 5.

If `droid` is not available, phases 2-3 report as unjudged and the audit blocks
— fail-closed, the same invariant as everywhere else. An unevaluated finding
group is not a confirmed finding group.

`--judge pattern` (the default) runs phases 0-1 only and is equivalent to `lint`:

```bash
python3 -m revgate audit fixtures/leads-dirty.csv --judge pattern
```

With droid, the full multi-agent audit runs in parallel:

```bash
python3 -m revgate audit fixtures/leads-dirty.csv --judge droid --max-workers 4
```

`--max-workers` controls how many `droid exec` sessions run concurrently (default 4).

---

## Factory / Droid integration

This repository uses Factory in six places, and **the claims are machine-checked
rather than asserted**:

```bash
python3 -m revgate provenance
```

```
revgate provenance · factory-usage.toml
  PASS  P0 0 · P1 0 · P2 0
  claims 11 · verified 11 · surfaces 6
```

[`factory-usage.toml`](factory-usage.toml) lists every Factory surface the project
says it uses (11 claims). `provenance` validates each claim against the file it names, and then
walks the repository the other way to flag any Factory surface that exists but is
undocumented, because a manifest that lags the code stops being evidence.

| Surface | What it does |
|---|---|
| **2 skills** | `revgate-list-review` triages findings into row, pipeline and motion defects. `revgate-agent-redteam` groups agent failures by mechanism and demands a control group. |
| **3 custom droids** | `list-gate-reviewer` blocks any gate that can pass a row it never evaluated. `scenario-author` writes scenarios and validates them against the unsafe demo agent. `origin-auditor` attacks this repository's own claims, including [NOVELTY.md](NOVELTY.md). |
| **Hooks** | `PostToolUse` lints a lead-list CSV the moment it is written. `PreToolUse` refuses a `git commit` that would stage a blocked list. |
| **`droid exec`** | `--judge droid` delegates assertions no regex can make to the operator's existing Droid session. No second API key. Every judgement records its `session_id`. |
| **Multi-agent audit** | `revgate audit --judge droid` splits the audit across multiple `droid exec` sessions — one per finding group, run **in parallel** — with a cross-validation synthesis session that checks the other agents' work. Five phases, five milestones: planning, pattern gates, parallel review, cross-validation, final report. |
| **CI** | Four jobs: `gate` (credential-free exit-code contract), `droid-review` (reviewer droids on changed gates), `docker-smoke` (container builds and serves), `droid-audit` (parallel multi-agent audit on push to main). |

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

Two notes on the newer surfaces:

- The HTTP gating API with per-source adapters is a standard integration pattern.
  What's unusual is that the fail-closed invariant extends to the API level: a
  malformed payload returns BLOCKED, not PASS.
- The multi-agent audit is a standard orchestration pattern. What's unusual is
  that unjudged findings block — the agent review is not decorative.

Read that before deciding what this is worth.

---

## Configuring for your motion

The default `revgate.toml` is tuned for cold outbound. Different motions need
different gate thresholds. Example configs live in `examples/`:

| Config | Motion | What changes |
|---|---|---|
| [`cold-outbound.toml`](examples/cold-outbound.toml) | Cold email/calling | Aggressive compliance (restricted states, DNC staleness 31d), tight title filtering |
| [`warm-intro.toml`](examples/warm-intro.toml) | Referral / warm intro | No restricted states, relaxed staleness (90d/180d), higher headcount ceiling |
| [`abm-enterprise.toml`](examples/abm-enterprise.toml) | Account-based marketing | Strict mode, fresh enrichment (30d), tight title filtering, short emails |

```bash
python3 -m revgate lint -c examples/cold-outbound.toml leads.csv
python3 -m revgate lint -c examples/warm-intro.toml leads.csv
python3 -m revgate lint -c examples/abm-enterprise.toml leads.csv
```

---

## Production deployment

The API server is stdlib-only and runs as a single process. For production:

**Docker** (simplest path):

```bash
docker build -t revgate .
docker run -p 8000:8000 -e REVGATE_API_KEY=your-secret revgate
```

The Dockerfile installs the package and runs `revgate serve --port 8000`. Mount
your `revgate.toml` to override defaults:

```bash
docker run -p 8000:8000 -e REVGATE_API_KEY=your-secret \
  -v $(pwd)/revgate.toml:/app/revgate.toml revgate
```

**Behind a reverse proxy** (recommended for TLS and rate limiting):

```
nginx/Traffic Manager → revgate serve (port 8000)
```

The server is stateless — each request is evaluated independently. Run
multiple containers behind a load balancer for higher concurrency.

**Writeback** (optional): After evaluating rows, you can POST verdicts back to
Clay or HubSpot so downstream teams see the quality flags in their workflow tool.
Writeback adapters use stdlib `urllib` (no extra dependencies) and require API
keys:

```python
from revgate.api.writeback import writeback_clay, writeback_hubspot

# Clay: needs CLAY_SOURCE_ID (the Clay source to update)
results = writeback_clay(api_key="sk-...", rows=evaluated_rows, source_id="src_123")

# HubSpot: external_id is the HubSpot contact ID
results = writeback_hubspot(api_key="pat-...", rows=evaluated_rows)
```

Both are fail-closed: if a writeback call fails, the error is returned, never
silently swallowed.

**Shell target** (for testing your own agent): The `shell` target lets you
red-team any agent that can speak JSON on stdin/stdout, in any language. An
example agent with intentional bugs lives in `examples/test_agent.py`:

```bash
REVGATE_TARGET_CMD="python3 examples/test_agent.py" \
  python3 -m revgate redteam --target shell
```

---

## Layout

```
revgate/
  core/         findings, severity, CSV loading and normalisation, reporters, config
  lists/        the twenty-two gates and their runner
  agents/       battery loader, target adapters, judges, scenario runner
  batteries/    adversarial scenarios (TOML)
  api/          HTTP gating server, source adapters (Clay/HubSpot/Apollo), writeback
  provenance.py verifies factory-usage.toml, records run history
  audit.py      multi-agent audit: 5 phases, parallel droid exec, cross-validation
  cli.py        lint · redteam · diff · provenance · rules · scenarios · serve · audit
fixtures/       dirty and clean lead lists, suppression and DNC exports, API fixtures
examples/       test agent script, example configs for different motions
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
