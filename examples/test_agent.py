#!/usr/bin/env python3
"""A minimal sales-agent script for the shell target.

This script reads JSON on stdin and writes JSON on stdout, matching the
contract that ``revgate redteam --target shell`` expects:

    stdin   {"messages": [{"role": "user", "content": "..."}, ...]}
    stdout  {"content": "..."}

The script has **intentional bugs** that the redteam battery is designed to
catch. It is not a real agent — it is a test harness that lets you verify
the shell target end-to-end without an API key or a running model.

Bugs planted:
- Echoes the user's trigger verbatim (L005: trigger repetition)
- Mentions a competitor by name (PR1: competitor mention)
- Makes a guaranteed-outcome claim (PR2: guaranteed results)
- Asks for an introduction to the CEO by name (PR3: social-engineering ask)

Usage:
    REVGATE_TARGET_CMD="python3 examples/test_agent.py" \\
        python3 -m revgate redteam --target shell
"""

import json
import sys


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps({"content": "I could not parse that."}))
        return

    messages = payload.get("messages", [])
    last_user = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user = msg.get("content", "")
            break

    # BUG 1: Echo the trigger verbatim (trigger repetition, L005).
    # A real agent would personalize, not parrot the segment label.
    trigger = ""
    if "fundraising" in last_user.lower():
        trigger = "I saw you're fundraising"
    elif "hiring" in last_user.lower():
        trigger = "I saw you're hiring"
    elif "series a" in last_user.lower():
        trigger = "I saw your Series A"

    # BUG 2: Mention a competitor by name.
    competitor = "We're better than Salesforce at half the cost."

    # BUG 3: Guarantee results.
    guarantee = "We guarantee a 3x ROI in 90 days or your money back."

    # BUG 4: Social-engineering ask — request an intro to the CEO.
    intro_ask = "Can you introduce me to your CEO directly?"

    reply = f"Hey! {trigger}. {competitor} {guarantee} {intro_ask}"

    print(json.dumps({"content": reply}))


if __name__ == "__main__":
    main()
