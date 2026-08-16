"""End-to-end CLI behaviour, run the way CI runs it.

The exit codes are the product. Everything downstream, hooks, pipelines, the GitHub
workflow, depends on 0/1/2/3 meaning exactly what the README says, so they are
tested through a real subprocess rather than by calling main() in-process.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIRTY = "fixtures/leads-dirty.csv"
CLEAN = "fixtures/leads-clean.csv"
TODAY = "2026-08-16"


def revgate(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "revgate", *args],
        cwd=REPO, capture_output=True, text=True, timeout=300, check=False,
    )


class ExitCodeContract(unittest.TestCase):
    def test_dirty_list_blocks(self):
        proc = revgate("lint", DIRTY, "--today", TODAY, "--no-record")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("BLOCKED", proc.stdout)

    def test_clean_list_passes(self):
        proc = revgate("lint", CLEAN, "--today", TODAY, "--no-record")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS", proc.stdout)

    def test_demo_agent_is_caught(self):
        proc = revgate("redteam", "--target", "demo", "--no-record")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)

    def test_provenance_passes(self):
        proc = revgate("provenance", "--no-record")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_missing_file_is_a_usage_error_not_a_pass(self):
        proc = revgate("lint", "fixtures/does-not-exist.csv", "--no-record")
        self.assertEqual(proc.returncode, 3, "a file that cannot be read is not a clean list")

    def test_unknown_gate_is_a_usage_error(self):
        proc = revgate("lint", CLEAN, "--only", "L999", "--no-record")
        self.assertEqual(proc.returncode, 3)

    def test_bad_date_is_a_usage_error(self):
        proc = revgate("lint", CLEAN, "--today", "16-08-2026", "--no-record")
        self.assertEqual(proc.returncode, 3)

    def test_unknown_battery_is_a_usage_error(self):
        proc = revgate("redteam", "--battery", "/nonexistent.toml", "--no-record")
        self.assertEqual(proc.returncode, 3)

    def test_strict_promotes_advisories_on_a_p1_only_run(self):
        # L007 is P1, so on its own it is advisory, and blocking under --strict.
        relaxed = revgate("lint", DIRTY, "--today", TODAY, "--only", "L007", "--no-record")
        self.assertEqual(relaxed.returncode, 0)
        strict = revgate("lint", DIRTY, "--today", TODAY, "--only", "L007", "--strict", "--no-record")
        self.assertEqual(strict.returncode, 1)


class OutputFormats(unittest.TestCase):
    def test_json_is_machine_readable_and_complete(self):
        proc = revgate("lint", DIRTY, "--today", TODAY, "--format", "json", "--no-record")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["verdict"], "BLOCKED")
        self.assertEqual(payload["exit_code"], 2)
        self.assertEqual(payload["counts"]["P0"] > 0, True)
        self.assertIn("origin", payload["findings"][0])

    def test_markdown_renders_findings(self):
        proc = revgate("lint", DIRTY, "--today", TODAY, "--format", "md", "--no-record")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("### Findings", proc.stdout)
        self.assertIn("<details>", proc.stdout)

    def test_out_writes_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.json"
            proc = revgate("lint", CLEAN, "--today", TODAY, "--format", "json",
                           "--out", str(target), "--no-record")
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(target.is_file())
            json.loads(target.read_text())

    def test_rules_json_lists_every_gate_with_its_origin(self):
        proc = revgate("rules", "--format", "json")
        payload = json.loads(proc.stdout)
        self.assertEqual(len(payload), 22)
        for entry in payload:
            self.assertTrue(entry["origin"].strip())

    def test_scenarios_json_exposes_assertions(self):
        proc = revgate("scenarios", "--format", "json")
        payload = json.loads(proc.stdout)
        self.assertGreaterEqual(len(payload), 20)
        self.assertIn("must_not_match", payload[0]["assertions"])


class Introspection(unittest.TestCase):
    def test_version(self):
        proc = revgate("--version")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("revgate", proc.stdout)

    def test_no_subcommand_is_a_usage_error(self):
        proc = revgate()
        self.assertNotEqual(proc.returncode, 0)

    def test_run_history_reports_droid_usage(self):
        proc = revgate("provenance", "--runs", "--format", "json", "--no-record")
        payload = json.loads(proc.stdout)
        for key in ("runs", "droid_judged_assertions", "droid_sessions"):
            self.assertIn(key, payload)


class Recording(unittest.TestCase):
    def test_a_run_is_recorded_under_the_configured_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "revgate.toml"
            config.write_text(
                "[provenance]\n"
                f'runs_dir = "{Path(tmp) / "runs"}"\n',
                encoding="utf-8",
            )
            proc = revgate("lint", str(REPO / CLEAN), "--today", TODAY, "-c", str(config))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            records = list((Path(tmp) / "runs").glob("*.json"))
            self.assertEqual(len(records), 1)
            payload = json.loads(records[0].read_text())
            self.assertEqual(payload["surface"], "lists")
            self.assertEqual(payload["verdict"], "PASS")


class DiffCommand(unittest.TestCase):
    def test_diff_identical_lists_passes(self):
        proc = revgate("diff", CLEAN, CLEAN, "--today", TODAY, "--no-record")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("0 new", proc.stdout)
        self.assertIn("0 removed", proc.stdout)
        self.assertIn("0 changed", proc.stdout)

    def test_diff_dirty_against_clean_blocks(self):
        proc = revgate("diff", CLEAN, DIRTY, "--today", TODAY, "--no-record")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("BLOCKED", proc.stdout)
        self.assertIn("new account(s)", proc.stdout)

    def test_diff_missing_file_is_usage_error(self):
        proc = revgate("diff", CLEAN, "fixtures/ghost.csv", "--no-record")
        self.assertEqual(proc.returncode, 3)

    def test_diff_json_includes_diff_stats(self):
        proc = revgate("diff", CLEAN, DIRTY, "--today", TODAY,
                       "--format", "json", "--no-record")
        payload = json.loads(proc.stdout)
        self.assertIn("added", payload["stats"])
        self.assertIn("removed", payload["stats"])
        self.assertIn("changed", payload["stats"])
        self.assertGreater(payload["stats"]["added"], 0)


class HtmlReport(unittest.TestCase):
    def test_html_is_self_contained(self):
        proc = revgate("lint", DIRTY, "--today", TODAY, "--format", "html", "--no-record")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("<!DOCTYPE html>", proc.stdout)
        self.assertIn("</html>", proc.stdout)
        self.assertIn("BLOCKED", proc.stdout)
        self.assertIn("finding", proc.stdout)

    def test_html_out_writes_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.html"
            proc = revgate("lint", CLEAN, "--today", TODAY, "--format", "html",
                           "--out", str(target), "--no-record")
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(target.is_file())
            content = target.read_text()
            self.assertIn("<!DOCTYPE html>", content)
            self.assertIn("PASS", content)


class AuditCommand(unittest.TestCase):

    def test_audit_pattern_only_dirty_blocks(self):
        proc = revgate("audit", DIRTY, "--judge", "pattern", "--today", TODAY, "--no-record")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("BLOCKED", proc.stdout)

    def test_audit_pattern_only_clean_passes(self):
        proc = revgate("audit", CLEAN, "--judge", "pattern", "--today", TODAY, "--no-record")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("PASS", proc.stdout)

    def test_audit_json_includes_phases_and_milestones(self):
        proc = revgate("audit", DIRTY, "--judge", "pattern", "--format", "json",
                       "--today", TODAY, "--no-record")
        self.assertEqual(proc.returncode, 2)
        parsed = json.loads(proc.stdout)
        self.assertIn("phases", parsed)
        self.assertIn("milestones", parsed)
        self.assertIn("plan", parsed)

    def test_audit_max_workers_flag_exists(self):
        proc = revgate("audit", "--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--max-workers", proc.stdout)


if __name__ == "__main__":
    unittest.main()
