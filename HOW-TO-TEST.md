# How to test revgate

A practical guide for someone who cloned the repo and wants to see it work.
No prior knowledge of the codebase required.

---

## When to use revgate

revgate is a QA layer between data generation and outbound execution. It catches
mistakes that cost money or create legal exposure before they reach a prospect.

**Use it when you are about to send a lead list or ship an AI agent that talks to
customers.** Specifically:

- **Before a cold outbound send.** You built a list in Clay, Apollo, or a CSV
  export. Run `revgate lint` to catch suppression collisions, DNC hits, restricted
  jurisdictions, unrendered merge fields, stale enrichment, and other mistakes
  that either bounce, land in spam, or create compliance exposure. One P0 finding
  blocks the send; the exit code goes straight into CI or a pre-send gate.

- **Before an ABM push.** You have a tight account list and want to verify every
  row is the right company, the right size, and has fresh data. Use `revgate lint`
  with a config tuned for enterprise (strict title filtering, tight headcount
  range, fresh enrichment).

- **When you diff two exports.** You refreshed a list and want to know what
  changed and whether the new rows pass. `revgate diff` matches old against new by
  domain, reports added/removed/changed, and re-gates only the rows that moved.

- **Before shipping an AI sales agent.** You built an agent that answers replies,
  handles inbound, or qualifies leads. Run `revgate redteam` to throw 27
  adversarial scenarios at it — identity disclosure, unauthorized discounts,
  fabricated compliance claims, prompt injection, opt-out violations — and see
  which guardrails hold and which yield.

- **When you want a multi-agent audit, not just a lint.** `revgate audit --judge
  droid` decomposes the findings across parallel droid sessions, each reviewing a
  rule group, then a root cause analysis session that sees patterns no individual
  gate can see, then a synthesis session that cross-validates everything. This is
  the step that pattern matching provably cannot do.

- **As a CI gate.** Wire `revgate lint` into your pipeline so a bad list never
  ships. The exit codes are the contract: 0 = clean, 2 = blocked. The bundled
  pre-commit hook does the same thing at commit time.

- **As an HTTP API for Clay/HubSpot/Apollo.** Run `revgate serve` and wire a
  webhook column in Clay that sends each row to revgate before it reaches
  outbound. The response carries writeback fields (`revgate_status`,
  `revgate_severity`, `revgate_rules`) that map straight back into your tool's
  columns. Filter on `revgate_status == PASS` and only clean rows proceed.

**When NOT to use it:**

- As a CRM or enrichment tool. It doesn't source data; it gates data you already
  have.
- As a sending platform. It doesn't send emails or make calls; it stops bad sends
  from happening.
- As legal advice. The compliance gates (DNC, calling hours, jurisdiction) are
  operational safeguards based on common practice. Verify current requirements
  with counsel.

---

**Prerequisites:** Python 3.11+ and a terminal. That's it for everything
except the droid-powered features.

```bash
git clone https://github.com/alecmurillo/revgate
cd revgate
```

---

## 1. Lint a lead list (30 seconds)

The core command. Runs 22 gates against a CSV and exits with a contract
code: 0 = clean, 2 = blocked, 3 = usage error.

```bash
# Dirty fixture — 28 rows engineered to trip every gate
python3 -m revgate lint fixtures/leads-dirty.csv --today 2026-08-16
echo "exit: $?"   # should be 2 (BLOCKED)

# Clean fixture — 20 rows that pass every gate
python3 -m revgate lint fixtures/leads-clean.csv --today 2026-08-16
echo "exit: $?"   # should be 0 (PASS)
```

`--today` pins the reference date because three gates depend on it (recent
contact, stale enrichment, DNC staleness). Without it, the results drift as
the calendar moves.

**Try your own CSV.** Any CSV with columns like `company`, `domain`, `email`,
`phone`, `state`, `trigger`, `copy` will work. Column names are matched through
an alias table, so `Company Domain`, `website`, and `domain` all resolve.

```bash
python3 -m revgate lint your-leads.csv --today 2026-08-17
```

**What to look for:**
- P0 findings block the run (exit 2). These must be fixed before sending.
- P1 findings are advisory unless you pass `--strict`.
- P2 findings are worth reviewing but never block.
- Skipped gates appear in the report with the reason. A gate that could not
  run is never a pass — if it's a P0 gate, the run blocks.

---

## 2. Red-team an AI agent (30 seconds)

Runs 27 adversarial scenarios against a customer-facing agent. The bundled
demo agent is deliberately unsafe — it says yes to everything.

```bash
python3 -m revgate redteam --target demo
echo "exit: $?"   # should be 2 (BLOCKED — the demo agent is unsafe)
```

**What to look for:**
- 21 adversarial scenarios should FAIL (the agent gets caught).
- 6 control scenarios should PASS (these are written to be safe).
- If the controls fail, the battery itself is broken, not the agent.

To test a real agent (OpenAI-compatible API):

```bash
export REVGATE_TARGET_BASE_URL=https://api.your-host.example/v1
export REVGATE_TARGET_MODEL=your-model
export REVGATE_TARGET_API_KEY=your-key
python3 -m revgate redteam --target openai
```

---

## 3. The HTML report (10 seconds)

Same lint run, but produce a shareable dark-theme HTML report:

```bash
python3 -m revgate lint fixtures/leads-dirty.csv --today 2026-08-16 \
  --format html --out report.html
open report.html
```

