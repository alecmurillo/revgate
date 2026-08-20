"""Drives each scenario against the target and assembles one Result.

Every exchange starts from an empty history. Scenarios must not be able to
contaminate each other, or a failure becomes impossible to attribute and a pass
becomes impossible to trust.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.config import Config
from ..core.findings import Finding, Result, Skipped
from .battery import Battery, Scenario
from .judge import Judgement
from .targets.openai_compat import TargetError

DEFAULT_REMEDY = (
    "Add a guardrail that makes this response impossible rather than unlikely: a tool "
    "call the agent must make, or a refusal it cannot phrase its way around."
)
DEFAULT_ORIGIN = (
    "A customer-facing agent speaks with the company's authority. What it says once, "
    "it will say to everyone who asks the same way."
)


@dataclass
class Exchange:
    scenario: Scenario
    replies: list[str] = field(default_factory=list)
    judgement: Judgement | None = None
    error: str = ""

    @property
    def verdict(self) -> str:
        if self.error:
            return "ERROR"
        if self.judgement is None:
            return "UNJUDGED"
        if self.judgement.failures:
            return "FAIL"
        if self.judgement.unjudged:
            return "PARTIAL"
        return "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario.id,
            "title": self.scenario.title,
            "priority": self.scenario.priority.value,
            "tags": list(self.scenario.tags),
            "verdict": self.verdict,
            "turns": [
                {"customer": q, "agent": a}
                for q, a in zip(self.scenario.turns, self.replies)
            ],
            "failures": list(self.judgement.failures) if self.judgement else [],
            "unjudged": [
                {"assertion": u.description, "reason": u.reason, "blocking": u.blocking}
                for u in (self.judgement.unjudged if self.judgement else [])
            ],
            "error": self.error,
        }


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-") or "scenario"


def run(
    battery: Battery,
    cfg: Config,
    target: Any,
    judge: Any,
    only: list[str] | None = None,
    priority: str | None = None,
    transcripts_dir: str | Path | None = None,
) -> Result:
    scenarios = battery.select(only=only, priority=priority)
    result = Result(surface="agents", target=f"{getattr(target, 'name', 'target')} · {battery.name}")

    exchanges: list[Exchange] = []
    provenance: list[dict[str, Any]] = []

    for scenario in scenarios:
        exchange = Exchange(scenario=scenario)
        history: list[dict[str, str]] = []
        for turn in scenario.turns:
            history.append({"role": "user", "content": turn})
            try:
                reply = target.reply(history)
            except TargetError as exc:
                exchange.error = str(exc)
                break
            except Exception as exc:  # a target is third-party code; do not let it kill the run
                exchange.error = f"{type(exc).__name__}: {exc}"
                break
            reply = reply if isinstance(reply, str) else str(reply)
            history.append({"role": "assistant", "content": reply})
            exchange.replies.append(reply)

        if exchange.error:
            result.skipped.append(Skipped(
                rule=scenario.id,
                reason=f"the target could not be exercised: {exchange.error}",
                blocking=True,
            ))
            exchanges.append(exchange)
            continue

        exchange.judgement = judge.evaluate(scenario, exchange.replies)
        provenance.extend(exchange.judgement.provenance)

        for failure in exchange.judgement.failures:
            result.findings.append(Finding(
                rule=scenario.id,
                severity=scenario.priority,
                title=scenario.title,
                detail=failure,
                remedy=scenario.remedy or DEFAULT_REMEDY,
                origin=scenario.origin or DEFAULT_ORIGIN,
                key=", ".join(scenario.tags),
            ))
        for unjudged in exchange.judgement.unjudged:
            result.skipped.append(Skipped(
                rule=scenario.id,
                reason=f"{unjudged.reason} — assertion: {unjudged.description}",
                blocking=unjudged.blocking,
            ))
        exchanges.append(exchange)

    verdicts = [e.verdict for e in exchanges]
    result.stats = {
        "scenarios": len(exchanges),
        "passed": verdicts.count("PASS"),
        "failed": verdicts.count("FAIL"),
        "partial": verdicts.count("PARTIAL"),
        "errored": verdicts.count("ERROR"),
        "judge": getattr(judge, "kind", "unknown"),
    }
    if provenance:
        result.stats["droid_sessions"] = provenance
        sessions = {p.get("session_id") for p in provenance if p.get("session_id")}
        result.notes.append(
            f"{len(provenance)} assertion(s) judged by droid exec across {len(sessions)} session(s). "
            "Session ids are recorded under .revgate/runs/ for provenance."
        )

    if transcripts_dir:
        directory = Path(transcripts_dir)
        directory.mkdir(parents=True, exist_ok=True)
        for exchange in exchanges:
            path = directory / f"{_slug(exchange.scenario.id)}.json"
            path.write_text(json.dumps(exchange.to_dict(), indent=2) + "\n", encoding="utf-8")
        index = directory / "index.json"
        index.write_text(
            json.dumps(
                {
                    "battery": battery.name,
                    "target": getattr(target, "name", "target"),
                    "judge": getattr(judge, "kind", "unknown"),
                    "exchanges": [e.to_dict() for e in exchanges],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        result.notes.append(f"Transcripts written to {directory}/ for review.")

    return result
