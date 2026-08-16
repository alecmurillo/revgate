"""Findings, severities, and the fail-closed exit-code policy.

Two invariants govern this module, and they are the reason the project exists:

1. A check that could not run is never a pass. It is recorded as skipped and
   surfaced in every renderer. A gate that reads an empty suppression file looks
   identical, from the outside, to a gate that found nothing wrong.
2. Severity decides the exit code, never the count. One P0 blocks the run; a
   thousand P2s do not.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

EXIT_OK = 0
EXIT_ADVISORY = 1
EXIT_BLOCKED = 2
EXIT_USAGE = 3


class Severity(enum.Enum):
    """Run priority. P0 is "this must not ship", not "this is important"."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"

    @property
    def blocking(self) -> bool:
        return self is Severity.P0

    @classmethod
    def parse(cls, raw: str) -> "Severity":
        try:
            return cls(str(raw).strip().upper())
        except ValueError as exc:
            valid = ", ".join(s.value for s in cls)
            raise ValueError(f"unknown severity {raw!r}; expected one of {valid}") from exc

    def __lt__(self, other: "Severity") -> bool:
        order = [Severity.P0, Severity.P1, Severity.P2]
        return order.index(self) < order.index(other)


@dataclass(frozen=True)
class Finding:
    """One concrete problem, tied to the mistake that motivated the check.

    `origin` is not decoration. A gate whose rationale nobody remembers is a gate
    somebody deletes the first time it is inconvenient.
    """

    rule: str
    severity: Severity
    title: str
    detail: str
    remedy: str
    origin: str
    row: int | None = None
    key: str = ""
    column: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "title": self.title,
            "detail": self.detail,
            "remedy": self.remedy,
            "origin": self.origin,
            "row": self.row,
            "key": self.key,
            "column": self.column,
        }


@dataclass(frozen=True)
class Skipped:
    """A check that did not run, and whether that fact should block.

    The distinction carries the whole lesson:

    - `blocking=False` -- the data has no such column, so there is nothing to
      check. Reported, not fatal.
    - `blocking=True` -- the check was configured and still could not run: the
      suppression export is missing, the do-not-call list is empty, the judge is
      unavailable. The gate was supposed to hold and did not, which is worse than
      never having had it, because the run *looks* checked.
    """

    rule: str
    reason: str
    blocking: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "reason": self.reason, "blocking": self.blocking}


@dataclass
class Result:
    """Everything one surface produced in one run."""

    surface: str
    target: str
    findings: list[Finding] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in Severity}
        for f in self.findings:
            out[f.severity.value] += 1
        return out

    @property
    def blocking_skips(self) -> list[Skipped]:
        return [s for s in self.skipped if s.blocking]

    def exit_code(self, strict: bool = False) -> int:
        if any(f.severity.blocking for f in self.findings) or self.blocking_skips:
            return EXIT_BLOCKED
        if strict and any(f.severity is Severity.P1 for f in self.findings):
            return EXIT_ADVISORY
        return EXIT_OK

    def verdict(self, strict: bool = False) -> str:
        code = self.exit_code(strict)
        if code == EXIT_BLOCKED:
            return "BLOCKED"
        if code == EXIT_ADVISORY:
            return "ADVISORY"
        return "PASS"

    def to_dict(self, strict: bool = False) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "target": self.target,
            "verdict": self.verdict(strict),
            "exit_code": self.exit_code(strict),
            "counts": self.counts(),
            "stats": self.stats,
            "findings": [f.to_dict() for f in self.findings],
            "skipped": [s.to_dict() for s in self.skipped],
            "notes": list(self.notes),
        }


def group_findings(findings: list[Finding]) -> list[tuple[str, str, list[Finding]]]:
    """Group by rule *and* title.

    Grouping on the rule alone hides distinctions that matter: one gate can report
    an unrendered placeholder, a raw timestamp and a collapsed merge field, and
    collapsing those under the first title read makes two of the three invisible.
    """
    grouped: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        grouped.setdefault((f.rule, f.title), []).append(f)
    ordered = sorted(
        grouped.items(),
        key=lambda kv: (list(Severity).index(kv[1][0].severity), kv[0][0], kv[0][1]),
    )
    return [(rule, title, items) for (rule, title), items in ordered]
