#!/usr/bin/env python3
"""Block a commit, or an edit, that would put an ungated lead list into the repo.

Two events, one script:

  PostToolUse (Create|Edit|ApplyPatch)
      A lead-list CSV was just written. Lint it now and hand the findings back to
      the agent, while it still has the context to fix the thing that produced
      the file rather than patching the file.

  PreToolUse (Execute)
      The command about to run is a `git commit`. Lint every staged lead list and
      refuse the commit if any of them is blocked. This is the last point at
      which a bad list is still cheap.

Exit codes are the hook contract, not decoration:

  0   allow
  2   block, and show the reason to the agent
  1   the hook itself failed; surface the error without blocking

The asymmetry in that last case is deliberate. This gate fails closed on lint
results: a list that revgate cannot evaluate is blocked, because the whole premise
of the tool is that an unevaluated check is not a pass. But it fails open on its
own bugs, because a hook that wedges every commit in the repository gets deleted
within the hour, and a deleted gate catches nothing. Set
REVGATE_HOOK_FAIL_OPEN=1 to downgrade the first case too.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_GLOBS = (
    "leads*.csv",
    "*-leads.csv",
    "*_leads.csv",
    "leads/*.csv",
    "**/leads/*.csv",
    "lists/*.csv",
    "fixtures/leads-*.csv",
)

BLOCKED_EXIT = 2
CLEAN_EXIT = 0
HOOK_ERROR_EXIT = 1


def _globs() -> tuple[str, ...]:
    configured = os.environ.get("REVGATE_HOOK_GLOBS", "").strip()
    if not configured:
        return DEFAULT_GLOBS
    return tuple(g.strip() for g in configured.split(",") if g.strip())


def _is_lead_list(path: str) -> bool:
    if not path.lower().endswith(".csv"):
        return False
    candidate = Path(path).as_posix()
    name = Path(path).name
    for pattern in _globs():
        if fnmatch.fnmatch(candidate, pattern) or fnmatch.fnmatch(name, pattern):
            return True
        # match the pattern anywhere in the path, so `leads/*.csv` catches
        # `data/exports/leads/august.csv`
        if fnmatch.fnmatch(candidate, f"*/{pattern}"):
            return True
    return False


def _project_dir(payload: dict) -> Path:
    for candidate in (
        os.environ.get("FACTORY_PROJECT_DIR"),
        payload.get("cwd"),
        payload.get("project_dir"),
    ):
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    return Path.cwd()


def _staged_csvs(root: Path) -> tuple[list[str], str | None]:
    """Return (staged CSVs, error_message).

    On enumeration failure, returns ([], error_message) so the caller can
    block rather than silently allowing the commit through.
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=root, capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"git enumeration failed: {exc}"
    if proc.returncode != 0:
        return [], f"git diff exited {proc.returncode}: {proc.stderr.strip()}"
    return [line.strip() for line in proc.stdout.splitlines() if _is_lead_list(line.strip())], None


def _lint(root: Path, relative: str) -> tuple[int, str]:
    """Run the gate. Returns (exit_code, output)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "revgate", "lint", relative, "--format", "text", "--no-record"],
            cwd=root, capture_output=True, text=True, timeout=120, check=False,
        )
    except FileNotFoundError:
        return -1, "revgate is not installed in this interpreter"
    except subprocess.SubprocessError as exc:
        return -1, f"revgate did not complete: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _fail_open() -> bool:
    return os.environ.get("REVGATE_HOOK_FAIL_OPEN", "").strip().lower() in {"1", "true", "yes"}


def _gate(root: Path, targets: list[str], preamble: str) -> int:
    blocked: list[str] = []
    unevaluated: list[str] = []
    reports: list[str] = []

    for relative in targets:
        if not (root / relative).is_file():
            continue
        code, output = _lint(root, relative)
        if code == BLOCKED_EXIT:
            blocked.append(relative)
            reports.append(output.rstrip())
        elif code not in (0, 1):
            # 3 is a usage error, -1 is a harness failure. Either way the list was
            # not evaluated, which is not the same as the list being clean.
            unevaluated.append(f"{relative}: exit {code}")
            reports.append(output.rstrip())

    if not blocked and not unevaluated:
        return CLEAN_EXIT

    lines = [preamble, ""]
    if blocked:
        lines.append("Blocked by revgate (P0 findings or blocking skips):")
        lines += [f"  {b}" for b in blocked]
    if unevaluated:
        lines.append("Could not be evaluated, so it is not cleared:")
        lines += [f"  {u}" for u in unevaluated]
    lines.append("")
    lines += reports
    lines.append("")
    lines.append("Fix the pipeline stage that produced these rows, not the rows.")
    print("\n".join(lines), file=sys.stderr)

    if unevaluated and not blocked and _fail_open():
        return CLEAN_EXIT
    return BLOCKED_EXIT


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return CLEAN_EXIT
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("lead_list_gate: could not parse hook payload", file=sys.stderr)
        return HOOK_ERROR_EXIT

    event = payload.get("hook_event_name") or payload.get("event") or ""
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    root = _project_dir(payload)

    if event == "PreToolUse":
        if tool != "Execute":
            return CLEAN_EXIT
        command = str(tool_input.get("command", ""))
        if "git commit" not in command:
            return CLEAN_EXIT
        staged, enum_err = _staged_csvs(root)
        if enum_err:
            print(f"lead_list_gate: could not enumerate staged files: {enum_err}", file=sys.stderr)
            if _fail_open():
                return CLEAN_EXIT
            return BLOCKED_EXIT
        if not staged:
            return CLEAN_EXIT
        return _gate(
            root, staged,
            "Commit refused: a staged lead list does not pass the gate.",
        )

    if event == "PostToolUse":
        path = str(
            tool_input.get("file_path")
            or tool_input.get("path")
            or tool_input.get("filePath")
            or ""
        )
        if not path or not _is_lead_list(path):
            return CLEAN_EXIT
        try:
            relative = Path(path).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            relative = path
        return _gate(
            root, [relative],
            f"{relative} was written but does not pass the gate.",
        )

    return CLEAN_EXIT


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - a hook must not raise into the session
        print(f"lead_list_gate failed: {exc}", file=sys.stderr)
        sys.exit(HOOK_ERROR_EXIT)
