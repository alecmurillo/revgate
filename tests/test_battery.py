"""Battery loading, and the shipped battery's own invariants.

The loader is strict on purpose. A scenario that asserts nothing can never fail, so
loading one quietly would add a green line to every report forever.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from revgate.agents.battery import Battery
from revgate.core.findings import Severity

REPO = Path(__file__).resolve().parents[1]
SHIPPED = REPO / "revgate" / "batteries" / "sales-intake.toml"


def battery_file(body: str) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8")
    tmp.write(textwrap.dedent(body))
    tmp.close()
    return Path(tmp.name)


class LoaderRejections(unittest.TestCase):
    def load(self, body: str):
        path = battery_file(body)
        try:
            return Battery.load(path)
        finally:
            path.unlink()

    def test_a_scenario_that_asserts_nothing_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            self.load("""
                name = "t"
                [[scenario]]
                id = "A1"
                turns = ["hello"]
            """)
        self.assertIn("asserts nothing", str(ctx.exception))

    def test_duplicate_ids_are_refused(self):
        with self.assertRaises(ValueError) as ctx:
            self.load("""
                name = "t"
                [[scenario]]
                id = "A1"
                turns = ["hi"]
                must_not_match = ["x"]
                [[scenario]]
                id = "A1"
                turns = ["hi"]
                must_not_match = ["y"]
            """)
        self.assertIn("duplicate", str(ctx.exception))

    def test_a_scenario_with_no_turns_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            self.load("""
                name = "t"
                [[scenario]]
                id = "A1"
                turns = []
                must_not_match = ["x"]
            """)
        self.assertIn("no turns", str(ctx.exception))

    def test_blank_turns_do_not_count_as_turns(self):
        with self.assertRaises(ValueError):
            self.load("""
                name = "t"
                [[scenario]]
                id = "A1"
                turns = ["  "]
                must_not_match = ["x"]
            """)

    def test_an_invalid_regex_fails_at_load_not_at_run(self):
        with self.assertRaises(ValueError) as ctx:
            self.load("""
                name = "t"
                [[scenario]]
                id = "A1"
                turns = ["hi"]
                must_not_match = ["([unclosed"]
            """)
        self.assertIn("invalid regex", str(ctx.exception))

    def test_a_battery_with_no_scenarios_is_refused(self):
        with self.assertRaises(ValueError):
            self.load('name = "t"\n')

    def test_a_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            Battery.load("/nonexistent/battery.toml")

    def test_semantic_alone_is_enough_to_be_a_valid_scenario(self):
        battery = self.load("""
            name = "t"
            [[scenario]]
            id = "A1"
            turns = ["hi"]
            semantic = "did the agent imply a guarantee"
        """)
        self.assertEqual(len(battery.scenarios), 1)
        self.assertFalse(battery.scenarios[0].has_pattern_assertions)


class Selection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.battery = Battery.load(SHIPPED)

    def test_select_by_id_is_case_insensitive(self):
        chosen = self.battery.select(only=["id1"])
        self.assertEqual([s.id for s in chosen], ["ID1"])

    def test_unknown_id_is_an_error(self):
        with self.assertRaises(ValueError):
            self.battery.select(only=["NOPE"])

    def test_priority_ceiling_includes_higher_priorities(self):
        chosen = self.battery.select(priority="P1")
        self.assertTrue(all(s.priority in (Severity.P0, Severity.P1) for s in chosen))
        self.assertTrue(any(s.priority is Severity.P0 for s in chosen))


class ShippedBattery(unittest.TestCase):
    """Invariants the bundled battery has to keep to stay meaningful."""

    @classmethod
    def setUpClass(cls):
        cls.battery = Battery.load(SHIPPED)

    def test_it_loads_and_is_not_trivial(self):
        self.assertGreaterEqual(len(self.battery.scenarios), 20)

    def test_every_scenario_explains_why_it_exists(self):
        for s in self.battery.scenarios:
            self.assertTrue(s.origin.strip(), f"{s.id} has no origin")
            self.assertTrue(s.title.strip(), f"{s.id} has no title")

    def test_there_is_a_control_group(self):
        controls = [s for s in self.battery.scenarios if "expected-pass" in s.tags]
        self.assertGreaterEqual(
            len(controls), 5,
            "without expected-pass controls a run cannot distinguish a working "
            "guardrail from an assertion that never matches",
        )

    def test_controls_assert_a_positive_shape_not_just_a_prohibition(self):
        for s in self.battery.scenarios:
            if "expected-pass" in s.tags:
                self.assertTrue(
                    s.must_match_any or s.must_match_all,
                    f"{s.id} is a control but only forbids things, so it would pass "
                    "against an agent that says nothing at all",
                )

    def test_persistence_scenarios_are_multi_turn(self):
        # A guardrail that holds once and yields on the re-ask cannot be detected
        # with a single turn.
        for sid in ("ID3", "OG1"):
            scenario = next(s for s in self.battery.scenarios if s.id == sid)
            self.assertGreaterEqual(len(scenario.turns), 2, f"{sid} needs a re-ask turn")

    def test_adversarial_scenarios_have_an_acceptable_way_out(self):
        for s in self.battery.scenarios:
            if "expected-pass" in s.tags or not s.must_not_match:
                continue
            self.assertTrue(
                s.must_match_any or s.must_match_all or s.semantic,
                f"{s.id} only forbids things; it cannot distinguish a safe answer "
                "from silence",
            )


if __name__ == "__main__":
    unittest.main()
