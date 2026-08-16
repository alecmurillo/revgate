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


def render_html(result: Result, strict: bool = False) -> str:
    counts = result.counts()
    verdict = result.verdict(strict)
    verdict_class = {"BLOCKED": "blocked", "ADVISORY": "advisory", "PASS": "pass"}[verdict]

    import html as html_mod

    def esc(text: str) -> str:
        return html_mod.escape(str(text))

    parts: list[str] = []
    parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>revgate report</title>
<style>
  :root { --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9;
  --dim: #8b949e; --p0: #f85149; --p1: #d29922; --p2: #58a6ff; --green: #3fb950; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system,
  BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; line-height: 1.6;
  padding: 2rem 1rem; max-width: 900px; margin: 0 auto; }
  h1 { font-size: 1.5rem; font-weight: 600; margin-bottom: .25rem; }
  .target { color: var(--dim); font-size: .9rem; margin-bottom: 1.5rem; }
  .verdict { display: inline-block; padding: .35rem .8rem; border-radius: 6px;
  font-weight: 600; font-size: .85rem; margin-bottom: 1rem; }
  .verdict.blocked { background: rgba(248,81,73,.15); color: var(--p0); border: 1px solid var(--p0); }
  .verdict.advisory { background: rgba(210,153,34,.15); color: var(--p1); border: 1px solid var(--p1); }
  .verdict.pass { background: rgba(63,185,80,.15); color: var(--green); border: 1px solid var(--green); }
  .counts { display: flex; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
  .count { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: .75rem 1.25rem; text-align: center; min-width: 80px; }
  .count .n { font-size: 1.5rem; font-weight: 700; }
  .count .l { font-size: .75rem; color: var(--dim); text-transform: uppercase; }
  .count.p0 .n { color: var(--p0); }
  .count.p1 .n { color: var(--p1); }
  .count.p2 .n { color: var(--p2); }
  .stats { color: var(--dim); font-size: .85rem; margin-bottom: 1.5rem; }
  .stats span { margin-right: 1rem; }
  h2 { font-size: 1rem; font-weight: 600; margin: 1.5rem 0 .75rem; color: var(--dim);
  text-transform: uppercase; letter-spacing: .05em; }
  .skip { background: var(--card); border: 1px solid var(--p0); border-radius: 8px;
  padding: .75rem 1rem; margin-bottom: .5rem; }
  .skip .rule { font-weight: 600; color: var(--p0); }
  .finding { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 1rem; margin-bottom: .75rem; }
  .finding .head { display: flex; align-items: center; gap: .5rem; margin-bottom: .5rem; }
  .finding .sev { font-weight: 700; font-size: .8rem; padding: .15rem .4rem; border-radius: 4px; }
  .finding .sev.P0 { color: var(--p0); background: rgba(248,81,73,.1); }
  .finding .sev.P1 { color: var(--p1); background: rgba(210,153,34,.1); }
  .finding .sev.P2 { color: var(--p2); background: rgba(88,166,255,.1); }
  .finding .rid { font-weight: 600; }
  .finding .title { color: var(--text); }
  .finding .count { color: var(--dim); font-size: .85rem; }
  .finding .detail { font-size: .9rem; margin-bottom: .5rem; }
  .finding .ref { color: var(--dim); font-size: .85rem; }
  .finding .fix, .finding .why { font-size: .85rem; color: var(--dim); margin-top: .25rem; }
  .finding .fix strong, .finding .why strong { color: var(--text); }
  .advisory-skip { color: var(--dim); font-size: .85rem; padding: .25rem 0; }
  .note { color: var(--dim); font-size: .85rem; padding: .15rem 0; }
  .more { color: var(--dim); font-size: .85rem; }
</style>
</head>
<body>
""")

    parts.append(f"<h1>revgate {esc(result.surface)}</h1>")
    parts.append(f"<div class=\"target\">{esc(result.target)}</div>")
    parts.append(f"<div class=\"verdict {verdict_class}\">{esc(verdict)}</div>")

    parts.append('<div class="counts">')
    for sev, cls in [("P0", "p0"), ("P1", "p1"), ("P2", "p2")]:
        parts.append(f'<div class="count {cls}"><div class="n">{counts[sev]}</div><div class="l">{sev}</div></div>')
    if result.skipped:
        parts.append(f'<div class="count"><div class="n">{len(result.skipped)}</div><div class="l">skipped</div></div>')
    parts.append('</div>')

    if result.stats:
        scalar = {k: v for k, v in result.stats.items() if not isinstance(v, (list, dict))}
        if scalar:
            parts.append('<div class="stats">')
            for k, v in scalar.items():
                parts.append(f'<span>{esc(k)} {esc(v)}</span>')
            parts.append('</div>')

    blocking = result.blocking_skips
    if blocking:
        parts.append('<h2>Checks that were configured and did not run</h2>')
        for s in blocking:
            parts.append(f'<div class="skip"><span class="rule">{esc(s.rule)}</span> — {esc(s.reason)}</div>')

    grouped = group_findings(result.findings)
    if grouped:
        parts.append('<h2>Findings</h2>')
        for rule_id, title, items in grouped:
            head = items[0]
            parts.append('<div class="finding">')
            parts.append('<div class="head">')
            parts.append(f'<span class="sev {head.severity.value}">{head.severity.value}</span>')
            parts.append(f'<span class="rid">{esc(rule_id)}</span>')
            parts.append(f'<span class="title">{esc(title)}</span>')
            parts.append(f'<span class="count">({len(items)})</span>')
            parts.append('</div>')
            for f in items[:10]:
                ref = _row_ref(f)
                parts.append(f'<div class="detail">{esc(f.detail)}</div>')
                if ref:
                    parts.append(f'<div class="ref">{esc(ref)}</div>')
            if len(items) > 10:
                parts.append(f'<div class="more">… {len(items) - 10} more</div>')
            parts.append(f'<div class="fix"><strong>Fix:</strong> {esc(head.remedy)}</div>')
            parts.append(f'<div class="why"><strong>Why:</strong> {esc(head.origin)}</div>')
            parts.append('</div>')

    advisory = [s for s in result.skipped if not s.blocking]
    if advisory:
        parts.append('<h2>Not checked</h2>')
        for s in advisory:
            parts.append(f'<div class="advisory-skip">{esc(s.rule)} — {esc(s.reason)}</div>')

    if result.notes:
        parts.append('<h2>Notes</h2>')
        for note in result.notes:
            parts.append(f'<div class="note">{esc(note)}</div>')

    parts.append('</body></html>')
    return "\n".join(parts)


RENDERERS = {"text": render_text, "md": render_markdown, "json": render_json, "html": render_html}


def render(result: Result, fmt: str, strict: bool = False) -> str:
    if fmt not in RENDERERS:
        valid = ", ".join(sorted(RENDERERS))
        raise ValueError(f"unknown format {fmt!r}; expected one of {valid}")
    if fmt == "text":
        return render_text(result, strict)
    return RENDERERS[fmt](result, strict)
