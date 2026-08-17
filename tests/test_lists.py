"""The twenty-two gates, exercised against the shipped fixtures.

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
        # L018 is a source-level gate: it inspects the DNC source file's
        # modification time, not any row in the lead list, so no row in the
        # fixture can trip it. It is exercised separately by
        # test_dnc_staleness_fires_with_zero_threshold.
        row_level_rules = {r.id for r in RULES if r.id != "L018"}
        never_fired = sorted(row_level_rules - fired)
        self.assertEqual(
            never_fired, [],
            f"gates with no exercising row in the dirty fixture: {never_fired}",
        )

    def test_dnc_staleness_fires_with_zero_threshold(self):
        """L018 is a source-level gate, not a row-level gate. Test it separately."""
        cfg = Config.load(REPO / "revgate.toml")
        # Pin today beyond the DNC file's mtime so a zero-day threshold must
        # fire regardless of when the fixture was last touched.
        cfg = cfg.with_overrides(dnc_stale_days=0, today=date(2027, 1, 1))
        result = runner.run(CLEAN, cfg, only=["L018"])
        l018_findings = [f for f in result.findings if f.rule == "L018"]
        self.assertGreater(len(l018_findings), 0)

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

    def test_unconfigured_p0_source_blocks(self):
        # C1 fix: a P0 gate that cannot run because no source is configured
        # must block, not silently pass.
        cfg = Config(root=REPO, today=TODAY)
        result = runner.run(CLEAN, cfg)
        skips = {s.rule: s for s in result.skipped}
        self.assertIn("L001", skips)
        self.assertTrue(skips["L001"].blocking)
        self.assertEqual(result.exit_code(), EXIT_BLOCKED)

    def test_acknowledged_unconfigured_source_skips_non_blocking(self):
        # When the operator explicitly acknowledges an unconfigured gate,
        # it skips non-blocking instead of blocking.
        cfg = Config(root=REPO, today=TODAY, acknowledge_unconfigured=("L001", "L003", "L018"))
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


class CopyGateSeverity(unittest.TestCase):
    """M10: L006 raw dates/numbers are P1, merge fields are P0."""

    def test_raw_date_is_p1_not_p0(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        tmp.write("Company,Domain,copy\nAcme,acme.com,Meeting on 2026-01-15\n")
        tmp.close()
        try:
            result = runner.run(Path(tmp.name), config())
            l006 = [f for f in result.findings if f.rule == "L006"]
            self.assertTrue(l006, "L006 should fire on raw date")
            self.assertEqual(l006[0].severity, Severity.P1, "raw date should be P1")
        finally:
            Path(tmp.name).unlink()

    def test_merge_field_is_p0(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        tmp.write("Company,Domain,copy\nAcme,acme.com,Hi {{first_name}}\n")
        tmp.close()
        try:
            result = runner.run(Path(tmp.name), config())
            l006 = [f for f in result.findings if f.rule == "L006"]
            self.assertTrue(l006, "L006 should fire on merge field")
            self.assertEqual(l006[0].severity, Severity.P0, "merge field should be P0")
        finally:
            Path(tmp.name).unlink()

    def test_same_value_in_trigger_and_copy_is_one_finding(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        tmp.write("Company,Domain,trigger,copy\nAcme,acme.com,{{first_name}},Hi {{first_name}}\n")
        tmp.close()
        try:
            result = runner.run(Path(tmp.name), config())
            l006 = [f for f in result.findings if f.rule == "L006"]
            self.assertEqual(len(l006), 1, "same value in trigger and copy = one finding")
        finally:
            Path(tmp.name).unlink()


class MultipleCTAsOverlap(unittest.TestCase):
    """M11: L022 must not double-count overlapping CTA matches."""

    def test_overlapping_ctas_count_as_one(self):
        # "let's chat" and "let's talk" overlap in "let's chat or talk"
        tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        tmp.write("Company,Domain,copy\nAcme,acme.com,let's chat or talk\n")
        tmp.close()
        try:
            result = runner.run(Path(tmp.name), config())
            l022 = [f for f in result.findings if f.rule == "L022"]
            self.assertEqual(len(l022), 0, "overlapping CTAs should count as one, not multiple")
        finally:
            Path(tmp.name).unlink()

    def test_distinct_ctas_still_fire(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        tmp.write("Company,Domain,copy\nAcme,acme.com,Schedule a call. Reply to learn more.\n")
        tmp.close()
        try:
            result = runner.run(Path(tmp.name), config())
            l022 = [f for f in result.findings if f.rule == "L022"]
            self.assertTrue(l022, "two distinct CTAs should fire L022")
        finally:
            Path(tmp.name).unlink()


class CleanInputPerGate(unittest.TestCase):
    """G5: each gate must NOT fire on clean input that should pass it.

    Table-driven, like PipedExitCodes. Each case provides a row that is clean
    for exactly one gate, and asserts that gate produces no finding.
    """

    CLEAN_CASES = [
        # (rule_id, csv_header, csv_row)
        ("L001", "company,domain,email\n", "Acme,acme.com,bob@acme.com\n"),
        ("L002", "company,domain,email,last_contacted\n",
         "Acme,acme.com,bob@acme.com,2026-01-01\n"),
        ("L003", "company,domain,email,phone\n",
         "Acme,acme.com,bob@acme.com,4155550142\n"),
        ("L004", "company,domain,email,state\n",
         "Acme,acme.com,bob@acme.com,CA\n"),
        ("L005", "company,domain,email,trigger\n",
         "Acme,acme.com,bob@acme.com,opened a new DC in Reno\n"),
        ("L006", "company,domain,email,copy\n",
         "Acme,acme.com,bob@acme.com,Saw the new DC. Worth a call?\n"),
        ("L007", "company,domain,email,email_status\n",
         "Acme,acme.com,bob@acme.com,verified\n"),
        ("L008", "company,domain,email\n",
         "Acme,acme.com,bob@acme.com\n"),
        ("L009", "company,domain,email\n",
         "Acme Corp,acme.com,bob@acme.com\n"),
        ("L010", "company,domain,email\n",
         "Acme Corp,acme.com,bob@acme.com\n"),
        ("L011", "company,domain,email,headcount\n",
         "Acme,acme.com,bob@acme.com,50\n"),
        # L012 needs 20+ rows with a distribution that includes
        # companies below the headcount floor (default 5). A single
        # row would skip, not pass. Covered by the built fixture below.
        # ("L012", ...) — see test_l012_clean_distribution_passes
        ("L013", "company,domain,email\n",
         "Acme,acme.com,bob@acme.com\n"),
        ("L014", "company,domain,email,phone\n",
         "Acme,acme.com,bob@acme.com,4155550142\n"),
        ("L015", "company,domain,email,enriched_date\n",
         "Acme,acme.com,bob@acme.com,2026-07-01\n"),
        ("L016", "company,domain,email,first_name,last_name\n",
         "Acme,acme.com,bob@acme.com,Bob,Smith\n"),
        ("L017", "company,domain,email,title\n",
         "Acme,acme.com,bob@acme.com,VP of Operations\n"),
        ("L018", "company,domain,email,phone\n",
         "Acme,acme.com,bob@acme.com,4155550142\n"),
        ("L019", "company,domain,email,state,send_time\n",
         "Acme,acme.com,bob@acme.com,NY,10:00 AM\n"),
        ("L020", "company,domain,email,copy\n",
         "Acme,acme.com,bob@acme.com,Saw the DC news. Worth a call?\n"),
        ("L021", "company,domain,email,copy\n",
         "Acme,acme.com,bob@acme.com,Saw the DC news. Worth a call?\n"),
        ("L022", "company,domain,email,copy\n",
         "Acme,acme.com,bob@acme.com,Saw the DC news. Worth a call?\n"),
    ]

    def test_clean_input_does_not_trip_gate(self):
        for rule_id, header, row in self.CLEAN_CASES:
            with self.subTest(rule=rule_id):
                tmp = tempfile.NamedTemporaryFile(
                    "w", suffix=".csv", delete=False, encoding="utf-8")
                tmp.write(header + row)
                tmp.close()
                try:
                    result = runner.run(Path(tmp.name), config())
                    skipped_rules = {s.rule for s in result.skipped}
                    # A gate that silently skips instead of evaluating is not
                    # the same as a gate that passes. This catches the case
                    # where a clean row trips nothing because the gate never
                    # ran, not because the input was clean.
                    self.assertNotIn(
                        rule_id, skipped_rules,
                        f"{rule_id} skipped on input that should have been "
                        f"evaluated: { {s.reason for s in result.skipped if s.rule == rule_id} }",
                    )
                    findings = [f for f in result.findings if f.rule == rule_id]
                    self.assertEqual(
                        findings, [],
                        f"{rule_id} fired on clean input: "
                        + ", ".join(f.detail for f in findings),
                    )
                finally:
                    Path(tmp.name).unlink()

    def test_l012_clean_distribution_passes(self):
        """L012 needs 20+ rows with a headcount distribution that includes
        companies below the floor. A single row would skip, not pass."""
        rows = []
        for i in range(25):
            hc = 3 if i == 0 else 50 + i * 10  # one small company, rest grow
            rows.append(f"Co{i},co{i}.com,ops@co{i}.com,{hc}")
        csv_text = "company,domain,email,headcount\n" + "\n".join(rows) + "\n"
        tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        tmp.write(csv_text)
        tmp.close()
        try:
            result = runner.run(Path(tmp.name), config())
            skipped_rules = {s.rule for s in result.skipped}
            self.assertNotIn("L012", skipped_rules, "L012 should have run, not skipped")
            l012 = [f for f in result.findings if f.rule == "L012"]
            self.assertEqual(l012, [], "L012 should not fire when the floor is represented")
        finally:
            Path(tmp.name).unlink()


if __name__ == "__main__":
    unittest.main()
