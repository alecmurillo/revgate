"""Provenance verification.

Two things need proving. First, that the verifier catches broken claims, because a
verifier that always passes is a rubber stamp and worse than nothing. Second, that
this repository's own manifest currently holds.
"""

from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from revgate.core.config import Config
from revgate.core.findings import EXIT_BLOCKED, EXIT_OK, Severity
from revgate.provenance import parse_frontmatter, record_run, summarize_runs, verify
from revgate.core.findings import Result

REPO = Path(__file__).resolve().parents[1]


class Frontmatter(unittest.TestCase):
    def test_scalars_and_inline_arrays(self):
        meta, body = parse_frontmatter(textwrap.dedent("""\
            ---
            name: my-skill
            description: Does a thing: with a colon in it
            tools: [Read, Grep, Execute]
            ---
            The body.
            """))
        self.assertEqual(meta["name"], "my-skill")
        self.assertEqual(meta["description"], "Does a thing: with a colon in it")
        self.assertEqual(meta["tools"], ["Read", "Grep", "Execute"])
        self.assertEqual(body.strip(), "The body.")

    def test_block_lists(self):
        meta, _ = parse_frontmatter("---\ntools:\n  - Read\n  - Grep\n---\nbody\n")
        self.assertEqual(meta["tools"], ["Read", "Grep"])

    def test_quotes_are_stripped(self):
        meta, _ = parse_frontmatter('---\nname: "quoted"\n---\nbody\n')
        self.assertEqual(meta["name"], "quoted")

    def test_no_frontmatter_returns_the_whole_text(self):
        meta, body = parse_frontmatter("just a document\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "just a document\n")

    def test_unterminated_frontmatter_is_not_parsed(self):
        meta, _ = parse_frontmatter("---\nname: x\nno closing fence\n")
        self.assertEqual(meta, {})


class TempRepo:
    """A throwaway repository with a manifest, for negative tests."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp())

    def write(self, relative: str, text: str) -> Path:
        path = self.dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        return path

    def manifest(self, body: str) -> None:
        self.write("factory-usage.toml", body)

    def config(self) -> Config:
        return Config(
            root=self.dir,
            manifest=self.dir / "factory-usage.toml",
            runs_dir=self.dir / ".revgate" / "runs",
        )

    def verify(self) -> Result:
        return verify(self.config())

    def cleanup(self) -> None:
        import shutil

        shutil.rmtree(self.dir, ignore_errors=True)


class CatchesBrokenClaims(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()

    def tearDown(self):
        self.repo.cleanup()

    def test_no_manifest_is_a_blocking_skip_not_a_pass(self):
        cfg = Config(root=self.repo.dir, manifest=self.repo.dir / "factory-usage.toml")
        result = verify(cfg)
        self.assertTrue(result.skipped[0].blocking)
        self.assertEqual(result.exit_code(), EXIT_BLOCKED)

    def test_a_claim_pointing_at_a_missing_file_fails(self):
        self.repo.manifest("""
            [[surface]]
            id = "X1"
            surface = "skill"
            path = ".factory/skills/ghost/SKILL.md"
            check = "skill"
        """)
        result = self.repo.verify()
        self.assertEqual(result.exit_code(), EXIT_BLOCKED)
        self.assertIn("does not exist", result.findings[0].detail)

    def test_a_manifest_entry_missing_required_keys_is_a_blocking_skip(self):
        self.repo.manifest("""
            [[surface]]
            id = "X1"
            surface = "skill"
        """)
        result = self.repo.verify()
        self.assertTrue(result.skipped[0].blocking)

    def test_a_skill_without_a_description_fails(self):
        self.repo.write(".factory/skills/thing/SKILL.md", """\
            ---
            name: thing
            ---
            Body.
            """)
        self.repo.manifest("""
            [[surface]]
            id = "X1"
            surface = "skill"
            path = ".factory/skills/thing/SKILL.md"
            check = "skill"
        """)
        result = self.repo.verify()
        self.assertTrue(any("description" in f.detail for f in result.findings))

    def test_a_skill_with_an_empty_body_fails(self):
        self.repo.write(".factory/skills/thing/SKILL.md", """\
            ---
            name: thing
            description: does a thing
            ---
            """)
        self.repo.manifest("""
            [[surface]]
            id = "X1"
            surface = "skill"
            path = ".factory/skills/thing/SKILL.md"
            check = "skill"
        """)
        result = self.repo.verify()
        self.assertTrue(any("body is empty" in f.detail for f in result.findings))

    def test_a_skill_name_that_does_not_match_its_directory_is_flagged(self):
        self.repo.write(".factory/skills/thing/SKILL.md", """\
            ---
            name: something-else
            description: does a thing
            ---
            Body.
            """)
        self.repo.manifest("""
            [[surface]]
            id = "X1"
            surface = "skill"
            path = ".factory/skills/thing/SKILL.md"
            check = "skill"
        """)
        result = self.repo.verify()
        self.assertTrue(any("does not match its directory" in f.detail for f in result.findings))

    def test_tools_all_is_rejected(self):
        self.repo.write(".factory/droids/r.md", """\
            ---
            name: r
            description: reviewer
            tools: all
            ---
            Prompt.
            """)
        self.repo.manifest("""
            [[surface]]
            id = "X1"
            surface = "droid"
            path = ".factory/droids/r.md"
            check = "droid"
        """)
        result = self.repo.verify()
        self.assertTrue(any("tools: all" in f.detail for f in result.findings))

    def test_a_forbidden_tool_is_rejected(self):
        self.repo.write(".factory/droids/r.md", """\
            ---
            name: r
            description: reviewer
            tools: [Read, ExitSpecMode]
            ---
            Prompt.
            """)
        self.repo.manifest("""
            [[surface]]
            id = "X1"
            surface = "droid"
            path = ".factory/droids/r.md"
            check = "droid"
        """)
        result = self.repo.verify()
        self.assertTrue(any("ExitSpecMode" in f.detail for f in result.findings))

    def test_an_unknown_hook_event_is_rejected(self):
        self.repo.write(".factory/hooks.json", json.dumps({
            "hooks": {"OnCommit": [{"matcher": "Execute", "hooks": [
                {"type": "command", "command": "true"}]}]}
        }))
        self.repo.manifest("""
            [[surface]]
            id = "X1"
            surface = "hooks"
            path = ".factory/hooks.json"
            check = "hooks"
        """)
        result = self.repo.verify()
        self.assertTrue(
            any("never fire" in f.detail for f in result.findings),
            "a hook registered on a non-existent event silently does nothing",
        )

    def test_a_missing_expected_marker_fails(self):
        self.repo.write(".github/workflows/ci.yml", "jobs:\n  test:\n    runs-on: ubuntu-latest\n")
        self.repo.manifest("""
            [[surface]]
            id = "X1"
            surface = "workflow"
            path = ".github/workflows/ci.yml"
            check = "workflow"
            expect = ["droid exec"]
        """)
        result = self.repo.verify()
        self.assertTrue(any("expected marker" in f.detail for f in result.findings))

    def test_an_undocumented_surface_is_flagged(self):
        self.repo.write(".factory/droids/undocumented.md", "---\nname: undocumented\n---\nx\n")
        self.repo.write(".factory/skills/thing/SKILL.md", """\
            ---
            name: thing
            description: does a thing
            ---
            Body.
            """)
        self.repo.manifest("""
            [[surface]]
            id = "X1"
            surface = "skill"
            path = ".factory/skills/thing/SKILL.md"
            check = "skill"
        """)
        result = self.repo.verify()
        undocumented = [f for f in result.findings if f.rule == "undocumented"]
        self.assertEqual(len(undocumented), 1)
        self.assertEqual(undocumented[0].severity, Severity.P1)
        self.assertIn("undocumented.md", undocumented[0].detail)

    def test_an_unknown_check_type_is_reported(self):
        self.repo.write("thing.txt", "x")
        self.repo.manifest("""
            [[surface]]
            id = "X1"
            surface = "code"
            path = "thing.txt"
            check = "vibes"
        """)
        result = self.repo.verify()
        self.assertTrue(any("unknown check" in f.detail for f in result.findings))


class ThisRepository(unittest.TestCase):
    """The manifest in this repo has to actually hold, or the README is lying."""

    @classmethod
    def setUpClass(cls):
        cls.result = verify(Config.load(REPO / "revgate.toml"))

    def test_it_verifies_cleanly(self):
        detail = "\n".join(f"{f.rule}: {f.detail}" for f in self.result.findings)
        self.assertEqual(self.result.exit_code(), EXIT_OK, detail)

    def test_nothing_is_undocumented(self):
        undocumented = [f.detail for f in self.result.findings if f.rule == "undocumented"]
        self.assertEqual(undocumented, [])

    def test_it_claims_a_real_number_of_surfaces(self):
        self.assertGreaterEqual(self.result.stats["claims"], 8)

    def test_every_claim_explains_itself(self):
        from revgate.provenance import describe

        for claim in describe(Config.load(REPO / "revgate.toml")):
            self.assertTrue(claim.does.strip(), f"{claim.id} does not say what it does")
            self.assertTrue(claim.novel.strip(), f"{claim.id} makes no novelty statement")


class RunHistory(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()

    def tearDown(self):
        self.repo.cleanup()

    def test_a_run_is_recorded_and_summarised(self):
        cfg = self.repo.config()
        result = Result(surface="agents", target="demo")
        result.stats["judge"] = "droid"
        result.stats["droid_sessions"] = [{"session_id": "abc123", "scenario": "ID1"}]
        self.assertIsNotNone(record_run(cfg, result))

        summary = summarize_runs(cfg)
        self.assertEqual(summary["runs"], 1)
        self.assertEqual(summary["by_surface"], {"agents": 1})
        self.assertEqual(summary["droid_judged_assertions"], 1)
        self.assertEqual(summary["droid_sessions"], ["abc123"])

    def test_sessions_are_deduplicated_across_runs(self):
        cfg = self.repo.config()
        for _ in range(3):
            result = Result(surface="agents", target="demo")
            result.stats["droid_sessions"] = [{"session_id": "same"}]
            record_run(cfg, result)
        summary = summarize_runs(cfg)
        self.assertEqual(summary["runs"], 3)
        self.assertEqual(summary["droid_sessions"], ["same"])

    def test_no_history_is_an_empty_summary_not_an_error(self):
        summary = summarize_runs(self.repo.config())
        self.assertEqual(summary["runs"], 0)

    def test_recording_never_raises_on_an_unwritable_path(self):
        cfg = Config(root=self.repo.dir, runs_dir=Path("/proc/nope/runs"))
        self.assertIsNone(record_run(cfg, Result(surface="lists", target="x")))


if __name__ == "__main__":
    unittest.main()
