"""Configuration, loaded from `revgate.toml`.

Every path in a config file resolves relative to that file, not to the process
working directory. Config that behaves differently depending on where you invoke
it from is config that silently stops finding your suppression list.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

CONFIG_NAME = "revgate.toml"

DEFAULT_GENERIC_TRIGGERS: tuple[str, ...] = (
    "n/a", "na", "none", "-", "--", "tbd", "todo", "unknown", "good fit", "great fit",
    "growing", "growing fast", "fast growing", "interesting", "relevant", "icp",
    "target account", "high intent", "hiring", "scaling", "modern company",
)

DEFAULT_VERIFIED_STATUSES: tuple[str, ...] = (
    "verified", "valid", "safe", "deliverable", "ok", "good", "safe_to_send", "high",
)

DEFAULT_ROLE_MAILBOXES: tuple[str, ...] = (
    "info", "sales", "support", "admin", "hello", "contact", "billing", "team",
    "office", "help", "careers", "jobs", "hr", "press", "media", "noreply",
    "no-reply", "donotreply", "enquiries", "inquiries", "marketing", "accounts",
)

DEFAULT_FREE_EMAIL_DOMAINS: tuple[str, ...] = (
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com",
    "me.com", "mac.com", "proton.me", "protonmail.com", "gmx.com", "mail.com",
    "live.com", "msn.com", "yandex.com", "zoho.com",
)

DEFAULT_ENTITY_TERMS: tuple[str, ...] = (
    "fund", "capital", "partners", "ventures", "holdings", "holding", "trust",
    "spv", "lp", "llp", "reit", "acquisition corp", "opportunity zone",
)

DEFAULT_TITLE_EXCLUDE: tuple[str, ...] = (
    "intern", "student", "assistant", "trainee", "apprentice", "volunteer",
    "contractor", "temp", "seasonal",
)


@dataclass
class Config:
    """Resolved settings for one invocation."""

    root: Path = field(default_factory=Path.cwd)
    source_path: Path | None = None

    # lint
    strict: bool = False
    recent_contact_days: int = 14
    restricted_states: tuple[str, ...] = ()
    headcount_exclude_above: int = 200
    headcount_floor_warn: int = 5
    max_trigger_repeat_ratio: float = 0.5
    min_rows_for_distribution_checks: int = 20
    generic_triggers: tuple[str, ...] = DEFAULT_GENERIC_TRIGGERS
    verified_email_statuses: tuple[str, ...] = DEFAULT_VERIFIED_STATUSES
    role_mailboxes: tuple[str, ...] = DEFAULT_ROLE_MAILBOXES
    free_email_domains: tuple[str, ...] = DEFAULT_FREE_EMAIL_DOMAINS
    entity_terms: tuple[str, ...] = DEFAULT_ENTITY_TERMS
    stale_enrichment_days: int = 90
    dnc_stale_days: int = 31
    title_exclude_keywords: tuple[str, ...] = DEFAULT_TITLE_EXCLUDE
    today: date | None = None

    # sources
    suppression: Path | None = None
    dnc: Path | None = None
    dnc_exported: date | None = None  # declared DNC export date (replaces mtime)

    # explicit logical-field -> header overrides
    columns: dict[str, str] = field(default_factory=dict)

    # redteam
    battery: Path | None = None
    target: str = "demo"
    judge: str = "pattern"
    judge_model: str | None = None

    # provenance
    manifest: Path | None = None
    runs_dir: Path | None = None

    # rules to skip even when unconfigured (explicit opt-out)
    acknowledge_unconfigured: tuple[str, ...] = ()
    # rules to disable entirely
    disable: tuple[str, ...] = ()

    # paths the pre-commit hook and CI treat as lead lists
    list_globs: tuple[str, ...] = ("lists/**/*.csv",)

    @classmethod
    def discover(cls, start: str | Path = ".") -> Path | None:
        here = Path(start).resolve()
        for candidate in [here, *here.parents]:
            probe = candidate / CONFIG_NAME
            if probe.is_file():
                return probe
        return None

    @classmethod
    def load(cls, path: str | Path | None = None, *, search: bool = True) -> "Config":
        resolved: Path | None = None
        if path:
            resolved = Path(path).resolve()
            if not resolved.is_file():
                raise FileNotFoundError(f"no config file at {resolved}")
        elif search:
            resolved = cls.discover()

        if resolved is None:
            return cls()

        with resolved.open("rb") as fh:
            data: dict[str, Any] = tomllib.load(fh)

        root = resolved.parent
        cfg = cls(root=root, source_path=resolved)

        lint = data.get("lint", {}) or {}
        cfg.strict = bool(lint.get("strict", cfg.strict))
        cfg.recent_contact_days = int(lint.get("recent_contact_days", cfg.recent_contact_days))
        cfg.restricted_states = tuple(str(s) for s in lint.get("restricted_states", cfg.restricted_states))
        cfg.headcount_exclude_above = int(lint.get("headcount_exclude_above", cfg.headcount_exclude_above))
        cfg.headcount_floor_warn = int(lint.get("headcount_floor_warn", cfg.headcount_floor_warn))
        cfg.max_trigger_repeat_ratio = float(lint.get("max_trigger_repeat_ratio", cfg.max_trigger_repeat_ratio))
        cfg.min_rows_for_distribution_checks = int(
            lint.get("min_rows_for_distribution_checks", cfg.min_rows_for_distribution_checks)
        )
        cfg.stale_enrichment_days = int(lint.get("stale_enrichment_days", cfg.stale_enrichment_days))
        cfg.dnc_stale_days = int(lint.get("dnc_stale_days", cfg.dnc_stale_days))
        for key in (
            "generic_triggers",
            "verified_email_statuses",
            "role_mailboxes",
            "free_email_domains",
            "entity_terms",
            "title_exclude_keywords",
        ):
            if key in lint:
                setattr(cfg, key, tuple(str(v).lower() for v in lint[key]))

        sources = lint.get("sources", {}) or {}
        # `crm` is accepted as a friendlier alias for the same thing.
        supp = sources.get("suppression") or sources.get("crm")
        if supp:
            cfg.suppression = cfg._resolve(supp)
        if sources.get("dnc"):
            cfg.dnc = cfg._resolve(sources["dnc"])
        if sources.get("dnc_exported"):
            from datetime import datetime as _dt
            cfg.dnc_exported = _dt.strptime(str(sources["dnc_exported"]), "%Y-%m-%d").date()

        cfg.columns = {str(k): str(v) for k, v in (lint.get("columns", {}) or {}).items()}

        if "list_globs" in lint:
            cfg.list_globs = tuple(str(g) for g in lint["list_globs"])
        if "acknowledge_unconfigured" in lint:
            cfg.acknowledge_unconfigured = tuple(str(r).upper() for r in lint["acknowledge_unconfigured"])
        if "disable" in lint:
            cfg.disable = tuple(str(r).upper() for r in lint["disable"])

        red = data.get("redteam", {}) or {}
        if red.get("battery"):
            cfg.battery = cfg._resolve(red["battery"])
        cfg.target = str(red.get("target", cfg.target))
        cfg.judge = str(red.get("judge", cfg.judge))
        if red.get("judge_model"):
            cfg.judge_model = str(red["judge_model"])

        prov = data.get("provenance", {}) or {}
        cfg.manifest = cfg._resolve(prov.get("manifest", "factory-usage.toml"))
        cfg.runs_dir = cfg._resolve(prov.get("runs_dir", ".revgate/runs"))

        return cfg

    def _resolve(self, value: str | Path) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (self.root / p).resolve()

    def with_overrides(self, **kwargs: Any) -> "Config":
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return replace(self, **clean) if clean else self

    def reference_date(self) -> date:
        from datetime import datetime, timezone

        return self.today or datetime.now(timezone.utc).date()
