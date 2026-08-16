"""Stdlib HTTP server for the gating API.

One endpoint: ``POST /v1/lint``. It accepts a JSON payload from any source
(Clay, HubSpot, Apollo, or raw), runs the existing gate engine, and returns
a structured result.

Design decisions:

- **Zero dependencies.** Uses ``http.server`` from the stdlib. For production,
  run behind a real HTTP server (gunicorn, nginx). For local testing, the
  server is sufficient.
- **Shared-secret auth.** If ``--key`` is set, every request must carry
  ``X-Revgate-Key`` with the same value. No key, wrong key → 401.
- **Fail-closed on every error path.** A malformed payload returns a BLOCKED
  response, not a 200 with a PASS. An internal error returns 500 with a
  BLOCKED verdict. The calling system should treat any non-200 as BLOCK.
- **The server is a transport, not a logic layer.** It calls
  ``run_on_dataset`` — the same function the CLI calls. No gate logic lives
  here.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from ..core.config import Config
from ..core.dataset import Dataset
from ..core.findings import Result, Severity
from ..lists.runner import run_on_dataset
from .adapters import AdapterError, get_adapter, RowInput

API_VERSION = "1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _verdict_from_exit(code: int) -> str:
    return {0: "PASS", 1: "ADVISORY", 2: "BLOCKED"}.get(code, "BLOCKED")


def _severity_from_findings(findings: list) -> str:
    """Highest severity across all findings, or empty string if none."""
    if not findings:
        return ""
    severities = [f.severity for f in findings]
    if Severity.P0 in severities:
        return "P0"
    if Severity.P1 in severities:
        return "P1"
    return "P2"


def _rules_from_findings(findings: list) -> str:
    """Comma-separated unique rule IDs, sorted by severity then ID."""
    seen: dict[str, None] = {}
    for f in sorted(findings, key=lambda f: (list(Severity).index(f.severity), f.rule)):
        seen.setdefault(f.rule, None)
    return ", ".join(seen)


def _summary_from_findings(findings: list, skipped: list) -> str:
    """One-line human-readable summary for the writeback field."""
    if not findings and not skipped:
        return "All gates passed."
    parts: list[str] = []
    grouped: dict[str, list] = {}
    for f in findings:
        grouped.setdefault(f.rule, []).append(f)
    for rule, items in sorted(grouped.items(), key=lambda kv: (list(Severity).index(kv[1][0].severity), kv[0])):
        parts.append(f"{rule}: {items[0].title} ({len(items)})")
    blocking_skips = [s for s in skipped if s.blocking]
    if blocking_skips:
        parts.append(f"blocking skips: {', '.join(s.rule for s in blocking_skips)}")
    return "; ".join(parts) if parts else "All gates passed."


def _row_to_response(
    row_result: Result,
    external_id: str,
    checked_at: str,
) -> dict[str, Any]:
    """Format one row's result with writeback fields."""
    verdict = row_result.verdict(strict=False)
    exit_code = row_result.exit_code(strict=False)
    severity = _severity_from_findings(row_result.findings)
    rules = _rules_from_findings(row_result.findings)
    summary = _summary_from_findings(row_result.findings, row_result.skipped)

    return {
        "external_id": external_id,
        "verdict": verdict,
        "exit_code": exit_code,
        "findings": [f.to_dict() for f in row_result.findings],
        "skipped": [s.to_dict() for s in row_result.skipped],
        "stats": row_result.stats,
        "notes": list(row_result.notes),
        # Writeback fields — map these in Clay/HubSpot/Apollo:
        "revgate_status": verdict,
        "revgate_severity": severity,
        "revgate_rules": rules,
        "revgate_summary": summary,
        "revgate_checked_at": checked_at,
    }


def evaluate(
    body: dict[str, Any],
    base_config: Config,
    *,
    source: str | None = None,
) -> dict[str, Any]:
    """Run the gate engine on a parsed request body and return the response dict.

    This is the core function the HTTP handler calls, and it is also the
    function tests call directly — no need to start a server to test the logic.
    """
    checked_at = _now_iso()
    src = source or body.get("source", "generic")

    try:
        adapter = get_adapter(src)
        row_inputs: list[RowInput] = adapter(body)
    except AdapterError as exc:
        return {
            "version": API_VERSION,
            "verdict": "BLOCKED",
            "exit_code": 2,
            "error": str(exc),
            "checked_at": checked_at,
            "rows": [],
            "counts": {"P0": 0, "P1": 0, "P2": 0},
            "skipped": [],
            "stats": {},
            "notes": [f"Adapter error: {exc}"],
        }

    if not row_inputs:
        return {
            "version": API_VERSION,
            "verdict": "BLOCKED",
            "exit_code": 2,
            "error": "no rows to evaluate",
            "checked_at": checked_at,
            "rows": [],
            "counts": {"P0": 0, "P1": 0, "P2": 0},
            "skipped": [],
            "stats": {},
            "notes": ["Adapter returned zero rows — nothing to evaluate."],
        }

    # Apply request-level config overrides to the base config.
    config_overrides = body.get("config", {})
    cfg = _apply_overrides(base_config, config_overrides)

    # Evaluate each row independently so the calling system can act per-row.
    row_results: list[dict[str, Any]] = []
    all_findings_count = {"P0": 0, "P1": 0, "P2": 0}
    all_skipped: list[dict[str, Any]] = []
    worst_exit = 0

    for ri in row_inputs:
        ds = Dataset.from_rows([ri.data], overrides=cfg.columns)
        result = run_on_dataset(ds, cfg, target=f"{src}:{ri.external_id}")

        row_resp = _row_to_response(result, ri.external_id, checked_at)
        row_results.append(row_resp)

        counts = result.counts()
        for k in all_findings_count:
            all_findings_count[k] += counts[k]
        for s in result.skipped:
            sd = s.to_dict()
            if sd not in all_skipped:
                all_skipped.append(sd)
        worst_exit = max(worst_exit, result.exit_code(strict=False))

    # Overall verdict is the worst across all rows.
    overall_verdict = _verdict_from_exit(worst_exit)

    return {
        "version": API_VERSION,
        "source": src,
        "verdict": overall_verdict,
        "exit_code": worst_exit,
        "counts": all_findings_count,
        "checked_at": checked_at,
        "rows": row_results,
        "skipped": all_skipped,
        "stats": {"rows evaluated": len(row_results)},
        "notes": [],
    }


