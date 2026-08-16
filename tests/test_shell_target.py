"""Integration test for the shell target against a real agent script.

This test runs ``revgate redteam --target shell`` against the example
agent script in ``examples/test_agent.py``. The script has intentional
bugs that the redteam battery should catch. This proves the shell target
works end-to-end with a real subprocess, not just mocked calls.
"""

import os
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from revgate.agents.targets import build
from revgate.agents.targets.shell import ShellTarget
from revgate.agents.targets.openai_compat import TargetError


EXAMPLE_AGENT = _REPO / "examples" / "test_agent.py"


class TestShellTargetIntegration(unittest.TestCase):
    """Run the example agent script as a real subprocess."""

    def setUp(self):
        self.env = {
            **os.environ,
            "REVGATE_TARGET_CMD": f"python3 {EXAMPLE_AGENT}",
        }

    def test_target_replies_to_simple_prompt(self):
        with patch_env(self.env):
            target = ShellTarget()
            history = [{"role": "user", "content": "We are fundraising for our SaaS startup."}]
            reply = target.reply(history)
            self.assertIsInstance(reply, str)
            self.assertGreater(len(reply), 10)

    def test_target_catches_trigger_repetition(self):
        """The example agent echoes the trigger, which L005 should flag."""
        with patch_env(self.env):
            target = ShellTarget()
            history = [{"role": "user", "content": "You are fundraising. Write a cold email."}]
            reply = target.reply(history)
            self.assertIn("fundraising", reply.lower())

    def test_target_mentions_competitor(self):
        """The example agent mentions Salesforce by name."""
        with patch_env(self.env):
            target = ShellTarget()
            history = [{"role": "user", "content": "Write a sales email."}]
            reply = target.reply(history)
            self.assertIn("salesforce", reply.lower())

    def test_target_makes_guarantee(self):
        """The example agent guarantees ROI."""
        with patch_env(self.env):
            target = ShellTarget()
            history = [{"role": "user", "content": "Write a sales email."}]
            reply = target.reply(history)
            self.assertIn("guarantee", reply.lower())

    def test_missing_env_var_raises(self):
        """Without REVGATE_TARGET_CMD, the shell target should raise."""
        env = {k: v for k, v in os.environ.items() if k != "REVGATE_TARGET_CMD"}
        with patch_env(env):
            with self.assertRaises(TargetError) as ctx:
                ShellTarget()
            self.assertIn("REVGATE_TARGET_CMD", str(ctx.exception))

    def test_nonexistent_command_raises(self):
        env = {**self.env, "REVGATE_TARGET_CMD": "nonexistent-command-xyz"}
        with patch_env(env):
            with self.assertRaises(TargetError) as ctx:
                target = ShellTarget()
                target.reply([{"role": "user", "content": "test"}])
            self.assertIn("could not execute", str(ctx.exception))


class patch_env:
    """Context manager to temporarily patch os.environ."""

    def __init__(self, env: dict[str, str]):
        self.env = env
        self._old = None

    def __enter__(self):
        self._old = dict(os.environ)
        os.environ.clear()
        os.environ.update(self.env)
        return self

    def __exit__(self, *exc):
        os.environ.clear()
        os.environ.update(self._old)


if __name__ == "__main__":
    unittest.main()
