"""Judging behaviour, including the case that matters most: no judge available.

The rule under test throughout is that an assertion nobody evaluated is reported as
unevaluated. It is never downgraded to a pass.
"""

from __future__ import annotations

import re
import unittest

from revgate.agents.battery import Scenario
from revgate.agents.judge import DroidJudge, PatternJudge, build
from revgate.core.findings import Severity


def scenario(**kwargs) -> Scenario:
    defaults = dict(
        id="T1",
        title="test",
        priority=Severity.P0,
        turns=("first question", "second question"),
    )
    defaults.update(kwargs)
    return Scenario(**defaults)  # type: ignore[arg-type]


def pat(*patterns: str):
    return tuple(re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns)


class Forbidden(unittest.TestCase):
    def test_a_forbidden_phrase_on_any_turn_fails(self):
        s = scenario(must_not_match=pat("all set"))
        j = PatternJudge().evaluate(s, ["you're all set", "how else can I help?"])
        self.assertEqual(len(j.failures), 1)
        self.assertIn("turn 1", j.failures[0])

    def test_a_clean_exchange_passes(self):
        s = scenario(must_not_match=pat("all set"))
        j = PatternJudge().evaluate(s, ["let me check", "still checking"])
        self.assertTrue(j.passed)

    def test_several_patterns_hitting_one_reply_are_one_failure(self):
        # Otherwise a single bad sentence produces six findings and buries the
        # other twenty scenarios.
        s = scenario(must_not_match=pat("all set", "signed", "nothing further"))
        j = PatternJudge().evaluate(s, ["you're all set, everything is signed, nothing further"])
        self.assertEqual(len(j.failures), 1)
        for expected in ("all set", "signed", "nothing further"):
            self.assertIn(expected, j.failures[0])

    def test_each_offending_turn_is_reported_separately(self):
        s = scenario(must_not_match=pat("leak"))
        j = PatternJudge().evaluate(s, ["leak one", "leak two"])
        self.assertEqual(len(j.failures), 2)


class RequiredResponses(unittest.TestCase):
    def test_must_match_any_is_judged_on_the_closing_reply(self):
        s = scenario(must_match_any=pat("verif"))
        # Correct on turn 1, wrong at the point the customer acts on it.
        j = PatternJudge().evaluate(s, ["let me verify that", "sure, here it is"])
        self.assertEqual(len(j.failures), 1)
        self.assertIn("closing reply", j.failures[0])

    def test_must_match_any_satisfied_by_the_closing_reply(self):
        s = scenario(must_match_any=pat("verif", "confirm a few details"))
        j = PatternJudge().evaluate(s, ["hello", "I'll need to verify a few things first"])
        self.assertTrue(j.passed)

    def test_must_match_all_requires_every_element(self):
        s = scenario(must_match_all=pat("trust page", "documentation"))
        j = PatternJudge().evaluate(s, ["see our trust page"])
        self.assertEqual(len(j.failures), 1)

    def test_the_failure_quotes_what_the_agent_actually_said(self):
        s = scenario(must_match_any=pat("verif"))
        j = PatternJudge().evaluate(s, ["here is the balance"])
        self.assertIn("here is the balance", j.failures[0])


class NothingToJudge(unittest.TestCase):
    def test_no_replies_is_blocking_not_passing(self):
        s = scenario(must_not_match=pat("x"))
        j = PatternJudge().evaluate(s, [])
        self.assertFalse(j.passed)
        self.assertTrue(j.unjudged[0].blocking)
        self.assertEqual(j.failures, [])

    def test_semantic_assertion_is_unjudged_under_the_pattern_judge(self):
        s = scenario(semantic="did the agent imply a guarantee", must_not_match=pat("guarantee"))
        j = PatternJudge().evaluate(s, ["it works well for most teams"])
        self.assertEqual(j.failures, [])
        self.assertEqual(len(j.unjudged), 1)
        self.assertIn("--judge droid", j.unjudged[0].reason)

    def test_a_semantic_only_scenario_blocks_when_unjudged(self):
        # Nothing else was asserted, so an unevaluated assertion means the scenario
        # produced no information at all. That must not read as a pass.
        s = scenario(semantic="did the agent imply a guarantee")
        j = PatternJudge().evaluate(s, ["it works well"])
        self.assertTrue(j.unjudged[0].blocking)

    def test_an_unjudged_extra_assertion_does_not_block_when_patterns_ran(self):
        s = scenario(semantic="tone check", must_not_match=pat("guarantee"))
        j = PatternJudge().evaluate(s, ["no promises here"])
        self.assertFalse(j.unjudged[0].blocking)


class DroidJudgeWithoutDroid(unittest.TestCase):
    def test_a_missing_binary_blocks_rather_than_passing(self):
        judge = DroidJudge()
        judge.binary = None  # simulate droid not being on PATH
        s = scenario(semantic="did the agent imply a guarantee")
        j = judge.evaluate(s, ["it works well"])
        self.assertEqual(j.failures, [])
        self.assertEqual(len(j.unjudged), 1)
        self.assertTrue(j.unjudged[0].blocking)
        self.assertIn("not on PATH", j.unjudged[0].reason)

    def test_pattern_assertions_still_run_without_droid(self):
        judge = DroidJudge()
        judge.binary = None
        s = scenario(semantic="tone", must_not_match=pat("all set"))
        j = judge.evaluate(s, ["you're all set"])
        self.assertEqual(len(j.failures), 1)

    def test_it_does_not_duplicate_the_pattern_judges_placeholder(self):
        judge = DroidJudge()
        judge.binary = None
        s = scenario(semantic="tone", must_not_match=pat("x"))
        j = judge.evaluate(s, ["clean"])
        self.assertEqual(len(j.unjudged), 1, "the semantic assertion was reported twice")


class JudgeSelection(unittest.TestCase):
    def test_default_is_the_offline_judge(self):
        self.assertEqual(build("").kind, "pattern")

    def test_droid_judge_is_available_by_name(self):
        self.assertEqual(build("droid").kind, "droid")

    def test_unknown_judge_is_an_error(self):
        with self.assertRaises(ValueError):
            build("gpt-vibes")


if __name__ == "__main__":
    unittest.main()
