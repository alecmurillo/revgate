"""Renderers: terminal, Markdown, and JSON.

Every renderer shows the same three things in the same order, because the order is
the argument: what blocks, what could not be checked, what is advisory. Skipped
checks are never relegated to a footnote.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from .findings import Finding, Result, Severity, group_findings

_COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "cyan": "\033[36m",
}

_SEVERITY_COLOR = {Severity.P0: "red", Severity.P1: "yellow", Severity.P2: "cyan"}


def _use_color(stream: Any) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("REVGATE_FORCE_COLOR"):
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def _paint(text: str, color: str, enabled: bool) -> str:
    if not enabled or color not in _COLORS:
        return text
    return f"{_COLORS[color]}{text}{_COLORS['reset']}"


def _row_ref(f: Finding) -> str:
    bits = []
    if f.row is not None:
        bits.append(f"row {f.row}")
    if f.key:
        bits.append(f.key)
    if f.column:
        bits.append(f"column `{f.column}`")
    return " · ".join(bits)


def render_text(result: Result, strict: bool = False, stream: Any = None) -> str:
    stream = stream or sys.stdout
    color = _use_color(stream)
    counts = result.counts()
    lines: list[str] = []

    verdict = result.verdict(strict)
    verdict_color = {"BLOCKED": "red", "ADVISORY": "yellow", "PASS": "green"}[verdict]
    lines.append("")
    lines.append(
        f"{_paint('revgate', 'bold', color)} {result.surface} · {result.target}"
    )
    lines.append(
        f"  {_paint(verdict, verdict_color, color)}  "
        f"P0 {counts['P0']} · P1 {counts['P1']} · P2 {counts['P2']}"
        + (f" · skipped {len(result.skipped)}" if result.skipped else "")
    )

    if result.stats:
        summary = " · ".join(f"{k} {v}" for k, v in result.stats.items() if not isinstance(v, (list, dict)))
        if summary:
            lines.append(f"  {_paint(summary, 'dim', color)}")
    lines.append("")

    blocking_skips = result.blocking_skips
    if blocking_skips:
        lines.append(_paint("  checks that were configured and did not run", "bold", color))
        for s in blocking_skips:
            lines.append(f"    {_paint('!', 'red', color)} {s.rule}: {s.reason}")
        lines.append("")

    for rule_id, title, items in group_findings(result.findings):
        head = items[0]
        sev = _paint(head.severity.value, _SEVERITY_COLOR[head.severity], color)
        lines.append(f"  {sev} {_paint(rule_id, 'bold', color)}  {title}  ({len(items)})")
        for f in items[:8]:
            ref = _row_ref(f)
            prefix = f"      {ref} — " if ref else "      "
            lines.append(f"{prefix}{f.detail}")
        if len(items) > 8:
            lines.append(_paint(f"      … {len(items) - 8} more", "dim", color))
        lines.append(_paint(f"      fix: {head.remedy}", "dim", color))
        lines.append(_paint(f"      why: {head.origin}", "dim", color))
        lines.append("")

    advisory_skips = [s for s in result.skipped if not s.blocking]
    if advisory_skips:
        lines.append(_paint("  not checked (no such field in this file)", "dim", color))
        for s in advisory_skips:
            lines.append(_paint(f"    - {s.rule}: {s.reason}", "dim", color))
        lines.append("")

    for note in result.notes:
        lines.append(_paint(f"  note: {note}", "dim", color))
    if result.notes:
        lines.append("")

    return "\n".join(lines)


def render_markdown(result: Result, strict: bool = False) -> str:
    counts = result.counts()
    verdict = result.verdict(strict)
    icon = {"BLOCKED": "🛑", "ADVISORY": "⚠️", "PASS": "✅"}[verdict]

    out: list[str] = []
    out.append(f"## {icon} revgate — {verdict}")
    out.append("")
    out.append(f"`{result.surface}` · `{result.target}`")
    out.append("")
    out.append("| P0 | P1 | P2 | skipped |")
    out.append("|---:|---:|---:|--------:|")
    out.append(f"| {counts['P0']} | {counts['P1']} | {counts['P2']} | {len(result.skipped)} |")
    out.append("")

    if result.stats:
        scalar = {k: v for k, v in result.stats.items() if not isinstance(v, (list, dict))}
        if scalar:
            out.append(" · ".join(f"**{k}** {v}" for k, v in scalar.items()))
            out.append("")

    blocking = result.blocking_skips
    if blocking:
        out.append("### Checks that were configured and did not run")
        out.append("")
        out.append("These block. A gate that cannot run is not a gate that passed.")
        out.append("")
        for s in blocking:
            out.append(f"- **{s.rule}** — {s.reason}")
        out.append("")

    grouped = group_findings(result.findings)
    if grouped:
        out.append("### Findings")
        out.append("")
        for rule_id, title, items in grouped:
            head = items[0]
            out.append(f"<details><summary><b>{head.severity.value} {rule_id}</b> — {title} ({len(items)})</summary>")
            out.append("")
            out.append(f"**Fix:** {head.remedy}")
            out.append("")
            out.append(f"**Why this gate exists:** {head.origin}")
            out.append("")
            for f in items[:25]:
                ref = _row_ref(f)
                out.append(f"- {ref + ' — ' if ref else ''}{f.detail}")
            if len(items) > 25:
                out.append(f"- … {len(items) - 25} more")
            out.append("")
            out.append("</details>")
            out.append("")

    advisory = [s for s in result.skipped if not s.blocking]
    if advisory:
        out.append("### Not checked")
        out.append("")
        for s in advisory:
            out.append(f"- {s.rule} — {s.reason}")
        out.append("")

    for note in result.notes:
        out.append(f"> {note}")
    if result.notes:
        out.append("")

    return "\n".join(out)


def render_json(result: Result, strict: bool = False) -> str:
    return json.dumps(result.to_dict(strict), indent=2)


RENDERERS = {"text": render_text, "md": render_markdown, "json": render_json}


def render(result: Result, fmt: str, strict: bool = False) -> str:
    if fmt not in RENDERERS:
        valid = ", ".join(sorted(RENDERERS))
        raise ValueError(f"unknown format {fmt!r}; expected one of {valid}")
    if fmt == "text":
        return render_text(result, strict)
    return RENDERERS[fmt](result, strict)
