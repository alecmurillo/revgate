"""The Factory hook, driven with the payloads Droid actually sends.

Exit codes are the hook contract: 0 allows, 2 blocks and shows the reason to the
agent, 1 means the hook itself broke.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / ".factory" / "hooks" / "lead_list_gate.py"

ALLOW, HOOK_ERROR, BLOCK = 0, 1, 2


def run_hook(payload, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=body, cwd=REPO, capture_output=True, text=True,
        timeout=300, check=False, env=env,
    )


def post(file_path: str, tool: str = "Create") -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "tool_input": {"file_path": file_path},
        "cwd": str(REPO),
    }


def pre(command: str) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Execute",
        "tool_input": {"command": command},
        "cwd": str(REPO),
    }


class WritingALeadList(unittest.TestCase):
    def test_a_blocked_list_stops_the_edit(self):
        proc = run_hook(post("fixtures/leads-dirty.csv"))
        self.assertEqual(proc.returncode, BLOCK, proc.stderr)
        self.assertIn("does not pass the gate", proc.stderr)

    def test_the_reason_reaches_the_agent_on_stderr(self):
        proc = run_hook(post("fixtures/leads-dirty.csv"))
        self.assertIn("L003", proc.stderr, "the agent needs the findings, not just a refusal")
        self.assertIn("pipeline stage", proc.stderr)

    def test_a_clean_list_is_allowed(self):
        proc = run_hook(post("fixtures/leads-clean.csv"))
        self.assertEqual(proc.returncode, ALLOW, proc.stderr)

    def test_an_unrelated_file_is_ignored(self):
        proc = run_hook(post("revgate/cli.py", tool="Edit"))
        self.assertEqual(proc.returncode, ALLOW)

    def test_a_csv_that_is_not_a_lead_list_is_ignored(self):
        proc = run_hook(post("fixtures/dnc.csv", tool="Edit"))
        self.assertEqual(proc.returncode, ALLOW)

    def test_the_matched_paths_are_configurable(self):
        proc = run_hook(post("fixtures/dnc.csv"), env_extra={"REVGATE_HOOK_GLOBS": "dnc.csv"})
        # Now in scope, and a DNC export is not a valid lead list, so it must not
        # slip through as clean.
        self.assertNotEqual(proc.returncode, ALLOW)


class Committing(unittest.TestCase):
    def test_a_non_commit_command_is_ignored(self):
        proc = run_hook(pre("ls -la"))
        self.assertEqual(proc.returncode, ALLOW)

    def test_a_commit_with_no_staged_lead_lists_is_allowed(self):
        proc = run_hook(pre("git commit -m 'docs: readme'"))
        self.assertEqual(proc.returncode, ALLOW, proc.stderr)

    def test_a_non_execute_tool_is_ignored(self):
        payload = pre("git commit -m x")
        payload["tool_name"] = "Read"
        self.assertEqual(run_hook(payload).returncode, ALLOW)


class Robustness(unittest.TestCase):
    def test_empty_input_allows(self):
        self.assertEqual(run_hook("").returncode, ALLOW)

    def test_unparseable_input_surfaces_without_blocking_everything(self):
        proc = run_hook("this is not json")
        self.assertEqual(proc.returncode, HOOK_ERROR)
        self.assertIn("could not parse", proc.stderr)

    def test_an_unknown_event_is_ignored(self):
        self.assertEqual(run_hook({"hook_event_name": "SessionStart"}).returncode, ALLOW)

    def test_a_missing_file_path_is_ignored(self):
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Create",
                   "tool_input": {}, "cwd": str(REPO)}
        self.assertEqual(run_hook(payload).returncode, ALLOW)

    def test_a_lead_list_that_does_not_exist_is_not_reported_as_clean_or_crashed(self):
        proc = run_hook(post("fixtures/leads-ghost.csv"))
        self.assertEqual(proc.returncode, ALLOW, "nothing was written, so nothing to gate")


if __name__ == "__main__":
    unittest.main()
