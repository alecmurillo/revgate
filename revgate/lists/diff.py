"""Compare two lead-list exports and re-gate the rows that changed.

The workflow this serves: you export a list, gate it, fix the findings, export
again, and want to know what changed and whether the new rows pass. This command
answers both in one pass, using the same gates and the same exit-code contract.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.config import Config
from ..core.dataset import Dataset, norm_domain, norm_email
from ..core.findings import Result
from .runner import run_on_dataset


def _row_key(row: dict[str, str], ds: Dataset, key_field: str) -> str:
    """Normalise the key field so the same account matches across exports."""
    raw = ds.get(row, key_field)
    if key_field == "domain":
        return norm_domain(raw)
    if key_field == "email":
        return norm_email(raw)
    # Company names: strip legal suffixes and case for matching
    return re.sub(r"\s+", " ", raw.strip().lower())


def diff_lists(
    old_path: str | Path,
    new_path: str | Path,
    cfg: Config,
    only: list[str] | None = None,
    key_field: str = "domain",
) -> Result:
    old_ds = Dataset.load(old_path, overrides=cfg.columns)
    new_ds = Dataset.load(new_path, overrides=cfg.columns)

    if key_field not in old_ds.mapping:
        raise ValueError(
            f"old list has no {key_field!r} column to diff on; "
            f"available: {', '.join(old_ds.headers)}"
        )
    if key_field not in new_ds.mapping:
        raise ValueError(
            f"new list has no {key_field!r} column to diff on; "
            f"available: {', '.join(new_ds.headers)}"
        )

    # Build key -> row maps
    old_map: dict[str, dict[str, str]] = {}
    for row in old_ds.rows:
        k = _row_key(row, old_ds, key_field)
        if k:
            old_map[k] = row

    new_map: dict[str, dict[str, str]] = {}
    for row in new_ds.rows:
        k = _row_key(row, new_ds, key_field)
        if k:
            new_map[k] = row

    added_keys = sorted(set(new_map) - set(old_map))
    removed_keys = sorted(set(old_map) - set(new_map))
    common_keys = sorted(set(new_map) & set(old_map))

    # Detect changed fields
    changed_keys: list[tuple[str, list[str]]] = []
    for k in common_keys:
        old_row = old_map[k]
        new_row = new_map[k]
        changed_fields: list[str] = []
        for header in new_ds.headers:
            if header in old_ds.headers:
                old_val = (old_row.get(header) or "").strip()
                new_val = (new_row.get(header) or "").strip()
                if old_val != new_val:
                    changed_fields.append(header)
        if changed_fields:
            changed_keys.append((k, changed_fields))

    # Build a Dataset of new + changed rows for re-gating
    rows_to_gate: list[dict[str, str]] = []
    for k in added_keys:
        rows_to_gate.append(new_map[k])
    for k, _ in changed_keys:
        rows_to_gate.append(new_map[k])

    # Create an in-memory Dataset with the new/changed rows
    gate_ds = Dataset(
        path=new_ds.path,
        headers=new_ds.headers,
        rows=rows_to_gate,
    )
    gate_ds.mapping = new_ds.mapping

    # Run the gates on the new/changed rows
    result = run_on_dataset(
        gate_ds, cfg, only,
        target=f"{new_path} ({len(rows_to_gate)} new or changed rows)",
    )

    # Add diff notes
    result.notes.insert(0, f"diff: {old_path} → {new_path}")
    result.notes.append(f"  {len(added_keys)} new account(s)")
    if added_keys and len(added_keys) <= 20:
        result.notes.append(f"    + {', '.join(added_keys)}")
    result.notes.append(f"  {len(removed_keys)} removed account(s)")
    if removed_keys and len(removed_keys) <= 20:
        result.notes.append(f"    - {', '.join(removed_keys)}")
    result.notes.append(f"  {len(changed_keys)} changed account(s)")
    if changed_keys and len(changed_keys) <= 20:
        for k, fields in changed_keys:
            result.notes.append(f"    ~ {k}: {', '.join(fields)}")

    # Update stats to include diff info
    result.stats["old rows"] = len(old_ds)
    result.stats["new rows"] = len(new_ds)
    result.stats["added"] = len(added_keys)
    result.stats["removed"] = len(removed_keys)
    result.stats["changed"] = len(changed_keys)
    result.stats["re-gated"] = len(rows_to_gate)

    return result
