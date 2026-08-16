"""Multi-agent audit: a task decomposed across agents with clear milestones.

The audit is a four-phase multi-agent workflow that demonstrates Factory's
value proposition for large tasks split across agents:

**Phase 0 — Planning.** The pattern gates run first (no agent). Findings are
grouped by rule. A review plan is generated listing what will be evaluated,
how many sessions will run, and what each session will check. This is
milestone 1: the plan is reviewable before any agent runs.

**Phase 1 — Pattern gates.** The existing 22 gates run against the list.
This is the deterministic baseline. No agent involved. Milestone 2.

**Phase 2 — Parallel agent review.** One ``droid exec`` session per finding
group, run **in parallel** using ``concurrent.futures.ThreadPoolExecutor``.
Each session reviews its rule's findings for true positives, false positives,
and remediation advice. Each session is a milestone. The work is decomposed
by rule group, not run sequentially. Milestone 3.

**Phase 3 — Cross-validation synthesis.** A final ``droid exec`` session
reviews all individual assessments for consistency, flags disagreements
between reviewers, and produces an overall recommendation. This is the
synthesis agent — its job is to check the other agents' work, not to
evaluate findings directly. Milestone 4.

**Phase 4 — Final report.** All phases are collected into a structured
report with milestone checkpoints, session IDs, and provenance. Milestone 5.

If ``droid`` is not on PATH, phases 2-3 are reported as unjudged and the
audit blocks — the fail-closed invariant holds. An unevaluated finding
group is not a confirmed finding group.

The pattern-only path (``--judge pattern`` or no droid available) runs
phases 0-1 only and is equivalent to ``revgate lint``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core.config import Config
from .core.findings import Result, Severity, group_findings
from .lists.runner import run

AUDIT_TAG = "revgate-audit"
AUDIT_LOG_GROUP = "revgate"

_VERDICT_RE = re.compile(
    r"\{[^{}]*\"verdict\"\s*:\s*\"(confirmed|false_positive|needs_review)\"[^{}]*\}",
    re.IGNORECASE | re.DOTALL,
)

_SYNTHESIS_VERDICT_RE = re.compile(
    r"\{[^{}]*\"overall\"\s*:\s*\"(blocked|advisory|clean)\"[^{}]*\}",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class ReviewPlan:
    """The plan generated before any agent runs."""

    total_findings: int
    rule_groups: list[dict[str, Any]]  # [{rule, title, count, origin}]
    estimated_sessions: int  # rule groups + 1 synthesis

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_findings": self.total_findings,
            "rule_groups": self.rule_groups,
            "estimated_sessions": self.estimated_sessions,
        }


@dataclass
class AgentReview:
    """One droid exec session's review of one rule's findings."""

    rule: str
    title: str
    finding_count: int
    verdict: str = "unjudged"
    reason: str = ""
    true_positives: int = 0
    false_positives: int = 0
    session_id: str = ""
    error: str = ""
    remediation: str = ""
    duration_ms: int = 0


@dataclass
class SynthesisReview:
    """The cross-validation session's assessment of all individual reviews."""

    session_id: str = ""
    overall: str = "unjudged"  # blocked, advisory, clean, unjudged
    disagreements: list[str] = field(default_factory=list)
    recommendation: str = ""
    error: str = ""
    duration_ms: int = 0


@dataclass
class Milestone:
    """One checkpoint in the multi-agent workflow."""

    phase: str
    status: str  # complete, skipped, unjudged
    detail: str
    sessions: int = 0
    findings_checked: int = 0


@dataclass
class AuditResult:
    """The full multi-agent audit output."""

    target: str
    lint_result: Result
    plan: ReviewPlan | None = None
    agent_reviews: list[AgentReview] = field(default_factory=list)
    synthesis: SynthesisReview | None = None
    phases: list[str] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return self.lint_result.verdict(strict=False)

    @property
    def exit_code(self) -> int:
        return self.lint_result.exit_code(strict=False)

    @property
    def agent_sessions(self) -> int:
        count = sum(1 for r in self.agent_reviews if r.session_id)
        if self.synthesis and self.synthesis.session_id:
            count += 1
        return count

    @property
    def unjudged_groups(self) -> int:
        return sum(1 for r in self.agent_reviews if r.verdict == "unjudged")


