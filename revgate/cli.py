"""Command line entry point.

Exit codes are the contract, because the point of the tool is to stop something:

    0  clean
    1  advisory findings only, and --strict was passed
    2  blocked: a P0 finding, or a configured check that could not run
    3  usage or configuration error
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, provenance as provenance_mod
from .core.config import Config
from .core.findings import EXIT_USAGE, Result, Severity
from .core.report import render

DEFAULT_BATTERY = Path(__file__).resolve().parent / "batteries" / "sales-intake.toml"


def _emit(text: str, out: str | None) -> None:
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        print(f"wrote {path}")
    else:
        print(text)


def _finish(result: Result, cfg: Config, args: argparse.Namespace) -> int:
    # Include the config path in the output so the reader can see which
    # config was used (G6). Falls back to "default" if no config file was found.
    config_path = getattr(cfg, "source_path", None)
    if config_path:
        result.notes.append(f"config: {config_path}")

    # Compute the exit code BEFORE any output. The pipe can close during
    # _emit (BrokenPipeError), and the exit code must already be decided
    # by then — not computed after the write that can fail.
    code = result.exit_code(cfg.strict)
    try:
        _emit(render(result, args.format, cfg.strict), getattr(args, "out", None))
    except BrokenPipeError:
        pass  # verdict already decided
    if not getattr(args, "no_record", False):
        try:
            provenance_mod.record_run(cfg, result)
        except BrokenPipeError:
            pass
    return code


def _base_config(args: argparse.Namespace) -> Config:
    cfg = Config.load(getattr(args, "config", None))
    overrides: dict[str, object] = {}
    if getattr(args, "strict", False):
        overrides["strict"] = True
    if getattr(args, "suppress", None):
        overrides["suppression"] = Path(args.suppress).resolve()
    if getattr(args, "dnc", None):
        overrides["dnc"] = Path(args.dnc).resolve()
    if getattr(args, "today", None):
        try:
            overrides["today"] = datetime.strptime(args.today, "%Y-%m-%d").date()
        except ValueError as exc:
            raise SystemExit(f"revgate: --today must be YYYY-MM-DD ({exc})")
    if getattr(args, "target", None):
        overrides["target"] = args.target
    if getattr(args, "judge", None):
        overrides["judge"] = args.judge
    if getattr(args, "judge_model", None):
        overrides["judge_model"] = args.judge_model
    if getattr(args, "battery", None):
        overrides["battery"] = Path(args.battery).resolve()
    return cfg.with_overrides(**overrides)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_lint(args: argparse.Namespace) -> int:
    from .lists import runner

    cfg = _base_config(args)
    only = [t for t in (args.only or "").split(",") if t.strip()] or None
    try:
        result = runner.run(args.leads, cfg, only=only)
    except FileNotFoundError as exc:
        print(f"revgate: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ValueError as exc:
        print(f"revgate: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return _finish(result, cfg, args)


def cmd_redteam(args: argparse.Namespace) -> int:
    from .agents import judge as judge_mod, runner
    from .agents.battery import Battery
    from .agents.targets import build as build_target
    from .agents.targets.openai_compat import TargetError

    cfg = _base_config(args)
    battery_path = Path(cfg.battery) if cfg.battery else DEFAULT_BATTERY
    if not battery_path.is_file():
        print(f"revgate: no battery at {battery_path}; pass --battery", file=sys.stderr)
        return EXIT_USAGE

    try:
        battery = Battery.load(battery_path)
    except (ValueError, FileNotFoundError) as exc:
        print(f"revgate: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        target = build_target(cfg.target, system=battery.system)
    except (ValueError, TargetError) as exc:
        print(f"revgate: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        judge = judge_mod.build(cfg.judge, model=cfg.judge_model, cwd=cfg.root)
    except ValueError as exc:
        print(f"revgate: {exc}", file=sys.stderr)
        return EXIT_USAGE

    only = [t for t in (args.only or "").split(",") if t.strip()] or None
    try:
        result = runner.run(
            battery, cfg, target=target, judge=judge,
            only=only, priority=args.priority, transcripts_dir=args.transcripts,
        )
    except ValueError as exc:
        print(f"revgate: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return _finish(result, cfg, args)


def cmd_provenance(args: argparse.Namespace) -> int:
    cfg = _base_config(args)

    if args.runs:
        summary = provenance_mod.summarize_runs(cfg)
        if args.format == "json":
            import json

            _emit(json.dumps(summary, indent=2), args.out)
            return 0
        lines = [
            "",
            f"revgate run history · {summary['runs']} run(s)",
        ]
        for surface, count in sorted(summary["by_surface"].items()):
            lines.append(f"  {surface:<12} {count}")
        lines.append(f"  assertions judged by droid exec: {summary['droid_judged_assertions']}")
        lines.append(f"  distinct droid sessions:         {len(summary['droid_sessions'])}")
        for sid in summary["droid_sessions"][:10]:
            lines.append(f"    {sid}")
        if len(summary["droid_sessions"]) > 10:
            lines.append(f"    … {len(summary['droid_sessions']) - 10} more")
        if summary["first"]:
            lines.append(f"  first {summary['first']}")
            lines.append(f"  last  {summary['last']}")
        lines.append("")
        _emit("\n".join(lines), args.out)
        return 0

    result = provenance_mod.verify(cfg)
    return _finish(result, cfg, args)


def cmd_diff(args: argparse.Namespace) -> int:
    from .lists.diff import diff_lists

    cfg = _base_config(args)
    only = [t for t in (args.only or "").split(",") if t.strip()] or None
    try:
        result = diff_lists(args.old, args.new, cfg, only=only, key_field=args.key)
    except FileNotFoundError as exc:
        print(f"revgate: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ValueError as exc:
        print(f"revgate: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return _finish(result, cfg, args)


def cmd_rules(args: argparse.Namespace) -> int:
    from .lists.rules import RULES

    if args.format == "json":
        import json

        payload = [
            {
                "id": r.id, "name": r.name, "severity": r.severity.value,
                "summary": r.summary, "origin": r.origin,
            }
            for r in RULES
        ]
        _emit(json.dumps(payload, indent=2), args.out)
        return 0

    if args.format == "md":
        lines = ["| Gate | Severity | Checks for | Why it exists |", "|---|---|---|---|"]
        for r in RULES:
            lines.append(f"| `{r.id}` {r.name} | {r.severity.value} | {r.summary} | {r.origin} |")
        _emit("\n".join(lines), args.out)
        return 0

    lines = ["", f"revgate list gates ({len(RULES)})", ""]
    for r in RULES:
        lines.append(f"  {r.severity.value}  {r.id}  {r.name}")
        lines.append(f"        {r.summary}")
        lines.append(f"        why: {r.origin}")
        lines.append("")
    _emit("\n".join(lines), args.out)
    return 0


def cmd_scenarios(args: argparse.Namespace) -> int:
    from .agents.battery import Battery

    cfg = _base_config(args)
    battery_path = Path(cfg.battery) if cfg.battery else DEFAULT_BATTERY
    try:
        battery = Battery.load(battery_path)
    except (ValueError, FileNotFoundError) as exc:
        print(f"revgate: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.format == "json":
        import json

        payload = [
            {
                "id": s.id, "title": s.title, "priority": s.priority.value,
                "tags": list(s.tags), "turns": list(s.turns),
                "assertions": {
                    "must_not_match": [p.pattern for p in s.must_not_match],
                    "must_match_any": [p.pattern for p in s.must_match_any],
                    "must_match_all": [p.pattern for p in s.must_match_all],
                    "semantic": s.semantic,
                },
            }
            for s in battery.scenarios
        ]
        _emit(json.dumps(payload, indent=2), args.out)
        return 0

    if args.format == "md":
        lines = [f"# {battery.name}", "", battery.description, "",
                 "| ID | Priority | Scenario | Tags |", "|---|---|---|---|"]
        for s in battery.scenarios:
            lines.append(f"| `{s.id}` | {s.priority.value} | {s.title} | {', '.join(s.tags)} |")
        _emit("\n".join(lines), args.out)
        return 0

    lines = ["", f"{battery.name} · {len(battery.scenarios)} scenarios", ""]
    for s in battery.scenarios:
        tags = f"  [{', '.join(s.tags)}]" if s.tags else ""
        lines.append(f"  {s.priority.value}  {s.id:<8} {s.title}{tags}")
    lines.append("")
    _emit("\n".join(lines), args.out)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .api.server import serve

    cfg = _base_config(args)
    key = args.key or __import__("os").environ.get("REVGATE_API_KEY", "")
    serve(port=args.port, auth_key=key or None, config=cfg)
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from .audit import audit, render_audit_text, render_audit_json

    cfg = _base_config(args)
    use_droid = args.judge == "droid"
    try:
        result = audit(args.leads, cfg, use_droid=use_droid, max_workers=getattr(args, "max_workers", 4))
    except FileNotFoundError as exc:
        print(f"revgate: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ValueError as exc:
        print(f"revgate: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.format == "json":
        print(render_audit_json(result, cfg.strict))
    else:
        print(render_audit_text(result, cfg.strict))

    if not args.no_record:
        provenance_mod.record_run(cfg, result.lint_result)
    return result.exit_code


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="revgate",
        description="Fail-closed QA for the artifacts that touch your prospects.",
    )
    parser.add_argument("--version", action="version", version=f"revgate {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, *, formats: tuple[str, ...] = ("text", "md", "json", "html")) -> None:
        p.add_argument("-c", "--config", help=f"path to a config file (default: nearest revgate.toml)")
        p.add_argument("-f", "--format", choices=formats, default="text")
        p.add_argument("-o", "--out", help="write the report here instead of stdout")
        p.add_argument("--strict", action="store_true", help="exit 1 on P1 findings as well as P0")
        p.add_argument("--no-record", action="store_true", help="do not append a run record under .revgate/runs")

    lint = sub.add_parser("lint", help="gate a lead list before it is dialled or sent")
    lint.add_argument("leads", help="CSV of leads to check")
    lint.add_argument("--suppress", help="CSV of accounts already in play (CRM export, prior campaign)")
    lint.add_argument("--dnc", help="CSV of suppressed phone numbers")
    lint.add_argument("--only", help="run only these gates, e.g. L001,L003")
    lint.add_argument("--today", help="pin the reference date (YYYY-MM-DD) for reproducible runs")
    common(lint)
    lint.set_defaults(func=cmd_lint)

    red = sub.add_parser("redteam", help="run adversarial scenarios against a customer-facing agent")
    red.add_argument("--battery", help="battery TOML (default: the bundled sales-intake battery)")
    red.add_argument("--target", choices=("demo", "openai", "shell"), help="what to test (default: demo)")
    red.add_argument("--judge", choices=("pattern", "droid"), help="how to grade (default: pattern)")
    red.add_argument("--judge-model", help="model id for the droid judge")
    red.add_argument("--only", help="run only these scenario ids")
    red.add_argument("--priority", choices=("P0", "P1", "P2"), help="run this priority and above")
    red.add_argument("--transcripts", help="write every exchange to this directory")
    common(red)
    red.set_defaults(func=cmd_redteam)

    prov = sub.add_parser("provenance", help="verify how this repo uses Factory, or show run history")
    prov.add_argument("--runs", action="store_true", help="summarise recorded runs instead of verifying claims")
    common(prov, formats=("text", "json"))
    prov.set_defaults(func=cmd_provenance)

    dif = sub.add_parser("diff", help="compare two lead lists and re-gate the rows that changed")
    dif.add_argument("old", help="the previous export (baseline)")
    dif.add_argument("new", help="the new export to check")
    dif.add_argument("--key", default="domain", choices=("domain", "email", "company"),
                      help="field to match rows on (default: domain)")
    dif.add_argument("--suppress", help="CSV of accounts already in play")
    dif.add_argument("--dnc", help="CSV of suppressed phone numbers")
    dif.add_argument("--only", help="run only these gates on the changed rows")
    dif.add_argument("--today", help="pin the reference date (YYYY-MM-DD)")
    common(dif)
    dif.set_defaults(func=cmd_diff)

    rules = sub.add_parser("rules", help="list the list gates and why each exists")
    rules.add_argument("-f", "--format", choices=("text", "md", "json"), default="text")  # html not needed for rules
    rules.add_argument("-o", "--out")
    rules.set_defaults(func=cmd_rules)

    scen = sub.add_parser("scenarios", help="list the scenarios in a battery")
    scen.add_argument("--battery")
    scen.add_argument("-c", "--config")
    scen.add_argument("-f", "--format", choices=("text", "md", "json"), default="text")  # html not needed for scenarios
    scen.add_argument("-o", "--out")
    scen.set_defaults(func=cmd_scenarios)

    srv = sub.add_parser("serve", help="run the HTTP gating API for Clay/HubSpot/Apollo webhooks")
    srv.add_argument("--port", type=int, default=8000, help="port to listen on (default: 8000)")
    srv.add_argument("--key", help="shared secret for X-Revgate-Key auth (default: $REVGATE_API_KEY)")
    srv.add_argument("-c", "--config")
    srv.set_defaults(func=cmd_serve)

    aud = sub.add_parser("audit", help="multi-agent audit: pattern gates + droid exec review")
    aud.add_argument("leads", help="CSV of leads to audit")
    aud.add_argument("--judge", choices=("pattern", "droid"), default="pattern",
                      help="pattern only (default) or add droid exec review per finding group")
    aud.add_argument("--max-workers", type=int, default=4,
                      help="max parallel droid exec sessions (default: 4)")
    aud.add_argument("--suppress", help="CSV of accounts already in play")
    aud.add_argument("--dnc", help="CSV of suppressed phone numbers")
    aud.add_argument("--only", help="run only these gates, e.g. L001,L003")
    aud.add_argument("--today", help="pin the reference date (YYYY-MM-DD)")
    common(aud, formats=("text", "json"))
    aud.set_defaults(func=cmd_audit)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Do NOT set SIGPIPE to SIG_DFL — it kills the process with signal 13
    # (exit 141) before the BrokenPipeError handler below can preserve the
    # real exit code. Instead, let Python raise BrokenPipeError on the
    # next stdout write, catch it, and return whatever code the run computed.
    parser = build_parser()
    args = parser.parse_args(argv)
    code = EXIT_USAGE
    try:
        code = int(args.func(args))
        sys.stdout.flush()
    except BrokenPipeError:
        pass  # keep whatever code the run computed
    except KeyboardInterrupt:
        print("\nrevgate: interrupted", file=sys.stderr)
        return EXIT_USAGE
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return EXIT_USAGE
        return int(exc.code or 0)
    except Exception as exc:
        print(f"revgate: {exc}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        # Redirect stdout to /dev/null before interpreter shutdown so
        # Python's cleanup flush doesn't re-raise BrokenPipeError.
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
