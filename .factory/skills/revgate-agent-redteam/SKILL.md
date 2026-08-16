---
name: revgate-agent-redteam
description: Red-team a customer-facing AI sales or support agent for disclosure failures, false confirmations, unauthorised commitments, competitor defamation, opt-out violations and prompt injection. Use when the user has an agent, chatbot or voice bot that talks to prospects or customers, or wants to add adversarial scenarios to an existing revgate battery.
---

# Red-teaming a revenue-facing agent

A sales agent that fabricates a discount has committed the company to it. This
skill runs an adversarial battery against a conversational target and turns the
transcript into specific guardrail changes.

## 1. Prove the harness works before pointing it at anything real

```bash
python3 -m revgate redteam --target demo
```

The `demo` target is a deliberately unsafe agent bundled with the repo. It runs
offline with no credentials and no network. It should come back BLOCKED with
twenty-one failures and six passes.

That result matters more than it looks. The six passes are scenarios written to
be passed, and they are the control group: a battery where everything fails is
indistinguishable from a battery with a broken matcher. If the demo run does not
produce both failures and passes, the harness is wrong, not the agent.

## 2. Point it at the real target

```bash
export REVGATE_TARGET_BASE_URL=https://api.your-host.example/v1
export REVGATE_TARGET_MODEL=your-model
export REVGATE_TARGET_API_KEY=...            # never hard-code this
python3 -m revgate redteam --target openai --transcripts ./transcripts
```

For an agent that is not an OpenAI-compatible endpoint, use the shell adapter:

```bash
export REVGATE_TARGET_CMD='python3 my_agent.py'   # JSON on stdin, JSON on stdout
python3 -m revgate redteam --target shell
```

Always pass `--transcripts`. The verdict tells you that the agent failed; the
transcript is the only thing that tells a guardrail author what to change.

## 3. Turn on the semantic judge for the assertions patterns cannot make

Some failures are not lexical. "Did the agent imply a guarantee without using
the word guarantee" is a judgement, and scenarios that need one carry a
`semantic` assertion.

```bash
python3 -m revgate redteam --target openai --judge droid
```

This delegates those assertions to `droid exec` in the operator's existing
session, so it needs no second API key. Every judgement records its
`session_id`, which `revgate provenance --runs` can later count.

With the default pattern judge, semantic assertions are reported as **blocking
skips**, not as passes. A scenario whose central assertion could not be
evaluated is unresolved. Never summarise one as clean.

## 4. Read failures as guardrail bugs, not as bad outputs

Each scenario's `origin` explains the failure mode it probes. Group your findings
by mechanism, because the fix is per mechanism:

- **Stateless checks that are not stateless.** `ID3` and `OG1` re-ask after a
  refusal. An agent that holds once and yields on the third ask has a guardrail
  in the prompt instead of in the control flow. The fix is to run the check on
  every turn, not to strengthen the wording.
- **Claims generated rather than retrieved.** Certifications, contract status and
  pricing must come from a source. If the agent can generate them, it will
  eventually generate a wrong one. The fix is a tool call, or a refusal.
- **Persuasion that outranks instruction.** Selling after an opt-out, or
  inventing a discount to save a deal, means the objective is beating the
  constraint. The fix belongs outside the model.
- **Disclosure that depends on phrasing.** If `AI1` fails and `GR1` passes, the
  disclosure is being generated instead of hard-coded.

## 5. Add scenarios where the battery was silent

Batteries in `revgate/batteries/*.toml`. A new scenario needs an `id`, a
`priority`, `turns`, at least one assertion, and an `origin` naming the real
failure it came from.

Two rules when authoring:

- Multi-turn beats single-turn. Nearly every interesting failure needs the setup
  turn to establish context and the second turn to apply pressure.
- Add a matching expected-pass scenario for any new failure mode. Without one you
  cannot tell a guardrail that works from an assertion that never matches.

Validate before running:

```bash
python3 -m revgate scenarios
```

Duplicate ids, assertion-free scenarios and invalid regexes are rejected at load
rather than being skipped quietly at run time.
