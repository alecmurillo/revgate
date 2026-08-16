"""Source-specific request parsers for the gating API.

Each adapter is a thin function that knows how to extract flat row dicts from
one system's webhook format. The gate engine never sees Clay, HubSpot, or
Apollo — it sees a ``Dataset`` with headers and rows, the same type it gets
from a CSV file.

All adapters return ``list[RowInput]`` where ``RowInput`` is a flat
``dict[str, str]`` plus an optional ``external_id`` the calling system can use
to map results back to its own records.

If an adapter cannot parse the payload, it raises ``AdapterError``. The
server catches this and returns a BLOCKED response, because a request that
cannot be evaluated is not a request that passed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RowInput:
    """One row from an upstream system, flattened to field-name → value."""

    data: dict[str, str]
    external_id: str = ""


class AdapterError(Exception):
    """The adapter could not parse the incoming payload.

    This is a fail-closed signal: the server returns BLOCKED, not PASS,
    because a request that cannot be evaluated is not a request that passed.
    """


# ---------------------------------------------------------------------------
# Generic / raw
# ---------------------------------------------------------------------------

def parse_generic(body: dict[str, Any]) -> list[RowInput]:
    """Accept rows in revgate's own format.

    Expected shape::

        {"rows": [{"Company": "Acme", "Domain": "acme.com", ...}, ...]}

    Or a single flat object (one row).
    """
    if not isinstance(body, dict):
        raise AdapterError("request body must be a JSON object")

    raw_rows = body.get("rows")
    if raw_rows is None:
        # Treat the entire body as a single row.
        raw_rows = [body]
    elif not isinstance(raw_rows, list):
        raise AdapterError("'rows' must be an array of objects")
    elif not raw_rows:
        raise AdapterError("'rows' is empty — nothing to evaluate")

    out: list[RowInput] = []
    for i, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            raise AdapterError(f"row {i} is not a JSON object")
        external_id = str(row.pop("_external_id", row.pop("external_id", "")))
        flat = {str(k): str(v) if v is not None else "" for k, v in row.items()}
        out.append(RowInput(data=flat, external_id=external_id or f"row-{i}"))
    return out


# ---------------------------------------------------------------------------
# Clay
# ---------------------------------------------------------------------------

def parse_clay(body: dict[str, Any]) -> list[RowInput]:
    """Parse a Clay webhook payload.

    Clay's webhook integration sends row data as configured by the user.
    The two common shapes are:

    1. **Batch** — ``{"rows": [{...}, ...]}`` where each object is a Clay row
       with whatever columns the user mapped.
    2. **Single row** — a flat object with the row's fields directly.

    Clay lets the user define the payload, so we accept any field names and
    rely on revgate's alias table to resolve them. If the payload doesn't
    look like either shape, we fail closed.
    """
    if not isinstance(body, dict):
        raise AdapterError("Clay payload must be a JSON object")

    raw_rows = body.get("rows")
    if raw_rows is None:
        raw_rows = body.get("data", body.get("records"))
    if raw_rows is None:
        # Single-row: treat the body itself as one row.
        if body.get("Company") or body.get("company") or body.get("Domain") or body.get("domain"):
            raw_rows = [body]
        else:
            raise AdapterError(
                "Clay payload has no 'rows' array and does not look like a single row. "
                "Send {\"rows\": [{...}]} or a flat object with company/domain fields."
            )
    elif not isinstance(raw_rows, list):
        raise AdapterError("Clay 'rows' must be an array")
    elif not raw_rows:
        raise AdapterError("Clay 'rows' is empty — nothing to evaluate")

    out: list[RowInput] = []
    for i, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            raise AdapterError(f"Clay row {i} is not a JSON object")
        # Extract external_id from the outer row before unwrapping.
        external_id = str(row.pop("_external_id", row.pop("id", row.pop("row_id", ""))))
        # Clay may wrap row data under a "data" or "values" key.
        if "data" in row and isinstance(row["data"], dict) and len(row["data"]) > 1:
            row = row["data"]
        elif "values" in row and isinstance(row["values"], dict):
            row = row["values"]
        flat = {str(k): str(v) if v is not None else "" for k, v in row.items()}
        out.append(RowInput(data=flat, external_id=external_id or f"clay-row-{i}"))
    return out


# ---------------------------------------------------------------------------
# HubSpot
# ---------------------------------------------------------------------------

def _flatten_hubspot_properties(props: dict[str, Any]) -> dict[str, str]:
    """Flatten HubSpot's property format to plain key-value.

    HubSpot sends properties in two shapes depending on API version:

    - Newer: ``{"firstname": "John", "lastname": "Doe"}``
    - Older: ``{"firstname": {"value": "John"}, "lastname": {"value": "Doe"}}``

    Both are flattened to ``{"firstname": "John", "lastname": "Doe"}``.
    """
    flat: dict[str, str] = {}
    for k, v in props.items():
        if isinstance(v, dict) and "value" in v:
            flat[str(k)] = str(v["value"]) if v["value"] is not None else ""
        elif v is not None:
            flat[str(k)] = str(v)
    return flat


def parse_hubspot(body: dict[str, Any]) -> list[RowInput]:
    """Parse a HubSpot webhook payload.

    HubSpot workflows trigger webhooks with contact and/or company data in a
    nested format::

        {
          "contact": {
            "vid": 12345,
            "properties": {"firstname": "John", "email": "john@acme.com", ...}
          },
          "company": {
            "properties": {"name": "Acme Corp", "domain": "acme.com", ...}
          }
        }

    The adapter flattens contact and company properties into one row dict,
    merging company fields alongside contact fields. If both are present,
    company fields are prefixed with nothing (they map directly to revgate's
    ``company``, ``domain``, etc. via the alias table).
    """
    if not isinstance(body, dict):
        raise AdapterError("HubSpot payload must be a JSON object")

    # HubSpot may send an array of events (batch webhook).
    if "events" in body and isinstance(body["events"], list):
        return [r for event in body["events"] for r in parse_hubspot(event)]

    row: dict[str, str] = {}
    external_id = ""

    contact = body.get("contact") or body.get("Contact")
    if contact and isinstance(contact, dict):
        vid = contact.get("vid") or contact.get("id") or ""
        external_id = f"contact-{vid}" if vid else ""
        props = contact.get("properties", contact)
        if isinstance(props, dict):
            row.update(_flatten_hubspot_properties(props))

    company = body.get("company") or body.get("Company")
    if company and isinstance(company, dict):
        cid = company.get("companyId") or company.get("id") or ""
        if cid and not external_id:
            external_id = f"company-{cid}"
        props = company.get("properties", company)
        if isinstance(props, dict):
            row.update(_flatten_hubspot_properties(props))

    # If no nested contact/company, treat the body as a flat row.
    if not row:
        if "properties" in body and isinstance(body["properties"], dict):
            row.update(_flatten_hubspot_properties(body["properties"]))
        elif any(k in body for k in ("email", "firstname", "lastname", "phone", "company", "domain")):
            row = {str(k): str(v) if v is not None else "" for k, v in body.items()}

    if not row:
        raise AdapterError("HubSpot payload has no contact or company properties to evaluate")

    return [RowInput(data=row, external_id=external_id or "hubspot-1")]


# ---------------------------------------------------------------------------
# Apollo
# ---------------------------------------------------------------------------

def parse_apollo(body: dict[str, Any]) -> list[RowInput]:
    """Parse an Apollo webhook payload.

    Apollo sends prospect data in a nested format::

        {
          "prospect": {
            "id": "abc123",
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@acme.com",
            "phone": "+1 415 555 0142",
            "title": "CEO",
            "organization": {
              "name": "Acme Corp",
              "domain": "acme.com",
              "size": "250"
            }
          }
        }

    The adapter flattens prospect and organization fields into one row dict.
    """
    if not isinstance(body, dict):
        raise AdapterError("Apollo payload must be a JSON object")

    # Apollo may send a batch.
    if "prospects" in body and isinstance(body["prospects"], list):
        return [r for p in body["prospects"] for r in parse_apollo({"prospect": p})]

    prospect = body.get("prospect") or body.get("Prospect")
    if not prospect:
        # Maybe the body itself is the prospect.
        if body.get("email") or body.get("first_name"):
            prospect = body
        else:
            raise AdapterError(
                "Apollo payload has no 'prospect' object. "
                "Send {\"prospect\": {...}} or a flat object with email/first_name."
            )

    if not isinstance(prospect, dict):
        raise AdapterError("Apollo 'prospect' must be a JSON object")

    external_id = str(prospect.get("id", prospect.get("prospect_id", "")))
    row: dict[str, str] = {}

    # Flatten prospect fields (skip nested "organization" for now).
    for k, v in prospect.items():
        if k == "organization" or k == "Organization":
            continue
        if v is not None and not isinstance(v, (dict, list)):
            row[str(k)] = str(v)

    # Flatten organization fields.
    org = prospect.get("organization") or prospect.get("Organization")
    if org and isinstance(org, dict):
        for k, v in org.items():
            if v is not None and not isinstance(v, (dict, list)):
                row[str(k)] = str(v)

    if not row:
        raise AdapterError("Apollo prospect has no fields to evaluate")

    return [RowInput(data=row, external_id=external_id or "apollo-1")]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ADAPTERS: dict[str, Any] = {
    "generic": parse_generic,
    "clay": parse_clay,
    "hubspot": parse_hubspot,
    "apollo": parse_apollo,
}


def get_adapter(source: str):
    """Return the parser for a source, or raise if unknown.

    An unknown source is fail-closed: the server returns BLOCKED, because we
    will not evaluate a payload from a system we do not recognise.
    """
    adapter = ADAPTERS.get(source)
    if adapter is None:
        valid = ", ".join(sorted(ADAPTERS))
        raise AdapterError(f"unknown source {source!r}; expected one of: {valid}")
    return adapter
