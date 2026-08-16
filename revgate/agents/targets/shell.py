"""An arbitrary command as the target.

The contract is one line of JSON in, one reply out:

    stdin   {"messages": [{"role": "user", "content": "..."}, ...]}
    stdout  {"content": "..."}   or plain text, if that is easier

Configure with:

    REVGATE_TARGET_CMD       required, e.g. "python3 my_agent.py"
    REVGATE_TARGET_TIMEOUT   seconds, default 60

This is how you test an agent that lives behind a queue, a websocket, a telephony
provider, or anything else that is not an HTTP chat endpoint: write the adapter in
whatever language you like and point revgate at it.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess

from .openai_compat import TargetError


class ShellTarget:
    name = "shell"
    description = "Subprocess speaking JSON on stdin/stdout"

    def __init__(self, system: str = "") -> None:
        raw = (os.environ.get("REVGATE_TARGET_CMD") or "").strip()
        if not raw:
            raise TargetError(
                "the shell target needs REVGATE_TARGET_CMD set, e.g. "
                'REVGATE_TARGET_CMD="python3 examples/my_agent.py"'
            )
        self.argv = shlex.split(raw)
        try:
            self.timeout = float(os.environ.get("REVGATE_TARGET_TIMEOUT", "60"))
        except ValueError:
            self.timeout = 60.0
        self.system = system

    def reply(self, history: list[dict[str, str]]) -> str:
        payload = {"messages": history}
        if self.system:
            payload["system"] = self.system
        try:
            proc = subprocess.run(
                self.argv,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise TargetError(f"could not execute {self.argv[0]!r}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise TargetError(f"target command timed out after {self.timeout}s") from exc

        if proc.returncode != 0:
            raise TargetError(
                f"target command exited {proc.returncode}: {(proc.stderr or '').strip()[:400]}"
            )

        out = (proc.stdout or "").strip()
        if not out:
            raise TargetError("target command produced no output")
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            return out
        if isinstance(parsed, str):
            return parsed
        if isinstance(parsed, dict):
            for key in ("content", "reply", "message", "text", "output"):
                value = parsed.get(key)
                if isinstance(value, str):
                    return value
                if isinstance(value, dict) and isinstance(value.get("content"), str):
                    return value["content"]
        raise TargetError(
            "target JSON had no content/reply/message/text field: " + out[:300]
        )
