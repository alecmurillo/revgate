"""The exit-code policy. Every CI integration depends on these being exactly right."""

from __future__ import annotations

import unittest

from revgate.core.findings import (
    EXIT_ADVISORY,
    EXIT_BLOCKED,
    EXIT_OK,
    Finding,
    Result,
    Severity,
    Skipped,
    group_findings,
)


def finding(rule: str = "L001", severity: Severity = Severity.P0, title: str = "t") -> Finding:
    return Finding(
        rule=rule, severity=severity, title=title,
        detail="d", remedy="r", origin="o",
    )


class SeverityPolicy(unittest.TestCase):
    def test_only_p0_blocks(self):
        self.assertTrue(Severity.P0.blocking)
        self.assertFalse(Severity.P1.blocking)
        self.assertFalse(Severity.P2.blocking)

    def test_parse_is_forgiving_about_case_and_whitespace(self):
        self.assertIs(Severity.parse(" p0 "), Severity.P0)

    def test_parse_rejects_nonsense(self):
        with self.assertRaises(ValueError):
            Severity.parse("critical")


class ExitCodes(unittest.TestCase):
    def result(self, **kwargs) -> Result:
        return Result(surface="lists", target="x", **kwargs)

    def test_clean_run_exits_zero(self):
        self.assertEqual(self.result().exit_code(), EXIT_OK)

    def test_one_p0_blocks(self):
        r = self.result(findings=[finding(severity=Severity.P0)])
        self.assertEqual(r.exit_code(), EXIT_BLOCKED)
        self.assertEqual(r.verdict(), "BLOCKED")

    def test_volume_of_advisories_never_blocks(self):
        r = self.result(findings=[finding(severity=Severity.P2) for _ in range(500)])
        self.assertEqual(r.exit_code(), EXIT_OK, "count must never decide the exit code")

    def test_strict_promotes_p1_only(self):
        r = self.result(findings=[finding(severity=Severity.P1)])
        self.assertEqual(r.exit_code(strict=False), EXIT_OK)
        self.assertEqual(r.exit_code(strict=True), EXIT_ADVISORY)

    def test_strict_does_not_promote_p2(self):
        r = self.result(findings=[finding(severity=Severity.P2)])
        self.assertEqual(r.exit_code(strict=True), EXIT_OK)

    # The invariant the whole project exists for.
    def test_blocking_skip_alone_blocks_the_run(self):
        r = self.result(skipped=[Skipped("L001", "suppression export missing", blocking=True)])
        self.assertEqual(r.findings, [])
        self.assertEqual(
            r.exit_code(), EXIT_BLOCKED,
            "a configured check that could not run must not report a pass",
        )

    def test_non_blocking_skip_does_not_block(self):
        r = self.result(skipped=[Skipped("L002", "no last-contacted column", blocking=False)])
        self.assertEqual(r.exit_code(), EXIT_OK)

    def test_blocking_skips_are_isolated(self):
        r = self.result(skipped=[
            Skipped("L001", "a", blocking=True),
            Skipped("L002", "b", blocking=False),
        ])
        self.assertEqual([s.rule for s in r.blocking_skips], ["L001"])


class Counting(unittest.TestCase):
    def test_counts_every_severity_key_even_at_zero(self):
        r = Result(surface="lists", target="x", findings=[finding(severity=Severity.P1)])
        self.assertEqual(r.counts(), {"P0": 0, "P1": 1, "P2": 0})

    def test_serialisation_carries_verdict_and_exit_code(self):
        r = Result(surface="lists", target="x", findings=[finding()])
        payload = r.to_dict()
        self.assertEqual(payload["verdict"], "BLOCKED")
        self.assertEqual(payload["exit_code"], EXIT_BLOCKED)
        self.assertEqual(payload["findings"][0]["origin"], "o")


class Grouping(unittest.TestCase):
    def test_same_rule_different_titles_do_not_collapse(self):
        # One gate reporting three different defects must not present as one.
        items = [
            finding(rule="L006", title="unrendered placeholder"),
            finding(rule="L006", title="raw timestamp"),
            finding(rule="L006", title="raw timestamp"),
        ]
        grouped = group_findings(items)
        self.assertEqual(len(grouped), 2)
        self.assertEqual({title for _, title, _ in grouped},
                         {"unrendered placeholder", "raw timestamp"})

    def test_p0_groups_sort_first(self):
        grouped = group_findings([
            finding(rule="L012", severity=Severity.P2, title="floor"),
            finding(rule="L003", severity=Severity.P0, title="dnc"),
        ])
        self.assertEqual(grouped[0][0], "L003")


if __name__ == "__main__":
    unittest.main()
