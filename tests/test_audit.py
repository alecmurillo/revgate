"""Tests for the multi-agent audit command.

Tests the pattern-only path, parallel agent review, cross-validation
synthesis, milestone reporting, and fail-closed behavior when droid is
unavailable.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from revgate.audit import (
    audit, render_audit_text, render_audit_json,
    AgentReview, AuditResult, ReviewPlan, SynthesisReview, Milestone, RootCause,
)
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
        self.assertIsNone(result.synthesis)

    def test_clean_list_passes(self):
        result = audit(FIXTURES / "leads-clean.csv", self.cfg, use_droid=False)
        self.assertEqual(result.verdict, "PASS")
        self.assertEqual(result.exit_code, 0)

    def test_text_render(self):
        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=False)
        text = render_audit_text(result)
        self.assertIn("revgate audit", text)
        self.assertIn("Phase 0", text)
        self.assertIn("Phase 1", text)

    def test_json_render(self):
        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=False)
        js = render_audit_json(result)
        parsed = json.loads(js)
        self.assertEqual(parsed["verdict"], "BLOCKED")
        self.assertIn("phases", parsed)
        self.assertIn("milestones", parsed)
        self.assertIn("plan", parsed)

    def test_plan_generated(self):
        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=False)
        self.assertIsNotNone(result.plan)
        self.assertGreater(result.plan.total_findings, 0)
        self.assertGreater(len(result.plan.rule_groups), 0)
        self.assertGreater(result.plan.estimated_sessions, 0)

    def test_milestones_present(self):
        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=False)
        self.assertGreaterEqual(len(result.milestones), 2)  # planning + pattern-gates
        for m in result.milestones:
            self.assertIn(m.phase, ("planning", "pattern-gates", "parallel-review", "root-cause-analysis", "cross-validation", "final-report"))
            self.assertIn(m.status, ("complete", "skipped", "partial", "unjudged"))

    def test_phases_include_planning(self):
        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=False)
        self.assertTrue(any("Phase 0" in p for p in result.phases))
        self.assertTrue(any("Phase 1" in p for p in result.phases))


class TestAuditDroidUnavailable(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_droid_not_available_fails_closed(self):
        with patch("revgate.audit.shutil.which", return_value=None):
            result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        self.assertEqual(result.verdict, "BLOCKED")
        self.assertGreater(len(result.agent_reviews), 0)
        for review in result.agent_reviews:
            self.assertEqual(review.verdict, "unjudged")
            self.assertEqual(review.session_id, "")
            self.assertTrue(review.error)

    def test_milestones_show_unjudged(self):
        with patch("revgate.audit.shutil.which", return_value=None):
            result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        parallel_ms = [m for m in result.milestones if m.phase == "parallel-review"]
        self.assertEqual(len(parallel_ms), 1)
        self.assertEqual(parallel_ms[0].sessions, 0)

    def test_synthesis_unjudged_when_droid_unavailable(self):
        with patch("revgate.audit.shutil.which", return_value=None):
            result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        self.assertIsNotNone(result.synthesis)
        self.assertEqual(result.synthesis.overall, "unjudged")
        self.assertTrue(result.synthesis.error)

    def test_agent_sessions_zero_when_unavailable(self):
        with patch("revgate.audit.shutil.which", return_value=None):
            result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        self.assertEqual(result.agent_sessions, 0)

    def test_json_includes_milestones_and_synthesis(self):
        with patch("revgate.audit.shutil.which", return_value=None):
            result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        js = render_audit_json(result)
        parsed = json.loads(js)
        self.assertIn("milestones", parsed)
        self.assertIn("synthesis", parsed)
        self.assertEqual(parsed["synthesis"]["overall"], "unjudged")


class TestAuditMockedDroid(unittest.TestCase):
    """Test with mocked droid exec that returns confirmed verdicts."""

    def setUp(self):
        self.cfg = Config()

    @staticmethod
    def _mock_droid_response(*args, **kwargs):
        """Return review, root cause, or synthesis response based on prompt content."""
        argv = args[0] if args else kwargs.get("args", [])
        tmp_file = [a for a in argv if a.endswith(".md")]
        if tmp_file:
            content = Path(tmp_file[0]).read_text()
            if "synthesis reviewer" in content:
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps({
                        "session_id": "synth-session",
                        "duration_ms": 2000,
                        "num_turns": 1,
                        "is_error": False,
                        "result": '{"overall": "blocked", "disagreements": [], "recommendation": "Fix all P0 issues"}',
                    }),
                    stderr="",
                )
            if "root cause analyst" in content:
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps({
                        "session_id": "rootcause-session",
                        "duration_ms": 1800,
                        "num_turns": 1,
                        "is_error": False,
                        "result": '{"root_causes": [{"cause": "Multiple rows share stale enrichment dates from the same export batch", "affected_rules": ["L015", "L007"], "affected_rows": ["row 16", "row 17"], "upstream_fix": "Re-verify the entire January export batch before sending"}]}',
                    }),
                    stderr="",
                )
        return MagicMock(
            returncode=0,
            stdout=json.dumps({
                "session_id": "test-session-abc",
                "duration_ms": 1500,
                "num_turns": 1,
                "is_error": False,
                "result": '{"verdict": "confirmed", "true_positives": 3, "false_positives": 0, "remediation": "Remove blocked rows"}',
            }),
            stderr="",
        )

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_mocked_droid_confirmed_parallel(self, mock_run, mock_which):
        """Multiple sessions run in parallel and all return confirmed."""
        mock_run.side_effect = self._mock_droid_response

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True, max_workers=2)
        self.assertGreater(len(result.agent_reviews), 0)
        for review in result.agent_reviews:
            self.assertEqual(review.verdict, "confirmed")
            self.assertEqual(review.session_id, "test-session-abc")
            self.assertGreater(review.duration_ms, 0)

        # Synthesis should also have run.
        self.assertIsNotNone(result.synthesis)
        self.assertEqual(result.synthesis.overall, "blocked")

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_mocked_droid_milestone_count(self, mock_run, mock_which):
        mock_run.side_effect = self._mock_droid_response

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        # Should have 6 milestones: planning, pattern-gates, parallel-review, root-cause-analysis, cross-validation, final-report
        self.assertEqual(len(result.milestones), 6)

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_mocked_droid_phases_count(self, mock_run, mock_which):
        mock_run.side_effect = self._mock_droid_response

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        # Should have 6 phases: 0, 1, 2, 2.5, 3, 4
        self.assertEqual(len(result.phases), 6)

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_mocked_droid_timeout(self, mock_run, mock_which):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="droid", timeout=120)

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        review = result.agent_reviews[0]
        self.assertEqual(review.verdict, "unjudged")
        self.assertIn("timed out", review.error)

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_agent_sessions_count_includes_synthesis(self, mock_run, mock_which):
        mock_run.side_effect = self._mock_droid_response

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        # agent_sessions includes both review sessions and the synthesis session
        self.assertGreater(result.agent_sessions, len(result.agent_reviews))

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_json_includes_synthesis_with_disagreements(self, mock_run, mock_which):
        def mock_with_disagreements(*args, **kwargs):
            argv = args[0] if args else kwargs.get("args", [])
            tmp_file = [a for a in argv if a.endswith(".md")]
            if tmp_file:
                content = Path(tmp_file[0]).read_text()
                if "synthesis reviewer" in content:
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps({
                            "session_id": "synth-session",
                            "duration_ms": 2000,
                            "num_turns": 1,
                            "is_error": False,
                            "result": '{"overall": "blocked", "disagreements": ["L004: reviewer says confirmed but data looks stale"], "recommendation": "Fix P0 issues before sending"}',
                        }),
                        stderr="",
                    )
                if "root cause analyst" in content:
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps({
                            "session_id": "rootcause-session",
                            "duration_ms": 1800,
                            "num_turns": 1,
                            "is_error": False,
                            "result": '{"root_causes": [{"cause": "Stale export batch", "affected_rules": ["L015"], "affected_rows": ["row 16"], "upstream_fix": "Re-verify batch"}]}',
                        }),
                        stderr="",
                    )
            return MagicMock(
                returncode=0,
                stdout=json.dumps({
                    "session_id": "test-session",
                    "duration_ms": 1000,
                    "num_turns": 1,
                    "is_error": False,
                    "result": '{"verdict": "confirmed", "true_positives": 1, "false_positives": 0, "remediation": "Fix"}',
                }),
                stderr="",
            )
        mock_run.side_effect = mock_with_disagreements

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        js = render_audit_json(result)
        parsed = json.loads(js)
        self.assertEqual(parsed["synthesis"]["overall"], "blocked")
        self.assertGreater(len(parsed["synthesis"]["disagreements"]), 0)

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_text_shows_milestones_and_synthesis(self, mock_run, mock_which):
        mock_run.side_effect = self._mock_droid_response

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        text = render_audit_text(result)
        self.assertIn("Milestones:", text)
        self.assertIn("Cross-validation synthesis:", text)
        self.assertIn("Plan:", text)

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_root_cause_analysis(self, mock_run, mock_which):
        """Root cause analysis session identifies systemic patterns."""
        mock_run.side_effect = self._mock_droid_response

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        self.assertGreater(len(result.root_causes), 0)
        rc = result.root_causes[0]
        self.assertTrue(rc.cause)
        self.assertTrue(rc.session_id)
        self.assertGreater(len(rc.affected_rules), 0)
        self.assertTrue(rc.upstream_fix)

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_root_cause_in_json(self, mock_run, mock_which):
        """Root causes appear in JSON output."""
        mock_run.side_effect = self._mock_droid_response

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        js = render_audit_json(result)
        parsed = json.loads(js)
        self.assertIn("root_causes", parsed)
        self.assertGreater(len(parsed["root_causes"]), 0)
        self.assertTrue(parsed["root_causes"][0]["cause"])

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_root_cause_in_text(self, mock_run, mock_which):
        """Root causes appear in text output."""
        mock_run.side_effect = self._mock_droid_response

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        text = render_audit_text(result)
        self.assertIn("Root cause analysis:", text)
        self.assertIn("upstream fix:", text)

    @patch("revgate.audit.shutil.which", return_value="/usr/local/bin/droid")
    @patch("revgate.audit.subprocess.run")
    def test_agent_sessions_includes_root_cause(self, mock_run, mock_which):
        """agent_sessions count includes the root cause session."""
        mock_run.side_effect = self._mock_droid_response

        result = audit(FIXTURES / "leads-dirty.csv", self.cfg, use_droid=True)
        # agent_sessions = review sessions + root cause session + synthesis session
        expected = len(result.agent_reviews) + 1 + 1  # reviews + root cause + synthesis
        self.assertEqual(result.agent_sessions, expected)


if __name__ == "__main__":
    unittest.main()