def _ask_droid(prompt: str, timeout: float = 120.0) -> dict[str, Any]:
    """Send a prompt to droid exec and return the parsed envelope."""
    binary = shutil.which("droid")
    if not binary:
        return {"error": "droid CLI is not on PATH"}

    tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    try:
        tmp.write(prompt)
        tmp.close()
        argv = [
            binary, "exec",
            "-f", tmp.name,
            "--output-format", "json",
            "--tag", AUDIT_TAG,
            "--log-group-id", AUDIT_LOG_GROUP,
        ]
        env = dict(os.environ)
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout,
                check=False, env=env,
            )
        except subprocess.TimeoutExpired:
            return {"error": f"timed out after {timeout}s"}

        if proc.returncode != 0:
            return {"error": f"droid exec exited {proc.returncode}: {(proc.stderr or '').strip()[:200]}"}

        try:
            envelope = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return {"error": "droid exec did not return JSON"}

        if envelope.get("is_error"):
            return {"error": str(envelope.get("result", ""))[:200]}

        return {
            "session_id": envelope.get("session_id"),
            "duration_ms": envelope.get("duration_ms"),
            "num_turns": envelope.get("num_turns"),
            "result": str(envelope.get("result") or ""),
        }
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except OSError:
            pass


def _review_prompt(rule_id: str, title: str, origin: str, findings: list) -> str:
    """Construct the prompt for one droid exec review session."""
    lines = [
        "You are reviewing findings from an automated lead-list linter.",
        "Each finding was produced by a deterministic gate. Your job is to assess",
        "whether the findings are true positives, false positives, or need human review.",
        "",
        "Reply with ONLY a single JSON object and nothing else:",
        '{"verdict": "confirmed" | "false_positive" | "needs_review", '
        '"true_positives": <int>, "false_positives": <int>, '
        '"remediation": "<= 200 chars>"}',
        "",
        f"GATE: {rule_id} — {title}",
        f"WHY THIS GATE EXISTS: {origin}",
        "",
        f"FINDINGS ({len(findings)} total, showing first 5):",
    ]
    for f in findings[:5]:
        lines.append(f"  - {f.detail}")
        if f.key:
            lines.append(f"    key: {f.key}")
    if len(findings) > 5:
        lines.append(f"  ... {len(findings) - 5} more")
    return "\n".join(lines)


def _synthesis_prompt(reviews: list[AgentReview]) -> str:
    """Construct the prompt for the cross-validation synthesis session."""
    lines = [
        "You are the synthesis reviewer for a multi-agent audit of a lead list.",
        "Multiple agent sessions have reviewed individual finding groups. Your job",
        "is to cross-validate their assessments, flag disagreements, and produce",
        "an overall recommendation.",
        "",
        "Reply with ONLY a single JSON object and nothing else:",
        '{"overall": "blocked" | "advisory" | "clean", '
        '"disagreements": ["<rule_id>: <description>", ...], '
        '"recommendation": "<= 300 chars>"}',
        "",
        f"INDIVIDUAL REVIEWS ({len(reviews)} total):",
    ]
    for r in reviews:
        lines.append(
            f"  {r.rule} ({r.title}): verdict={r.verdict}, "
            f"true_positives={r.true_positives}, false_positives={r.false_positives}"
        )
        if r.remediation:
            lines.append(f"    remediation: {r.remediation}")
        if r.error:
            lines.append(f"    error: {r.error}")
    return "\n".join(lines)


def _review_one_group(
    rule_id: str,
    title: str,
    origin: str,
    findings: list,
) -> AgentReview:
    """Run one droid exec session for one finding group. Thread-safe."""
    review = AgentReview(
        rule=rule_id,
        title=title,
        finding_count=len(findings),
    )
    prompt = _review_prompt(rule_id, title, origin, findings)
    response = _ask_droid(prompt)

    if "error" in response:
        review.error = response["error"]
        review.verdict = "unjudged"
    else:
        review.session_id = str(response.get("session_id") or "")
        review.duration_ms = int(response.get("duration_ms") or 0)
        text = response.get("result", "")
        match = _VERDICT_RE.search(text)
        if match:
            try:
                parsed = json.loads(match.group(0))
                review.verdict = str(parsed.get("verdict", "")).lower()
                review.true_positives = int(parsed.get("true_positives", 0))
                review.false_positives = int(parsed.get("false_positives", 0))
                review.remediation = str(parsed.get("remediation", "")).strip()
                review.reason = f"Reviewed in session {review.session_id}"
            except (json.JSONDecodeError, ValueError):
                review.error = "verdict object was not valid JSON"
                review.verdict = "unjudged"
        else:
            review.error = "no verdict object in the agent's reply"
            review.verdict = "unjudged"
    return review