def _apply_overrides(base: Config, overrides: dict[str, Any]) -> Config:
    """Apply request-level scalar config overrides on top of the server config.

    Only safe scalar values are accepted — things like ``restricted_states``
    and ``headcount_ceiling``. File paths (suppression, DNC) are never
    accepted from the request; they come from the server's config file only,
    so a request cannot redirect the server at an arbitrary file.
    """
    if not overrides:
        return base

    kwargs: dict[str, Any] = {}

    if "restricted_states" in overrides:
        kwargs["restricted_states"] = tuple(str(s) for s in overrides["restricted_states"])
    if "headcount_ceiling" in overrides:
        kwargs["headcount_exclude_above"] = int(overrides["headcount_ceiling"])
    if "headcount_floor" in overrides:
        kwargs["headcount_floor_warn"] = int(overrides["headcount_floor"])
    if "recent_contact_days" in overrides:
        kwargs["recent_contact_days"] = int(overrides["recent_contact_days"])
    if "stale_enrichment_days" in overrides:
        kwargs["stale_enrichment_days"] = int(overrides["stale_enrichment_days"])
    if "strict" in overrides:
        kwargs["strict"] = bool(overrides["strict"])
    if "columns" in overrides and isinstance(overrides["columns"], dict):
        kwargs["columns"] = {str(k): str(v) for k, v in overrides["columns"].items()}

    return base.with_overrides(**kwargs) if kwargs else base


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    server_version = "revgate/1.0"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        expected = self.server.auth_key  # type: ignore[attr-defined]
        if not expected:
            return True
        provided = self.headers.get("X-Revgate-Key", "")
        return provided == expected

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/health":
            self._send_json(200, {"status": "ok", "version": API_VERSION})
        else:
            self._send_json(404, {"error": "not found", "hint": "use POST /v1/lint"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_auth():
            self._send_json(401, {
                "version": API_VERSION,
                "verdict": "BLOCKED",
                "exit_code": 2,
                "error": "unauthorized: missing or invalid X-Revgate-Key",
            })
            return

        if self.path != "/v1/lint":
            self._send_json(404, {"error": "not found", "hint": "use POST /v1/lint"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length) if content_length else b""

        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            self._send_json(400, {
                "version": API_VERSION,
                "verdict": "BLOCKED",
                "exit_code": 2,
                "error": f"invalid JSON: {exc}",
                "checked_at": _now_iso(),
                "rows": [],
                "counts": {"P0": 0, "P1": 0, "P2": 0},
                "skipped": [],
                "stats": {},
                "notes": ["Request body is not valid JSON."],
            })
            return

        try:
            response = evaluate(body, self.server.base_config)  # type: ignore[attr-defined]
        except Exception as exc:
            # Any unhandled error is fail-closed: BLOCKED, not PASS.
            self._send_json(500, {
                "version": API_VERSION,
                "verdict": "BLOCKED",
                "exit_code": 2,
                "error": f"internal error: {exc}",
                "checked_at": _now_iso(),
                "rows": [],
                "counts": {"P0": 0, "P1": 0, "P2": 0},
                "skipped": [],
                "stats": {},
                "notes": [f"Server error: {exc}"],
            })
            return

        # 200 for PASS, 200 for ADVISORY (non-strict), 422 for BLOCKED.
        # Using 422 (Unprocessable Entity) rather than 200 so the calling
        # system can branch on HTTP status without parsing the body.
        http_status = 200 if response["exit_code"] <= 1 else 422
        self._send_json(http_status, response)

    def log_message(self, fmt: str, *args: Any) -> None:
        # Log to stderr so stdout stays clean for piping.
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")


def create_server(
    port: int = 8000,
    *,
    auth_key: str | None = None,
    config: Config | None = None,
) -> HTTPServer:
    """Create an HTTPServer instance (for testing or programmatic use)."""
    server = HTTPServer(("0.0.0.0", port), _Handler)
    server.auth_key = auth_key or ""  # type: ignore[attr-defined]
    server.base_config = config or Config.load()  # type: ignore[attr-defined]
    return server


def serve(port: int = 8000, *, auth_key: str | None = None, config: Config | None = None) -> None:
    """Start the blocking HTTP server."""
    server = create_server(port, auth_key=auth_key, config=config)
    print(f"revgate serve on http://0.0.0.0:{port}", file=sys.stderr)
    if auth_key:
        print("  auth: X-Revgate-Key required", file=sys.stderr)
    else:
        print("  auth: none (set --key to enable)", file=sys.stderr)
    print(f"  endpoint: POST /v1/lint", file=sys.stderr)
    print(f"  health:   GET /v1/health", file=sys.stderr)
    print(file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nrevgate: shutting down", file=sys.stderr)
        server.shutdown()
