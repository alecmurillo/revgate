"""Targets: the thing being tested.

A target is anything that can answer `reply(history) -> str`, where `history` is
an OpenAI-shaped message list. Three ship here:

- `demo`   the bundled unsafe agent, offline and deterministic
- `openai` any OpenAI-compatible `/chat/completions` endpoint
- `shell`  an arbitrary command that reads JSON on stdin and writes JSON on stdout

The `shell` target is the escape hatch: if your agent is reachable by any means at
all, you can wrap it in ten lines and test it without changing revgate.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Target(Protocol):
    name: str

    def reply(self, history: list[dict[str, str]]) -> str: ...


def build(kind: str, system: str = "") -> Target:
    kind = (kind or "demo").strip().lower()
    if kind == "demo":
        from .demo import DemoTarget

        return DemoTarget(system=system)
    if kind in ("openai", "openai-compat", "http"):
        from .openai_compat import OpenAICompatTarget

        return OpenAICompatTarget(system=system)
    if kind in ("shell", "cmd", "exec"):
        from .shell import ShellTarget

        return ShellTarget(system=system)
    raise ValueError(f"unknown target {kind!r}; expected one of: demo, openai, shell")


KNOWN_TARGETS = ("demo", "openai", "shell")
