"""Optional writeback adapters for Clay and HubSpot.

These functions POST revgate's per-row verdicts back to the source system
so that downstream teams see the quality flags without leaving their
workflow tool. They are **optional** — the core API server works without
them — and they require API keys that the caller provides.

Both adapters use only stdlib ``urllib.request`` (no third-party HTTP
client). Both are fail-closed: if a writeback fails, the error is
returned to the caller, never silently swallowed.

Usage from the API server (when configured):

    from revgate.api.writeback import writeback
    writeback("clay", api_key=clay_key, rows=evaluated_rows)

Or standalone:

    from revgate.api.writeback import writeback_clay, writeback_hubspot
    writeback_clay(api_key="sk-...", rows=[{"external_id": "row_1", "revgate_status": "blocked", ...}])
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

CLAY_API_URL = "https://api.clay.com/v3/sources/{source_id}/items"
HUBSPOT_API_URL = "https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}"


class WritebackError(Exception):
    """Raised when a writeback call fails."""


def _post_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    """POST JSON and return the parsed response. Raises WritebackError on failure."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={**headers, "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 400:
                raise WritebackError(f"HTTP {resp.status}: {resp.read().decode('utf-8', errors='replace')[:300]}")
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise WritebackError(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}") from exc
    except urllib.error.URLError as exc:
        raise WritebackError(f"network error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise WritebackError(f"invalid JSON response: {exc}") from exc


def writeback_clay(
    api_key: str,
    rows: list[dict[str, Any]],
    source_id: str | None = None,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Write revgate verdicts back to Clay.

    Each row must have ``external_id`` and the revgate fields
    (``revgate_status``, ``revgate_severity``, ``revgate_rules``,
    ``revgate_summary``, ``revgate_checked_at``).

    Requires ``source_id`` (the Clay source to update) either as an
    argument or from ``CLAY_SOURCE_ID`` env var.

    Returns a list of per-row results: ``[{"external_id": ..., "ok": True/False, "error": ...}]``.
    """
    if not api_key:
        raise WritebackError("CLAY_API_KEY is required for writeback")
    source_id = source_id or os.environ.get("CLAY_SOURCE_ID", "")
    if not source_id:
        raise WritebackError("CLAY_SOURCE_ID is required for Clay writeback")

    url = CLAY_API_URL.format(source_id=source_id)
    headers = {"Authorization": f"Bearer {api_key}"}
    results: list[dict[str, Any]] = []

    for row in rows:
        ext_id = row.get("external_id")
        if not ext_id:
            results.append({"external_id": "", "ok": False, "error": "missing external_id"})
            continue

        body = {
            "external_id": ext_id,
            "fields": {
                "revgate_status": row.get("revgate_status", ""),
                "revgate_severity": row.get("revgate_severity", ""),
                "revgate_rules": row.get("revgate_rules", ""),
                "revgate_summary": row.get("revgate_summary", ""),
                "revgate_checked_at": row.get("revgate_checked_at", ""),
            },
        }
        try:
            _post_json(url, headers, body, timeout=timeout)
            results.append({"external_id": ext_id, "ok": True, "error": ""})
        except WritebackError as exc:
            results.append({"external_id": ext_id, "ok": False, "error": str(exc)})

    return results


def writeback_hubspot(
    api_key: str,
    rows: list[dict[str, Any]],
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Write revgate verdicts back to HubSpot CRM.

    Each row must have ``external_id`` (the HubSpot contact ID) and the
    revgate fields. The function PATCHes each contact's custom properties.

    Returns a list of per-row results.
    """
    if not api_key:
        raise WritebackError("HUBSPOT_API_KEY is required for writeback")

    headers = {"Authorization": f"Bearer {api_key}"}
    results: list[dict[str, Any]] = []

    for row in rows:
        ext_id = row.get("external_id")
        if not ext_id:
            results.append({"external_id": "", "ok": False, "error": "missing external_id"})
            continue

        url = HUBSPOT_API_URL.format(contact_id=ext_id)
        body = {
            "properties": {
                "revgate_status": row.get("revgate_status", ""),
                "revgate_severity": row.get("revgate_severity", ""),
                "revgate_rules": row.get("revgate_rules", ""),
                "revgate_summary": row.get("revgate_summary", ""),
                "revgate_checked_at": row.get("revgate_checked_at", ""),
            }
        }
        try:
            _post_json(url, headers, body, timeout=timeout)
            results.append({"external_id": ext_id, "ok": True, "error": ""})
        except WritebackError as exc:
            results.append({"external_id": ext_id, "ok": False, "error": str(exc)})

    return results


def writeback(
    adapter: str,
    api_key: str,
    rows: list[dict[str, Any]],
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Dispatch to the right writeback adapter by name."""
    if adapter == "clay":
        return writeback_clay(api_key, rows, **kwargs)
    if adapter == "hubspot":
        return writeback_hubspot(api_key, rows, **kwargs)
    raise WritebackError(f"unknown writeback adapter: {adapter!r}")
