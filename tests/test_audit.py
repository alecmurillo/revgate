"""Tests for the multi-agent audit command.

Tests the pattern-only path (no droid needed) and the structure of the
agent review. The droid exec path is tested for fail-closed behavior when
the droid CLI is not available.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from revgate.audit import audit, render_audit_text, render_audit_json, AgentReview, AuditResult
from revgate.core.config import Config
from revgate.core.findings import Result, Finding, Severity

FIXTURES = _REPO / "fixtures"


class TestAuditPatternOnly(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_dirty_list_blocked(self):
        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=False)
        self.assertEqual(result.verdict, "BLOCKED")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(len(result.agent_reviews), 0)
        self.assertIn("Phase 1", result.phases[0])

    def test_clean_list_passes(self):
        result = audit(FIXTURES / "leads-clean.csv", self.cfg, use_droid=False)
        self.assertEqual(result.verdict, "PASS")
        self.assertEqual(result.exit_code, 0)

    def test_text_render(self):
        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=False)
        text = render_audit_text(result)
        self.assertIn("revgate audit", text)
        self.assertIn("Phase 1", text)

    def test_json_render(self):
        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=False)
        js = render_audit_json(result)
        parsed = json.loads(js)
        self.assertEqual(parsed["verdict"], "BLOCKED")
        self.assertIn("phases", parsed)
        self.assertEqual(parsed["agent_reviews"], [])

    def test_phases_list(self):
        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=False)
        self.assertEqual(len(result.phases), 1)
        self.assertIn("Pattern gates", result.phases[0])


class TestAuditDroid(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_droid_not_available_fails_closed(self):
        """When droid is not on PATH, agent reviews are unjudged and the audit blocks."""
        with patch("revgate.audit.shutil.which", return_value=None):
            result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        self.assertEqual(result.verdict, "BLOCKED")
        self.assertGreater(len(result.agent_reviews), 0)
        for review in result.agent_reviews:
            self.assertEqual(review.verdict, "unjudged")
            self.assertEqual(review.session_id, "")
            self.assertTrue(review.error)

    def test_droid_phases_include_all_three(self):
        with patch("revgate.audit.shutil.which", return_value=None):
            result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        # Phase 1, Phase 2 (with unjudged), Phase 3
        self.assertGreaterEqual(len(result.phases), 2)

    def test_unjudged_groups_count(self):
        with patch("revgate.audit.shutil.which", return_value=None):
            result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        self.assertGreater(result.unjudged_groups, 0)

    def test_agent_sessions_zero_when_unavailable(self):
        with patch("revgate.audit.shutil.which", return_value=None):
            result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        self.assertEqual(result.agent_sessions, 0)

    def test_json_includes_agent_reviews(self):
        with patch("revgate.audit.shutil.which", return_value=None):
            result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        js = render_audit_json(result)
        parsed = json.loads(js)
        self.assertGreater(len(parsed["agent_reviews"]), 0)
        for review in parsed["agent_reviews"]:
            self.assertEqual(review["verdict"], "unjudged")

    def test_text_shows_unjudged_warning(self):
        with patch("revgate.audit.shutil.which", return_value=None):
            result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        text = render_audit_text(result)
        self.assertIn("could not be evaluated", text)


class TestAuditMockedDroid(unittest.TestCase):
    """Test with a mocked droid exec that returns a confirmed verdict."""

    def setUp(self):
        self.cfg = Config()

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_mocked_droid_confirmed(self, mock_run, mock_which):
        mock_run.return_value = type(
            "CompletedProcess", (),
            {
                "returncode": 0,
                "stdout": json.dumps({
                    "session_id": "test-session-abc",
                    "duration_ms": 1500,
                    "num_turns": 1,
                    "is_error": False,
                    "result": '{"verdict": "confirmed", "true_positives": 3, "false_positives": 0, "remediation": "Remove blocked rows"}',
                }),
                "stderr": "",
            },
        )

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        self.assertGreater(len(result.agent_reviews), 0)
        review = result.agent_reviews[0]
        self.assertEqual(review.verdict, "confirmed")
        self.assertEqual(review.true_positives, 3)
        self.assertEqual(review.false_positives, 0)
        self.assertEqual(review.session_id, "test-session-abc")
        self.assertEqual(review.remediation, "Remove blocked rows")
        self.assertGreater(result.agent_sessions, 0)
        self.assertEqual(result.unjudged_groups, 0)

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_mocked_droid_false_positive(self, mock_run, mock_which):
        mock_run.return_value = type(
            "CompletedProcess", (),
            {
                "returncode": 0,
                "stdout": json.dumps({
                    "session_id": "test-session-fp",
                    "duration_ms": 1200,
                    "num_turns": 1,
                    "is_error": False,
                    "result": '{"verdict": "false_positive", "true_positives": 0, "false_positives": 2, "remediation": "Review these rows manually"}',
                }),
                "stderr": "",
            },
        )

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        review = result.agent_reviews[0]
        self.assertEqual(review.verdict, "false_positive")
        self.assertEqual(review.false_positives, 2)

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_mocked_droid_timeout(self, mock_run, mock_which):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="droid", timeout=120)

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        review = result.agent_reviews[0]
        self.assertEqual(review.verdict, "unjudged")
        self.assertIn("timed out", review.error)


if __name__ == "__main__":
    unittest.main()
