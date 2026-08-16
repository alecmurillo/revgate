"""revgate — fail-closed QA for the artifacts that touch your prospects.

Two surfaces, one severity policy:

- `revgate lint` gates a lead list before it is dialled or sent.
- `revgate redteam` gates a customer-facing AI agent before it talks to anyone.

Both refuse to report a pass for a check they could not run.
"""

__version__ = "0.1.0"
