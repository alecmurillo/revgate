"""Verified provenance: prove how this repository uses Factory, don't assert it.

A README can claim anything. This module turns those claims into checks.

`factory-usage.toml` lists every Factory surface the project says it uses. Running
`revgate provenance` validates each claim against the file it names — skill
frontmatter parses and carries the required fields, custom droids declare a legal
tool policy, `hooks.json` only registers real lifecycle events, the CI workflow
really does invoke `droid exec` — and fails if a claim does not hold. It also walks
the repository in the other direction and flags any Factory surface that exists but
is not documented, because undocumented drift is how a manifest becomes fiction.

Second half of the module is run history. Every revgate invocation appends a record
under `.revgate/runs/`, including the `session_id` of any `droid exec` judgement.
That turns "this project uses Droid" into a countable, auditable claim.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core.config import Config
from .core.findings import Finding, Result, Severity, Skipped

MANIFEST_NAME = "factory-usage.toml"

# From the documented custom-droid tool policy.
TOOL_CATEGORIES = {"read-only", "edit", "execute", "web", "mcp"}
TOOL_IDS = {
    "Read", "LS", "Grep", "Glob", "Create", "Edit", "ApplyPatch", "Execute",
    "WebSearch", "FetchUrl", "TodoWrite", "Skill", "Task", "TaskOutput", "TaskStop",
    "AskUser",
}
FORBIDDEN_TOOLS = {"ExitSpecMode", "GenerateDroid"}

HOOK_EVENTS = {
    "PreToolUse", "PostToolUse", "UserPromptSubmit", "Notification", "Stop",
    "SubagentStop", "PreCompact", "SessionStart", "SessionEnd",
}

_DROID_NAME_RE = re.compile(r"^[a-z0-9-_]+$")


# --------------------------------------------------------------------------
# a small, dependency-free frontmatter reader
# --------------------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse the YAML subset that skill and droid files actually use.

    Supports `key: value`, inline arrays (`tools: [Read, Grep]`), and block lists.
    Deliberately not a YAML implementation: this needs to run with no dependencies,
    and the files it reads are small and hand-written.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}, text

    data: dict[str, Any] = {}
    current_key: str | None = None
    for raw in lines[1:end]:
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and current_key:
            data.setdefault(current_key, [])
            if isinstance(data[current_key], list):
                data[current_key].append(item.group(1).strip().strip("\"'"))
            continue
        kv = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if not kv:
            continue
        key, value = kv.group(1), kv.group(2).strip()
        current_key = key
        if value == "":
            data[key] = []
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data[key] = [v.strip().strip("\"'") for v in inner.split(",") if v.strip()] if inner else []
            continue
        data[key] = value.strip().strip("\"'")
    body = "\n".join(lines[end + 1:])
    return data, body


# --------------------------------------------------------------------------
# claim verification
# --------------------------------------------------------------------------

@dataclass
class Claim:
    id: str
    surface: str
    path: str
    check: str
    does: str = ""
    novel: str = ""
    expect: tuple[str, ...] = ()


def _load_manifest(path: Path) -> tuple[list[Claim], dict[str, Any]]:
    import tomllib

    with path.open("rb") as fh:
        data = tomllib.load(fh)
    claims: list[Claim] = []
    for i, raw in enumerate(data.get("surface", []) or [], start=1):
        missing = [k for k in ("id", "surface", "path", "check") if not raw.get(k)]
        if missing:
            raise ValueError(f"{path}: surface #{i} is missing {', '.join(missing)}")
        claims.append(Claim(
            id=str(raw["id"]),
            surface=str(raw["surface"]),
            path=str(raw["path"]),
            check=str(raw["check"]),
            does=str(raw.get("does", "")),
            novel=str(raw.get("novel", "")),
            expect=tuple(str(e) for e in raw.get("expect", []) or ()),
        ))
    return claims, data


def _finding(claim: Claim, detail: str, severity: Severity = Severity.P0) -> Finding:
    return Finding(
        rule=claim.id,
        severity=severity,
        title=f"{claim.surface} claim does not hold",
        detail=detail,
        remedy=f"Fix {claim.path}, or remove the claim from {MANIFEST_NAME}.",
        origin=(
            "A documented integration that no longer works is worse than an undocumented one: "
            "somebody trusts it."
        ),
        key=claim.path,
    )


def _check_skill(claim: Claim, path: Path) -> list[Finding]:
    if path.name != "SKILL.md":
        return [_finding(claim, f"{path} must be named SKILL.md to be discovered")]
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    out: list[Finding] = []
    for field_name in ("name", "description"):
        if not meta.get(field_name):
            out.append(_finding(claim, f"skill frontmatter is missing required `{field_name}`"))
    if str(meta.get("enabled", "true")).lower() == "false":
        out.append(_finding(claim, "skill is disabled by frontmatter (`enabled: false`)", Severity.P1))
    if not body.strip():
        out.append(_finding(claim, "skill body is empty, so there is no workflow to run"))
    name = str(meta.get("name", ""))
    if name and name != path.parent.name:
        out.append(_finding(
            claim,
            f"skill name {name!r} does not match its directory {path.parent.name!r}, "
            "which makes the slash command ambiguous",
            Severity.P1,
        ))
    return out


def _check_droid(claim: Claim, path: Path) -> list[Finding]:
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    out: list[Finding] = []
    name = str(meta.get("name", ""))
    if not name:
        out.append(_finding(claim, "droid frontmatter is missing required `name`"))
    elif not _DROID_NAME_RE.match(name):
        out.append(_finding(claim, f"droid name {name!r} must match ^[a-z0-9-_]+$"))
    elif name != path.stem:
        out.append(_finding(
            claim, f"droid name {name!r} does not match filename {path.stem!r}", Severity.P1
        ))
    if not meta.get("description"):
        out.append(_finding(claim, "droid has no description, so /droids cannot describe it", Severity.P1))
    if not body.strip():
        out.append(_finding(claim, "droid system prompt body is empty, which fails validation at load"))

    tools = meta.get("tools")
    if isinstance(tools, str):
        if tools.strip().lower() == "all":
            out.append(_finding(claim, "`tools: all` is rejected by the validator; omit the field instead"))
        elif tools.strip() not in TOOL_CATEGORIES:
            out.append(_finding(
                claim,
                f"tool category {tools!r} is not one of: {', '.join(sorted(TOOL_CATEGORIES))}",
            ))
    elif isinstance(tools, list):
        for tool in tools:
            if tool in FORBIDDEN_TOOLS:
                out.append(_finding(claim, f"tool {tool!r} cannot be enabled by a custom droid"))
            elif tool not in TOOL_IDS and not tool.startswith("mcp__"):
                out.append(_finding(claim, f"unknown tool id {tool!r}"))
    return out


def _check_hooks(claim: Claim, path: Path) -> list[Finding]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [_finding(claim, f"hooks file is not valid JSON: {exc}")]
    if isinstance(data, dict) and "hooks" in data and isinstance(data["hooks"], dict):
        data = data["hooks"]
    out: list[Finding] = []
    if not isinstance(data, dict) or not data:
        return [_finding(claim, "hooks file registers no events")]
    for event, groups in data.items():
        if event not in HOOK_EVENTS:
            out.append(_finding(
                claim,
                f"{event!r} is not a Droid lifecycle event, so this hook will never fire",
            ))
            continue
        if not isinstance(groups, list) or not groups:
            out.append(_finding(claim, f"event {event} has no matcher groups"))
            continue
        for group in groups:
            entries = (group or {}).get("hooks")
            if not entries:
                out.append(_finding(claim, f"event {event} has a matcher group with no commands"))
                continue
            for entry in entries:
                if entry.get("type") != "command":
                    out.append(_finding(claim, f"event {event}: hook type must be 'command'"))
                if not entry.get("command"):
                    out.append(_finding(claim, f"event {event}: hook has no command"))
    return out


def _check_contains(claim: Claim, path: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8", errors="replace")
    missing = [needle for needle in claim.expect if needle not in text]
    if missing:
        return [_finding(
            claim,
            "file does not contain the expected marker(s): " + ", ".join(repr(m) for m in missing),
        )]
    return []


_CHECKS = {
    "skill": _check_skill,
    "droid": _check_droid,
    "hooks": _check_hooks,
    "workflow": _check_contains,
    "code": _check_contains,
    "file": lambda claim, path: [],
}


def _discover_surfaces(root: Path) -> set[str]:
    found: set[str] = set()
    for pattern in (
        ".factory/skills/*/SKILL.md",
        ".factory/droids/*.md",
        ".factory/hooks.json",
        ".factory/hooks/*.py",
        ".github/workflows/*.yml",
        ".github/workflows/*.yaml",
    ):
        for path in root.glob(pattern):
            found.add(path.relative_to(root).as_posix())
    return found


def verify(cfg: Config) -> Result:
    manifest_path = Path(cfg.manifest) if cfg.manifest else (cfg.root / MANIFEST_NAME)
    result = Result(surface="provenance", target=str(manifest_path))

    if not manifest_path.is_file():
        result.skipped.append(Skipped(
            rule="manifest",
            reason=f"no {MANIFEST_NAME} found at {manifest_path}; nothing to verify against",
            blocking=True,
        ))
        return result

    try:
        claims, raw = _load_manifest(manifest_path)
    except (ValueError, OSError) as exc:
        result.skipped.append(Skipped(rule="manifest", reason=str(exc), blocking=True))
        return result

    claimed_paths: set[str] = set()
    by_surface: dict[str, int] = {}

    for claim in claims:
        path = (cfg.root / claim.path).resolve()
        claimed_paths.add(claim.path)
        by_surface[claim.surface] = by_surface.get(claim.surface, 0) + 1

        if claim.check not in _CHECKS:
            result.findings.append(_finding(
                claim, f"unknown check {claim.check!r}; expected one of: {', '.join(sorted(_CHECKS))}"
            ))
            continue
        if not path.exists():
            result.findings.append(_finding(claim, f"claimed path does not exist: {claim.path}"))
            continue

        result.findings.extend(_CHECKS[claim.check](claim, path))
        if claim.expect and claim.check not in ("workflow", "code"):
            result.findings.extend(_check_contains(claim, path))

    for discovered in sorted(_discover_surfaces(cfg.root) - claimed_paths):
        result.findings.append(Finding(
            rule="undocumented",
            severity=Severity.P1,
            title="Factory surface present but not documented",
            detail=f"{discovered} exists in the repository but no claim in {MANIFEST_NAME} covers it",
            remedy=f"Add a [[surface]] entry for it, or delete the file.",
            origin=(
                "A manifest that lags the repository stops being evidence. The reverse check is "
                "what keeps it honest."
            ),
            key=discovered,
        ))

    result.stats = {
        "claims": len(claims),
        "verified": len(claims) - len({f.rule for f in result.findings if f.rule != "undocumented"}),
        "surfaces": len(by_surface),
    }
    result.notes.append("Surfaces claimed: " + ", ".join(f"{k} ×{v}" for k, v in sorted(by_surface.items())))
    result.notes.append(
        f"{result.stats['verified']}/{result.stats['claims']} claims verified present "
        "against the files they name. 'Verified' means the file exists and carries "
        "the expected fields — not that the surface has been exercised in a live run."
    )
    return result


def describe(cfg: Config) -> list[Claim]:
    manifest_path = Path(cfg.manifest) if cfg.manifest else (cfg.root / MANIFEST_NAME)
    if not manifest_path.is_file():
        return []
    claims, _ = _load_manifest(manifest_path)
    return claims


# --------------------------------------------------------------------------
# run history
# --------------------------------------------------------------------------

def record_run(cfg: Config, result: Result, extra: dict[str, Any] | None = None) -> Path | None:
    """Append one run record. Never raises: telemetry must not break the tool."""
    directory = Path(cfg.runs_dir) if cfg.runs_dir else (cfg.root / ".revgate" / "runs")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "surface": result.surface,
            "target": result.target,
            "verdict": result.verdict(cfg.strict),
            "counts": result.counts(),
            "skipped": len(result.skipped),
            "droid_sessions": result.stats.get("droid_sessions", []),
            "judge": result.stats.get("judge"),
        }
        if extra:
            payload.update(extra)
        path = directory / f"{stamp}-{result.surface}.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path
    except OSError:
        return None


def summarize_runs(cfg: Config) -> dict[str, Any]:
    directory = Path(cfg.runs_dir) if cfg.runs_dir else (cfg.root / ".revgate" / "runs")
    summary: dict[str, Any] = {
        "runs": 0,
        "by_surface": {},
        "droid_judged_assertions": 0,
        "droid_sessions": [],
        "first": None,
        "last": None,
    }
    if not directory.is_dir():
        return summary

    sessions: list[str] = []
    stamps: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        summary["runs"] += 1
        surface = str(data.get("surface", "unknown"))
        summary["by_surface"][surface] = summary["by_surface"].get(surface, 0) + 1
        records = data.get("droid_sessions") or []
        summary["droid_judged_assertions"] += len(records)
        for record in records:
            sid = record.get("session_id")
            if sid and sid not in sessions:
                sessions.append(sid)
        if data.get("timestamp"):
            stamps.append(str(data["timestamp"]))

    summary["droid_sessions"] = sessions
    if stamps:
        summary["first"] = min(stamps)
        summary["last"] = max(stamps)
    return summary