The report includes a plain-English summary, severity counts, per-gate
findings with fix/why, and a "What to do next" section.

---

## 4. The HTTP API (1 minute)

Start the server, then send it a Clay-style row from another terminal:

```bash
# Terminal 1 — start the server
python3 -m revgate serve --port 8000

# Terminal 2 — send a row (no auth needed on localhost)
curl -s localhost:8000/v1/lint \
  -H 'Content-Type: application/json' \
  -d '{"source":"clay","rows":[{"Company Name":"Acme","Domain":"acme.com","Email":"ops@acme.com","Trigger":"opened new DC","Copy":"Saw the new DC"}]}'
```

**What to look for:**
- The response includes `revgate_status`, `revgate_severity`,
  `revgate_rules`, `revgate_summary`, and `revgate_checked_at` fields.
- HTTP status 200 = PASS/ADVISORY, 422 = BLOCKED.
- A row missing a column a P0 gate needs (like `phone`) returns BLOCKED,
  not PASS.

Try sending a row without a `Phone` field to see the fail-closed behavior:

```bash
curl -s localhost:8000/v1/lint \
  -H 'Content-Type: application/json' \
  -d '{"source":"clay","rows":[{"Company Name":"Acme","Domain":"acme.com"}]}' | python3 -m json.tool
```

---

## 5. Diff two lists (30 seconds)

Compare an old export against a new one and re-gate only the rows that
changed:

```bash
python3 -m revgate diff fixtures/leads-clean.csv fixtures/leads-dirty.csv \
  --today 2026-08-16
echo "exit: $?"   # should be 2 (the dirty list has P0 findings)
```

---

## 6. List gates and scenarios (10 seconds)

See all 22 gates with the mistake each one prevents:

```bash
python3 -m revgate rules
```

See all 27 adversarial scenarios:

```bash
python3 -m revgate scenarios
```

---

## 7. Provenance — verify Factory claims (10 seconds)

Verifies that every Factory surface the README claims is actually present and
well-formed in the repo:

```bash
python3 -m revgate provenance
echo "exit: $?"   # should be 0 (all claims verified)
```

---

## 8. The demo script (1 minute)

Runs the full tour — lint, redteam, diff, provenance — and asserts every
exit code as it goes. This is the fastest end-to-end check:

```bash
./scripts/demo.sh
echo "exit: $?"   # should be 0
```

---

## 9. Multi-agent audit with droid (requires Factory account)

This is the flagship feature: a six-phase multi-agent workflow that
decomposes the audit across parallel `droid exec` sessions, each reviewing
a rule group, then a root cause analysis session, then a synthesis session
that cross-validates everything.

**Prerequisite:** A Factory account and the Droid CLI installed.

```bash
# Install the Droid CLI
curl -fsSL https://app.factory.ai/cli | sh

# Authenticate (opens browser)
droid auth

# Run the full multi-agent audit
python3 -m revgate audit fixtures/leads-dirty.csv --judge droid --max-workers 4
```

**What to look for:**
- Phase 0: Planning (no agent, just grouping findings)
- Phase 1: Pattern gates (the 22 deterministic gates)
- Phase 2: Parallel agent review (one droid session per rule group)
- Phase 2.5: Root cause analysis (one droid session sees all findings)
- Phase 3: Cross-validation synthesis (one droid session checks the others)
- Phase 4: Final report with milestones, session IDs, and root causes

Without droid, the pattern-only audit still works:

```bash
python3 -m revgate audit fixtures/leads-dirty.csv --judge pattern
```

---

## 10. Run the test suite (10 seconds)

268 tests covering every gate, every adapter, every exit code, and every
pipe behavior:

```bash
python3 -m unittest discover -s tests
```

---

## 11. Try your own list

Create a CSV with these columns (all optional, but more is better):

```
company,domain,email,phone,first_name,last_name,title,state,headcount,
last_contacted,enriched_date,email_status,trigger,copy,send_time
```

Run it:

```bash
python3 -m revgate lint my-list.csv --today 2026-08-17
```

If you get blocking skips for gates like L001 (suppression) or L003 (DNC),
that's the fail-closed invariant: a gate that can't run is not a gate that
passed. Either configure the sources in `revgate.toml` or acknowledge
them:

```toml
[lint]
acknowledge_unconfigured = ["L001", "L003", "L018"]
```

---

## What does NOT require a Factory account

Everything in sections 1-8 and 10-11 works with just Python. No credentials,
no API keys, no network. The droid-powered features (section 9 and
`redteam --judge droid`) need a Factory account.

## Quick reference

| Command | What it does | Needs Factory? |
|---|---|---|
| `lint` | Gate a lead list | No |
| `redteam --target demo` | Red-team the bundled unsafe agent | No |
| `redteam --target openai` | Red-team a real agent | No (needs OpenAI key) |
| `redteam --judge droid` | Grade semantic assertions with droid | Yes |
| `diff` | Compare two lists and re-gate changes | No |
| `serve` | HTTP gating API for Clay/HubSpot/Apollo | No |
| `audit --judge pattern` | Pattern-only audit (phases 0-1) | No |
| `audit --judge droid` | Full multi-agent audit (phases 0-4) | Yes |
| `rules` | List all gates | No |
| `scenarios` | List all adversarial scenarios | No |
| `provenance` | Verify Factory surface claims | No |
| `demo.sh` | End-to-end tour with exit code assertions | No |
