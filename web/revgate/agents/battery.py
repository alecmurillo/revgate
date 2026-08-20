"""Battery loading: scenarios, assertions, and their compiled patterns.

A scenario is a persona plus the assertion that must hold. Both halves are
required. A scenario with no assertion can never fail, so loading one is an error
rather than a silently useless test.

Assertion scope is fixed and deliberate:

- `must_not_match` is evaluated against **every** agent reply in the exchange. A
  leak on turn one is a leak, even if the closing turn is clean.
- `must_match_any` and `must_match_all` are evaluated against the **final** reply,
  because that is where a resolution is expected to appear.
- `semantic` is prose, judged by a model. It is depth on top of the patterns, never
  a substitute for them.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..core.findings import Severity


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    priority: Severity
    turns: tuple[str, ...]
    tags: tuple[str, ...] = ()
    must_not_match: tuple[re.Pattern[str], ...] = ()
    must_match_any: tuple[re.Pattern[str], ...] = ()
    must_match_all: tuple[re.Pattern[str], ...] = ()
    semantic: str = ""
    remedy: str = ""
    origin: str = ""

    @property
    def has_pattern_assertions(self) -> bool:
        return bool(self.must_not_match or self.must_match_any or self.must_match_all)


@dataclass
class Battery:
    name: str
    description: str
    path: Path
    scenarios: tuple[Scenario, ...] = ()
    system: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Battery":
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"no battery file at {p}")
        with p.open("rb") as fh:
            data = tomllib.load(fh)

        raw_scenarios = data.get("scenario", [])
        if not raw_scenarios:
            raise ValueError(f"{p} defines no [[scenario]] entries")

        scenarios: list[Scenario] = []
        seen: set[str] = set()
        for i, raw in enumerate(raw_scenarios, start=1):
            sid = str(raw.get("id") or "").strip()
            if not sid:
                raise ValueError(f"{p}: scenario #{i} has no id")
            if sid in seen:
                raise ValueError(f"{p}: duplicate scenario id {sid!r}")
            seen.add(sid)

            turns = tuple(str(t) for t in raw.get("turns", []) if str(t).strip())
            if not turns:
                raise ValueError(f"{p}: scenario {sid} has no turns to send")

            def compiled(key: str) -> tuple[re.Pattern[str], ...]:
                out = []
                for pattern in raw.get(key, []) or []:
                    try:
                        out.append(re.compile(str(pattern), re.IGNORECASE | re.DOTALL))
                    except re.error as exc:
                        raise ValueError(
                            f"{p}: scenario {sid} has an invalid regex in {key}: {pattern!r} ({exc})"
                        ) from exc
                return tuple(out)

            scenario = Scenario(
                id=sid,
                title=str(raw.get("title") or sid),
                priority=Severity.parse(raw.get("priority", "P1")),
                turns=turns,
                tags=tuple(str(t) for t in raw.get("tags", []) or ()),
                must_not_match=compiled("must_not_match"),
                must_match_any=compiled("must_match_any"),
                must_match_all=compiled("must_match_all"),
                semantic=str(raw.get("semantic") or "").strip(),
                remedy=str(raw.get("remedy") or "").strip(),
                origin=str(raw.get("origin") or "").strip(),
            )
            if not scenario.has_pattern_assertions and not scenario.semantic:
                raise ValueError(
                    f"{p}: scenario {sid} asserts nothing, so it can never fail. "
                    "Add must_not_match, must_match_any, must_match_all, or semantic."
                )
            scenarios.append(scenario)

        return cls(
            name=str(data.get("name") or p.stem),
            description=str(data.get("description") or ""),
            path=p,
            scenarios=tuple(scenarios),
            system=str(data.get("system") or ""),
            metadata={str(k): str(v) for k, v in (data.get("metadata", {}) or {}).items()},
        )

    def select(self, only: list[str] | None = None, priority: str | None = None) -> list[Scenario]:
        chosen = list(self.scenarios)
        if only:
            wanted = {t.strip().upper() for t in only}
            missing = wanted - {s.id.upper() for s in chosen}
            if missing:
                raise ValueError(f"no such scenario(s): {', '.join(sorted(missing))}")
            chosen = [s for s in chosen if s.id.upper() in wanted]
        if priority:
            ceiling = Severity.parse(priority)
            allowed = {s for s in Severity if not ceiling < s}
            chosen = [s for s in chosen if s.priority in allowed]
        return chosen
