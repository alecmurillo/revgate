"""HTTP gating API and system adapters.

The API layer is a transport, not a logic layer. It accepts JSON from any
source (Clay, HubSpot, Apollo, or a raw curl), constructs a ``Dataset`` from
the rows, calls ``run_on_dataset`` — the same function the CLI calls — and
serializes the ``Result`` in a stable versioned schema.

The fail-closed invariant holds at the API level: a malformed payload, a
missing required field, or an adapter that cannot map the incoming format all
produce a BLOCKED response, never a silent PASS.
"""
