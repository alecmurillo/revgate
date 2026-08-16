"""Runs the list gates and assembles one Result.

Source loading is deliberately noisy about failure. A suppression file that is
configured and unreadable produces a blocking skip, not a warning, because the
alternative is a run that looks checked and is not.
"""

from __future__ import annotations

from pathlib import Path

from ..core.config import Config
from ..core.dataset import Dataset, load_key_set
from ..core.findings import Result
from .rules import RULES, RULES_BY_ID, Context, Rule


def _load_sources(cfg: Config, ctx: Context) -> None:
    if cfg.suppression is not None:
        try:
            ctx.suppression = load_key_set(cfg.suppression, kinds=("domain", "email"))
            ctx.suppression_path = Path(cfg.suppression)
        except FileNotFoundError:
            ctx.suppression = {"domain": set(), "email": set()}
            ctx.suppression_path = Path(cfg.suppression)

    if cfg.dnc is not None:
        try:
            ctx.dnc = load_key_set(cfg.dnc, kinds=("phone",))["phone"]
            ctx.dnc_path = Path(cfg.dnc)
        except FileNotFoundError:
            ctx.dnc = set()
            ctx.dnc_path = Path(cfg.dnc)


def select_rules(only: list[str] | None = None) -> list[Rule]:
    if not only:
        return list(RULES)
    wanted = []
    for token in only:
        key = token.strip().upper()
        rule = RULES_BY_ID.get(key)
        if rule is None:
            by_name = {r.name.lower(): r for r in RULES}
            rule = by_name.get(token.strip().lower())
        if rule is None:
            valid = ", ".join(r.id for r in RULES)
            raise ValueError(f"unknown rule {token!r}; known rules: {valid}")
        wanted.append(rule)
    return wanted


def run(path: str | Path, cfg: Config, only: list[str] | None = None) -> Result:
    ds = Dataset.load(path, overrides=cfg.columns)
    return run_on_dataset(ds, cfg, only, target=str(Path(path)))


def run_on_dataset(
    ds: Dataset, cfg: Config, only: list[str] | None = None, *, target: str = "(in-memory)",
) -> Result:
    ctx = Context()
    _load_sources(cfg, ctx)

    rules = select_rules(only)
    result = Result(surface="lists", target=target)

    for rule in rules:
        result.findings.extend(rule.check(ds, cfg, ctx))

    result.skipped.extend(ctx.skips)

    unmapped = [logical for logical in ("company", "domain", "email", "trigger") if not ds.has(logical)]
    result.stats = {
        "rows": len(ds),
        "columns": len(ds.headers),
        "gates run": len(rules) - len(ctx.skips),
        "gates skipped": len(ctx.skips),
    }
    if unmapped:
        result.notes.append(
            "No column resolved for: " + ", ".join(unmapped)
            + ". Map them under [lint.columns] in revgate.toml if they exist under a name revgate does not recognise."
        )
    if not ds.rows:
        result.notes.append(
            "The file has zero data rows. An empty list passes every gate, which is why this is stated rather than left implicit."
        )
    return result
