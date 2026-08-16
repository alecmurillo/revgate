"""The thirteen gates, exercised against the shipped fixtures.

Two assertions carry most of the weight:

- the dirty fixture must trip every gate, because a gate with no fixture row is an
  untested assertion;
- the clean fixture must trip none, because a linter that fires on clean data gets
  switched off and then catches nothing.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from revgate.core.config import Config
from revgate.core.findings import EXIT_BLOCKED, EXIT_OK, Severity
from revgate.lists import runner
from revgate.lists.rules import RULES, RULES_BY_ID

REPO = Path(__file__).resolve().parents[1]
DIRTY = REPO / "fixtures" / "leads-dirty.csv"
CLEAN = REPO / "fixtures" / "leads-clean.csv"

# The fixtures contain dates and one gate is about recency, so the reference date
# is pinned. Without this the suite would start failing on its own in a fortnight.
TODAY = date(2026, 8, 16)


def config(**overrides) -> Config:
    cfg = Config.load(REPO / "revgate.toml")
    return cfg.with_overrides(today=TODAY, **overrides)


class DirtyFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = runner.run(DIRTY, config())

    def test_run_is_blocked(self):
        self.assertEqual(self.result.exit_code(), EXIT_BLOCKED)
        self.assertEqual(self.result.verdict(), "BLOCKED")

    def test_every_gate_has_a_row_that_trips_it(self):
        fired = {f.rule for f in self.result.findings}
        never_fired = sorted({r.id for r in RULES} - fired)
        self.assertEqual(
            never_fired, [],
            f"gates with no exercising row in the dirty fixture: {never_fired}",
        )

    def test_nothing_was_skipped(self):
        # Every source the config names exists, so a skip here means a real defect.
        self.assertEqual([s.rule for s in self.result.skipped], [])

    def test_every_finding_carries_its_origin_and_remedy(self):
        for f in self.result.findings:
            self.assertTrue(f.remedy.strip(), f"{f.rule} has no remedy")
            # The finding-level origin has to name the mistake, not restate the rule,
            # and a restatement is almost always short.
            self.assertGreater(
                len(f.origin), 60,
                f"{f.rule} origin is too short to name a real mistake: {f.origin!r}",
            )

    def test_severities_match_the_declared_rule_severity(self):
        for f in self.result.findings:
            declared = RULES_BY_ID[f.rule].severity
            self.assertLessEqual(
                [Severity.P0, Severity.P1, Severity.P2].index(declared),
                [Severity.P0, Severity.P1, Severity.P2].index(f.severity),
                f"{f.rule} reported {f.severity.value} but declares {declared.value}",
            )

    def test_row_numbers_are_within_the_file(self):
        limit = self.result.stats["rows"] + 1
        for f in self.result.findings:
            if f.row is not None:
                self.assertGreaterEqual(f.row, 2)
                self.assertLessEqual(f.row, limit)

    def test_statutory_gates_actually_fired(self):
        fired = {f.rule for f in self.result.findings}
        for rule in ("L003", "L004"):  # do-not-call, restricted jurisdiction
            self.assertIn(rule, fired)


class CleanFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = runner.run(CLEAN, config())

    def test_clean_list_passes(self):
        self.assertEqual(
            self.result.findings, [],
            "the clean fixture tripped a gate: "
            + ", ".join(f"{f.rule} row {f.row}" for f in self.result.findings),
        )
        self.assertEqual(self.result.exit_code(), EXIT_OK)

    def test_clean_list_is_still_fully_checked(self):
        self.assertEqual(self.result.stats["gates skipped"], 0)
        self.assertEqual(self.result.stats["gates run"], len(RULES))

    def test_strict_mode_does_not_change_a_clean_verdict(self):
        self.assertEqual(self.result.exit_code(strict=True), EXIT_OK)


class FailClosedSources(unittest.TestCase):
    """A configured source that cannot be read must block, never pass quietly."""

    def test_missing_suppression_export_blocks(self):
        cfg = config(suppression=REPO / "does-not-exist.csv")
        result = runner.run(CLEAN, cfg)
        skips = {s.rule: s for s in result.skipped}
        self.assertIn("L001", skips)
        self.assertTrue(skips["L001"].blocking)
        self.assertEqual(
            result.exit_code(), EXIT_BLOCKED,
            "a clean list checked against a missing suppression source is not clean",
        )

    def test_empty_suppression_export_blocks_too(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        tmp.write("Domain\n")  # headers, no rows
        tmp.close()
        try:
            result = runner.run(CLEAN, config(suppression=Path(tmp.name)))
            skips = {s.rule: s for s in result.skipped}
            self.assertIn("L001", skips)
            self.assertTrue(
                skips["L001"].blocking,
                "an empty export would let every row pass unchecked",
            )
        finally:
            Path(tmp.name).unlink()

    def test_unconfigured_source_skips_without_blocking(self):
        # Nothing was promised, so nothing was broken. Reported, not fatal.
        cfg = Config(root=REPO, today=TODAY)
        result = runner.run(CLEAN, cfg)
        skips = {s.rule: s for s in result.skipped}
        self.assertIn("L001", skips)
        self.assertFalse(skips["L001"].blocking)
        self.assertEqual(result.exit_code(), EXIT_OK)


class MissingColumns(unittest.TestCase):
    def test_gates_skip_rather_than_evaluate_empty_strings(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        tmp.write("Company,Domain\nAcme Inc,acme.com\n")
        tmp.close()
        try:
            result = runner.run(Path(tmp.name), config())
            skipped = {s.rule for s in result.skipped}
            # No phone column, so the do-not-call gate cannot run and says so.
            self.assertIn("L003", skipped)
            self.assertEqual(result.stats["gates skipped"], len(skipped))
        finally:
            Path(tmp.name).unlink()

    def test_empty_file_is_called_out_explicitly(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        tmp.write("Company,Domain,Email\n")
        tmp.close()
        try:
            result = runner.run(Path(tmp.name), config())
            self.assertTrue(
                any("zero data rows" in n for n in result.notes),
                "an empty list passes every gate, which must be stated rather than implied",
            )
        finally:
            Path(tmp.name).unlink()


class RuleSelection(unittest.TestCase):
    def test_subset_selection(self):
        result = runner.run(DIRTY, config(), only=["L003"])
        self.assertEqual({f.rule for f in result.findings}, {"L003"})

    def test_unknown_rule_is_an_error_not_a_silent_no_op(self):
        with self.assertRaises(ValueError):
            runner.select_rules(["L999"])

    def test_rules_are_uniquely_identified(self):
        ids = [r.id for r in RULES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_rule_declares_why_it_exists(self):
        # Rule.origin is the one-line headline printed by `revgate rules`. The full
        # explanation lives on the Finding, and is length-checked separately.
        for rule in RULES:
            self.assertTrue(rule.origin.strip(), f"{rule.id} has no origin")
            self.assertTrue(rule.summary.strip(), f"{rule.id} has no summary")
            # A headline can be terse; it still has to be a sentence rather than a
            # label, because a label is what a restatement looks like.
            self.assertIn(" ", rule.origin, f"{rule.id} origin is a label, not a reason")
            self.assertTrue(
                rule.origin.rstrip().endswith("."),
                f"{rule.id} origin is not written as a sentence: {rule.origin!r}",
            )


if __name__ == "__main__":
    unittest.main()
