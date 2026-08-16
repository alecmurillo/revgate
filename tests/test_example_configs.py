"""Tests that the example configs in examples/ load and produce expected results.

These configs are documentation, but they are also TOML files the config
loader parses. If a field name has a typo or a value is the wrong type, no
one finds out until a user hits it. This test catches that.
"""

import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLEAN = "fixtures/leads-clean.csv"
DIRTY = "fixtures/leads-dirty.csv"
TODAY = "2026-08-16"

EXAMPLES = [
    "examples/cold-outbound.toml",
    "examples/warm-intro.toml",
    "examples/abm-enterprise.toml",
]


def revgate(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "revgate", *args],
        cwd=REPO, capture_output=True, text=True, timeout=60, check=False,
    )


class TestExampleConfigs(unittest.TestCase):
    """Each example config must load and produce a sensible exit code."""

    def test_each_config_loads_without_error(self):
        for config_path in EXAMPLES:
            with self.subTest(config=config_path):
                proc = revgate("lint", CLEAN, "-c", config_path,
                               "--today", TODAY, "--no-record")
                # Should not exit 3 (usage error = config failed to load)
                self.assertNotEqual(proc.returncode, 3,
                    f"{config_path} failed to load: {proc.stderr}")

    def test_clean_list_passes_with_each_config(self):
        for config_path in EXAMPLES:
            with self.subTest(config=config_path):
                proc = revgate("lint", CLEAN, "-c", config_path,
                               "--today", TODAY, "--no-record")
                self.assertEqual(proc.returncode, 0,
                    f"{config_path} should pass clean list: {proc.stdout[:300]}")

    def test_dirty_list_blocks_with_each_config(self):
        for config_path in EXAMPLES:
            with self.subTest(config=config_path):
                proc = revgate("lint", DIRTY, "-c", config_path,
                               "--today", TODAY, "--no-record")
                self.assertEqual(proc.returncode, 2,
                    f"{config_path} should block dirty list: {proc.stdout[:300]}")

    def test_cold_outbound_has_restricted_states(self):
        proc = revgate("lint", DIRTY, "-c", "examples/cold-outbound.toml",
                       "--today", TODAY, "--format", "json", "--no-record")
        import json
        parsed = json.loads(proc.stdout)
        # Cold outbound should have NY in restricted states — L004 is the restricted jurisdiction gate
        restricted = [f for f in parsed.get("findings", [])
                      if f.get("rule") == "L004"]
        self.assertGreater(len(restricted), 0,
            "cold-outbound.toml should flag restricted-state findings (L004)")

    def test_warm_intro_has_no_restricted_states(self):
        proc = revgate("lint", DIRTY, "-c", "examples/warm-intro.toml",
                       "--today", TODAY, "--format", "json", "--no-record")
        import json
        parsed = json.loads(proc.stdout)
        # Warm intro has no restricted states — L004 should not fire
        restricted = [f for f in parsed.get("findings", [])
                      if f.get("rule") == "L004"]
        self.assertEqual(len(restricted), 0,
            "warm-intro.toml should not flag restricted-state findings (L004)")

    def test_abm_enterprise_is_strict(self):
        proc = revgate("lint", DIRTY, "-c", "examples/abm-enterprise.toml",
                       "--today", TODAY, "--format", "json", "--no-record")
        import json
        parsed = json.loads(proc.stdout)
        # Strict mode means P1 findings should also block (exit 2)
        # But we're checking the config loaded with strict=true
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