def audit(
    path: str | Path,
    cfg: Config,
    *,
    use_droid: bool = False,
    max_workers: int = 4,
) -> AuditResult:
    """Run a multi-agent audit on a lead list.

    Phases 0-1 always run. Phases 2-3 run only if ``use_droid`` is True and
    the droid CLI is available. Phase 4 is the final report assembly.
    """
    phases: list[str] = []
    milestones: list[Milestone] = []

    # Run pattern gates first to collect the data the plan needs.
    lint_result = run(path, cfg)
    grouped = group_findings(lint_result.findings)
    counts = lint_result.counts()

    # Phase 0: Planning (generated from the gate results).
    plan = ReviewPlan(
        total_findings=sum(counts.values()),
        rule_groups=[
            {"rule": rid, "title": title, "count": len(items), "origin": items[0].origin if items else ""}
            for rid, title, items in grouped
        ],
        estimated_sessions=len(grouped) + 1,  # +1 for synthesis
    )
    phases.append(f"Phase 0: Review plan generated ({plan.estimated_sessions} sessions planned)")
    milestones.append(Milestone(
        phase="planning",
        status="complete",
        detail=f"{plan.total_findings} findings, {len(grouped)} rule groups, {plan.estimated_sessions} sessions",
    ))

    # Phase 1: Pattern gates (the deterministic baseline).
    phases.append("Phase 1: Pattern gates complete")
    milestones.append(Milestone(
        phase="pattern-gates",
        status="complete",
        detail=f"{len(grouped)} finding groups across {sum(counts.values())} findings",
        findings_checked=sum(counts.values()),
    ))

    reviews: list[AgentReview] = []

    if not use_droid or not grouped:
        if not grouped and use_droid:
            phases.append("Phase 2: No findings to review")
        elif not use_droid:
            phases.append("Phase 2: Skipped (pattern-only mode)")
        return AuditResult(
            target=str(path),
            lint_result=lint_result,
            plan=plan,
            agent_reviews=reviews,
            phases=phases,
            milestones=milestones,
        )

    # Phase 2: Parallel agent review.
    # Run one droid exec session per finding group IN PARALLEL.
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_group = {
            executor.submit(
                _review_one_group,
                rule_id, title,
                items[0].origin if items else "",
                items,
            ): (rule_id, title)
            for rule_id, title, items in grouped
        }
        for future in as_completed(future_to_group):
            review = future.result()
            reviews.append(review)

    # Sort reviews by rule ID for stable output.
    reviews.sort(key=lambda r: r.rule)

    sessions_run = sum(1 for r in reviews if r.session_id)
    phases.append(
        f"Phase 2: Parallel review complete "
        f"({sessions_run}/{len(grouped)} sessions completed in parallel)"
    )
    milestones.append(Milestone(
        phase="parallel-review",
        status="complete" if sessions_run == len(grouped) else "partial",
        detail=f"{sessions_run} sessions ran in parallel, "
               f"{sum(1 for r in reviews if r.verdict == 'unjudged')} unjudged",
        sessions=sessions_run,
        findings_checked=sum(r.finding_count for r in reviews),
    ))

    # Phase 3: Cross-validation synthesis.
    synthesis = SynthesisReview()
    if any(r.session_id for r in reviews):
        syn_prompt = _synthesis_prompt(reviews)
        syn_response = _ask_droid(syn_prompt)

        if "error" in syn_response:
            synthesis.error = syn_response["error"]
        else:
            synthesis.session_id = str(syn_response.get("session_id") or "")
            synthesis.duration_ms = int(syn_response.get("duration_ms") or 0)
            text = syn_response.get("result", "")
            match = _SYNTHESIS_VERDICT_RE.search(text)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    synthesis.overall = str(parsed.get("overall", "")).lower()
                    synthesis.disagreements = list(parsed.get("disagreements", []))
                    synthesis.recommendation = str(parsed.get("recommendation", "")).strip()
                except (json.JSONDecodeError, ValueError):
                    synthesis.error = "synthesis verdict was not valid JSON"
            else:
                synthesis.error = "no verdict object in synthesis reply"
    else:
        synthesis.error = "no individual reviews to synthesize"

    phases.append(
        f"Phase 3: Cross-validation complete "
        f"(overall: {synthesis.overall}"
        + (f", {len(synthesis.disagreements)} disagreements" if synthesis.disagreements else ""
        + ")")
    )
    milestones.append(Milestone(
        phase="cross-validation",
        status="complete" if synthesis.session_id else "unjudged",
        detail=f"overall={synthesis.overall}"
               + (f", {len(synthesis.disagreements)} disagreements" if synthesis.disagreements else ""),
        sessions=1 if synthesis.session_id else 0,
    ))

    # Phase 4: Final report.
    phases.append("Phase 4: Final report assembled")
    milestones.append(Milestone(
        phase="final-report",
        status="complete",
        detail=f"{len(reviews)} reviews, {sum(r.true_positives for r in reviews)} TP, "
               f"{sum(r.false_positives for r in reviews)} FP, "
               f"{sum(1 for r in reviews if r.verdict == 'unjudged')} unjudged",
    ))

    return AuditResult(
        target=str(path),
        lint_result=lint_result,
        plan=plan,
        agent_reviews=reviews,
        synthesis=synthesis,
        phases=phases,
        milestones=milestones,
    )


