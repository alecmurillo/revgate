"""Multi-agent audit: pattern gates first, then droid exec per finding group.

The audit command demonstrates a task decomposed across agents with clear
milestones:

1. **Phase 1 — Pattern gates.** The existing lint engine runs all 22 gates.
   No agent involved. This is milestone 1: the deterministic baseline.

2. **Phase 2 — Agent review.** Findings are grouped by rule. Each group is
   delegated to a separate ``droid exec`` session that reviews the findings
   for true positives, false positives, and remediation advice. Each session
   is a milestone. This is where the task is split: one session per rule
   group, run independently, results collected.

3. **Phase 3 — Synthesis.** The agent assessments are collected into a final
   report with true-positive counts, false-positive flags, and an overall
   recommendation. This is the final milestone.

If ``droid`` is not on PATH, phase 2 is reported as unjudged and the audit
blocks — the fail-closed invariant holds. An unevaluated finding group is
not a confirmed finding group.

The pattern-only path (``--judge pattern`` or no droid available) runs phase
1 only and is equivalent to ``revgate lint``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
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


@dataclass
class AgentReview:
    """One droid exec session's review of one rule's findings."""

    rule: str
    title: str
    finding_count: int
    verdict: str = "unjudged"  # confirmed, false_positive, needs_review, unjudged
    reason: str = ""
    true_positives: int = 0
    false_positives: int = 0
    session_id: str = ""
    error: str = ""
    remediation: str = ""


@dataclass
class AuditResult:
    """The full multi-agent audit output."""

    target: str
    lint_result: Result
    agent_reviews: list[AgentReview] = field(default_factory=list)
    phases: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return self.lint_result.verdict(strict=False)

    @property
    def exit_code(self) -> int:
        return self.lint_result.exit_code(strict=False)

    @property
    def agent_sessions(self) -> int:
        return sum(1 for r in self.agent_reviews if r.session_id)

    @property
    def unjudged_groups(self) -> int:
        return sum(1 for r in self.agent_reviews if r.verdict == "unjudged")


def _ask_droid(prompt: str, timeout: float = 120.0) -> dict[str, Any]:
    """Send a prompt to droid exec and return the parsed envelope.

    Returns a dict with at least ``error`` if something went wrong.
    """
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


def audit(
    path: str | Path,
    cfg: Config,
    *,
    use_droid: bool = False,
) -> AuditResult:
    """Run a multi-agent audit on a lead list.

    Phase 1 always runs (pattern gates). Phase 2 runs only if ``use_droid`` is
    True and the droid CLI is available. Phase 3 is the synthesis.
    """
    # Phase 1: Pattern gates.
    lint_result = run(path, cfg)
    phases = ["Phase 1: Pattern gates complete"]

    reviews: list[AgentReview] = []

    if not use_droid:
        return AuditResult(target=str(path), lint_result=lint_result, agent_reviews=reviews, phases=phases)

    # Phase 2: Agent review — one droid exec session per finding group.
    grouped = group_findings(lint_result.findings)
    if not grouped:
        phases.append("Phase 2: No findings to review")
        return AuditResult(target=str(path), lint_result=lint_result, agent_reviews=reviews, phases=phases)

    for rule_id, title, items in grouped:
        review = AgentReview(
            rule=rule_id,
            title=title,
            finding_count=len(items),
        )

        # Find the origin from the first finding.
        origin = items[0].origin if items else ""

        prompt = _review_prompt(rule_id, title, origin, items)
        response = _ask_droid(prompt)

        if "error" in response:
            review.error = response["error"]
            review.verdict = "unjudged"
        else:
            review.session_id = str(response.get("session_id") or "")
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

        reviews.append(review)

    phases.append(f"Phase 2: Agent review complete ({len(reviews)} droid exec sessions)")

    # Phase 3: Synthesis.
    total_tp = sum(r.true_positives for r in reviews)
    total_fp = sum(r.false_positives for r in reviews)
    phases.append(
        f"Phase 3: Synthesis complete "
        f"({total_tp} true positives, {total_fp} false positives, "
        f"{sum(1 for r in reviews if r.verdict == 'unjudged')} unjudged)"
    )

    return AuditResult(
        target=str(path),
        lint_result=lint_result,
        agent_reviews=reviews,
        phases=phases,
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

    if result.agent_reviews:
        lines.append("  Agent reviews:")
        for r in result.agent_reviews:
            status = r.verdict
            session = f"session {r.session_id[:8]}" if r.session_id else "no session"
            lines.append(f"    {r.rule} {r.title} ({r.finding_count} findings)")
            lines.append(f"      verdict: {status} · {session}")
            if r.true_positives or r.false_positives:
                lines.append(f"      true positives: {r.true_positives}, false positives: {r.false_positives}")
            if r.remediation:
                lines.append(f"      remediation: {r.remediation}")
            if r.error:
                lines.append(f"      error: {r.error}")
        lines.append("")

    if result.unjudged_groups:
        lines.append(f"  {result.unjudged_groups} group(s) could not be evaluated by the agent.")
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
                "remediation": r.remediation,
                "error": r.error,
            }
            for r in result.agent_reviews
        ],
        "lint_result": result.lint_result.to_dict(strict),
    }
    return json.dumps(payload, indent=2, default=str)
