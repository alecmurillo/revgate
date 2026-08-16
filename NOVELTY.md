# What is actually new here, and what is not

Written August 2026. This document exists because "novel" is the easiest word in
software to use dishonestly, and the easiest claim for a reader to check.

The short version: **one of revgate's two surfaces is a crowded field and the other
appears to be empty.** The parts we think are genuinely new are small, specific, and
listed at the bottom along with instructions for disproving them.

---

## The agent red-teaming surface is not novel

`revgate redteam` runs adversarial conversations against a customer-facing agent
and reports failures. This is a well-populated category, and anyone claiming to
have invented it is not paying attention.

| Prior art | What it is |
|---|---|
| [promptfoo](https://github.com/promptfoo/promptfoo) | The most widely adopted open-source LLM eval and red-teaming framework. Ships OWASP LLM Top 10 presets, NIST AI RMF mappings, MITRE ATLAS coverage. Now part of OpenAI. |
| [garak](https://github.com/NVIDIA/garak) | NVIDIA's LLM vulnerability scanner. Large probe catalogue, plugin architecture. |
| [PyRIT](https://github.com/Azure/PyRIT) | Microsoft's Python Risk Identification Tool for generative AI. Orchestrator/scorer model, multi-turn attack support. |
| [DeepTeam](https://github.com/confident-ai/deepteam) | Red-teaming framework from the DeepEval authors, with a large vulnerability taxonomy. |
| [Giskard](https://github.com/Giskard-AI/giskard) | Open-source testing for ML and LLM applications, including automated vulnerability scans. |
| Lakera, and several commercial vendors | Hosted prompt-injection and jailbreak testing. |

All of these do multi-turn adversarial testing. Several do it with far more
breadth than revgate does. If you want an OWASP-mapped scanner with hundreds of
probes, use promptfoo or garak; this is not an attempt to replace them.

What revgate's battery does differently is narrower rather than better: it is
scoped to **commercial** failure modes in a **revenue** conversation, which is a
specific and under-tested slice. Fabricating a discount, confirming a signature
that does not exist, disparaging a named competitor, continuing to sell after an
opt-out, and confirming certifications the company may not hold are all failures
where the damage is contractual, reputational or statutory rather than a content
policy violation. The scenarios read like impatient prospects, not like
jailbreaks, because the failures worth catching in this domain are the ones a
normal customer triggers by accident.

That is a content contribution and a framing contribution. It is not a new
category, and this repository should not be read as claiming one.

---

## The lead-list surface appears to be empty

`revgate lint` gates an outbound lead list before it is sent. Here the search
turned up nothing that does the job.

**Generic data-quality frameworks** do exist and are excellent:
[Great Expectations](https://github.com/great-expectations/great_expectations),
[Soda](https://github.com/sodadata/soda-core),
[dbt tests](https://docs.getdbt.com/docs/build/data-tests), and
[Pandera](https://github.com/unionai-oss/pandera). Every one of them will happily
assert that a column is non-null, unique, or matches a regex. None of them knows
anything about outbound. They give you the mechanism and no opinion, and the
opinion is the entire product: knowing that a catch-all domain passes verification
and then bounces, that a `{{first_name}}` that renders empty leaves a double space
and a stranded comma, that public filing sources are majority holding companies
that pass every firmographic filter and buy nothing, that a minimum-headcount
filter is usually the most expensive default in the channel.

Writing those twenty-two assertions in Great Expectations is a week of work and
requires already knowing all twenty-two. That knowledge is the artefact here.

**Suppression and DNC scrubbing** exists commercially, for example ActiveProspect's
SuppressionList and the compliance suites bundled into dialler platforms. Those are
hosted, paid, and closed. They also solve one of the twenty-two gates.

**What we could not find**, as of August 2026, is an open-source, opinionated,
runnable linter for outbound lead lists with a severity policy attached. If it
exists, this repository should be smaller and should link to it instead.

---

## The five things we think are genuinely new

Each of these is small. Together they are the reason this is a tool rather than a
checklist in a wiki.

### 1. One severity contract across a spreadsheet and a conversation

The list surface and the agent surface are the same product decision seen twice:
what is this revenue system allowed to do to a person before a human has looked at
it. Both surfaces emit the same `Finding` type, the same P0/P1/P2 policy, and the
same exit codes, so one CI job blocks a bad list and a regressed agent with the
same contract.

Every tool we found treats these as unrelated problems belonging to different
teams. Unifying them is not technically hard. Noticing they are one problem is the
contribution.

### 2. A check that could not run is never a pass

This is the invariant the whole codebase is built to preserve. A gate that cannot
find its suppression export records a **blocking skip**, not an absence of
findings. A semantic assertion that no judge evaluated is reported as unjudged and
blocks. An empty finding list is never allowed to mean "clean" when it actually
means "did not look".

Most evaluation tooling skips quietly. The result is a green report that means
nothing, which is worse than no report, because somebody trusts it. Fail-closed
skip semantics as a load-bearing invariant rather than an afterthought is the
design decision we are most confident is unusual.

### 3. Every rule carries the mistake it prevents

Each gate has a required `origin` field naming the specific failure it exists to
catch, and the report prints it. Not a description of the rule: the mistake.

This is a documentation convention enforced by a dataclass, which sounds trivial.
In practice it is the difference between a linter that survives its first false
positive and one that gets switched off, because the operator can see what the
rule is buying them. It also makes a rule that nobody can justify impossible to
add without noticing.

### 4. Verified provenance instead of asserted integration

`revgate provenance` reads `factory-usage.toml`, where every claim this repository
makes about how it uses Factory is written down, and checks each one against the
file it names: skill frontmatter parses and carries required fields, custom droids
declare a legal tool policy, hooks register real lifecycle events, the CI workflow
really does invoke `droid exec`. Then it walks the repository in the other
direction and flags any Factory surface that exists but is undocumented.

Plus: each `droid exec` judgement records its `session_id`, so
`revgate provenance --runs` counts real sessions rather than trusting a README.

We have not seen a repository ship a build step whose job is to falsify its own
integration claims. It is a small idea and we would like it to be copied.

### 5. Multi-agent audit with parallel sessions and cross-validation

`revgate audit --judge droid` decomposes the audit across multiple `droid exec`
sessions run in parallel — one per finding group — and then runs a synthesis
session that cross-validates the individual assessments. Five phases, five
milestones: planning, pattern gates, parallel review, cross-validation, final
report.

Multi-agent orchestration frameworks exist (LangGraph, CrewAI, AutoGen). They are
libraries you build on. This is a concrete, runnable audit where the decomposition
is driven by the data (one session per rule group), not by a fixed graph. The
synthesis agent's job is to check the other agents' work, not to evaluate findings
directly — a separation that makes the cross-validation more than a vote.

The CI workflow runs this on every push to main, producing a visible artifact with
real session IDs, parallel review counts, and the synthesis verdict. This is the
proof that droids are making this project what it is: the audit literally cannot
run without `droid exec`.

---

## Adjacent claim: the judge borrows the operator's session

Model-graded assertions are old. LLM-as-judge is in promptfoo, DeepEval, Giskard,
and most eval frameworks.

What is unusual is the plumbing. `--judge droid` shells out to `droid exec` in the
Droid session the operator is already authenticated for. There is no vendor SDK,
no provider configuration, and no API key belonging to revgate. Comparable tools
require their own provider credential before they will grade anything.

The consequence is the point: the default path is fully offline and free, and the
model-graded path costs one flag and zero setup. Treating the coding agent as an
available runtime rather than a dependency to be vendored is a pattern we expect to
become normal, and we have not yet seen it used this way.

---

## Claims this project does not make

- Not the first tool to red-team an LLM agent. Not close.
- Not more comprehensive than promptfoo, garak or PyRIT, and not trying to be.
- Not a compliance product. It encodes no legal advice, and jurisdiction rules are
  configuration you supply, not law we shipped.
- Not a replacement for a data-quality framework. If you need column-level
  contracts across a warehouse, use Great Expectations or Soda.
- Not novel in its implementation. It is stdlib Python doing obvious things. The
  contribution is which things and what happens when they cannot run.

---

## How to disprove any of this

Every claim above is falsifiable, and the fastest way to find out is to try:

1. **"The lead-list surface is empty."** Find an open-source outbound lead-list
   linter with a severity policy. One counterexample retires the claim. Open an
   issue and this document changes.
2. **"Fail-closed skips are unusual."** Point at an eval framework where an
   unevaluated assertion blocks by default rather than being skipped.
3. **"Verified provenance is new."** Point at a repository with a build step that
   verifies its own integration manifest in both directions.
4. **"The judge needs no second credential."** Read
   [`revgate/agents/judge.py`](revgate/agents/judge.py). If you find a provider key
   or an SDK import, the claim is false.
5. **"The multi-agent audit is genuinely new."** Find an open-source tool that
   decomposes an audit across parallel agent sessions with a cross-validation
   synthesis step, where the decomposition is driven by the data rather than a
   fixed graph. One counterexample retires the claim.
6. **All of it.** Run `.factory/droids/origin-auditor.md` against this repository.
   Its explicit assignment is to attack this document and report every claim that
   is weaker than it reads, and it is instructed to treat a claim it cannot verify
   as a finding rather than giving it the benefit of the doubt.

If a claim here turns out to be wrong, the correct fix is to narrow the claim, not
to defend it.