def render_audit_text(result: AuditResult, strict: bool = False) -> str:
    """Render the audit result as text."""
    counts = result.lint_result.counts()
    lines: list[str] = []
    lines.append("")
    lines.append(f"revgate audit · {result.target}")
    lines.append(f"  {result.verdict}  P0 {counts['P0']} · P1 {counts['P1']} · P2 {counts['P2']}")

    for phase in result.phases:
        lines.append(f"  {phase}")
    lines.append("")

    if result.milestones:
        lines.append("  Milestones:")
        for m in result.milestones:
            lines.append(f"    [{m.status}] {m.phase}: {m.detail}")
        lines.append("")

    if result.plan:
        lines.append(f"  Plan: {result.plan.total_findings} findings, "
                     f"{len(result.plan.rule_groups)} rule groups, "
                     f"{result.plan.estimated_sessions} sessions")
        lines.append("")

    if result.agent_reviews:
        lines.append("  Agent reviews (parallel):")
        for r in result.agent_reviews:
            session = f"session {r.session_id[:8]}" if r.session_id else "no session"
            lines.append(f"    {r.rule} {r.title} ({r.finding_count} findings)")
            lines.append(f"      verdict: {r.verdict} · {session}")
            if r.true_positives or r.false_positives:
                lines.append(f"      true positives: {r.true_positives}, false positives: {r.false_positives}")
            if r.remediation:
                lines.append(f"      remediation: {r.remediation}")
            if r.error:
                lines.append(f"      error: {r.error}")
        lines.append("")

    if result.synthesis:
        lines.append("  Cross-validation synthesis:")
        syn = result.synthesis
        session = f"session {syn.session_id[:8]}" if syn.session_id else "no session"
        lines.append(f"    overall: {syn.overall} · {session}")
        if syn.disagreements:
            lines.append(f"    disagreements:")
            for d in syn.disagreements:
                lines.append(f"      - {d}")
        if syn.recommendation:
            lines.append(f"    recommendation: {syn.recommendation}")
        if syn.error:
            lines.append(f"    error: {syn.error}")
        lines.append("")

    if result.unjudged_groups:
        lines.append(f"  {result.unjudged_groups} group(s) could not be evaluated by the agents.")
        lines.append("  Unjudged findings are not confirmed. The audit blocks.")
        lines.append("")

    return "\n".join(lines)


def render_audit_json(result: AuditResult, strict: bool = False) -> str:
    """Render the audit result as JSON."""
    payload = {
        "target": result.target,
        "verdict": result.verdict,
        "exit_code": result.exit_code,
        "counts": result.lint_result.counts(),
        "phases": result.phases,
        "milestones": [
            {"phase": m.phase, "status": m.status, "detail": m.detail,
             "sessions": m.sessions, "findings_checked": m.findings_checked}
            for m in result.milestones
        ],
        "plan": result.plan.to_dict() if result.plan else None,
        "agent_sessions": result.agent_sessions,
        "unjudged_groups": result.unjudged_groups,
        "agent_reviews": [
            {
                "rule": r.rule,
                "title": r.title,
                "finding_count": r.finding_count,
                "verdict": r.verdict,
                "true_positives": r.true_positives,
                "false_positives": r.false_positives,
                "session_id": r.session_id,
                "duration_ms": r.duration_ms,
                "remediation": r.remediation,
                "error": r.error,
            }
            for r in result.agent_reviews
        ],
        "synthesis": {
            "session_id": result.synthesis.session_id if result.synthesis else "",
            "overall": result.synthesis.overall if result.synthesis else "unjudged",
            "disagreements": result.synthesis.disagreements if result.synthesis else [],
            "recommendation": result.synthesis.recommendation if result.synthesis else "",
            "error": result.synthesis.error if result.synthesis else "",
        }
        if result.synthesis else None,
        "lint_result": result.lint_result.to_dict(strict),
    }
    return json.dumps(payload, indent=2, default=str)
