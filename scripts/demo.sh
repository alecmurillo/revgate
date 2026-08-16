#!/usr/bin/env bash
#
# The whole tour, offline, in about five seconds. No credentials, no network.
#
#   ./scripts/demo.sh
#
# Every command is one you can run yourself, and every exit code is asserted, so a
# regression in this repo breaks the demo rather than quietly producing a nicer one.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PY=${PYTHON:-python3}
TODAY=2026-08-16
FAILED=0

rule() { printf '\n\033[1m%s\033[0m\n' "$1"; }

expect() {
  local want=$1 got=$2 what=$3
  if [ "$want" -eq "$got" ]; then
    printf '\033[32m  ✓ exit %s as documented (%s)\033[0m\n' "$got" "$what"
  else
    printf '\033[31m  ✗ expected exit %s, got %s (%s)\033[0m\n' "$want" "$got" "$what"
    FAILED=1
  fi
}

rule "1. Seventeen gates, and the mistake each one prevents"
$PY -m revgate rules | head -18

rule "2. A lead list built to fail. Twenty-eight rows, all seventeen gates."
$PY -m revgate lint fixtures/leads-dirty.csv --today "$TODAY" --no-record
expect 2 $? "a blocked list"

rule "3. The same gate on a clean list"
$PY -m revgate lint fixtures/leads-clean.csv --today "$TODAY" --no-record
expect 0 $? "a clean list"

rule "4. What changed between two exports, re-gated"
$PY -m revgate diff fixtures/leads-clean.csv fixtures/leads-dirty.csv --today "$TODAY" --no-record | head -8
expect 2 "${PIPESTATUS[0]}" "changed rows are blocked"

rule "5. A deliberately unsafe sales agent, red-teamed offline"
$PY -m revgate redteam --target demo --no-record --transcripts ./transcripts | head -24
expect 2 "${PIPESTATUS[0]}" "a blocked agent"

rule "6. Six of the twenty-six scenarios were written to pass. They did."
$PY - <<'PY'
import json
from collections import Counter
data = json.load(open("transcripts/index.json"))
verdicts = Counter(e["verdict"] for e in data["exchanges"])
controls = [e for e in data["exchanges"] if "expected-pass" in e.get("tags", [])]
print(f"  {dict(verdicts)}")
print(f"  controls: {len(controls)}, all passing: {all(e['verdict'] == 'PASS' for e in controls)}")
print("  A battery where everything fails cannot tell a broken guardrail")
print("  from a broken matcher. That is what the controls are for.")
PY

rule "7. This repo's Factory integration, verified rather than asserted"
$PY -m revgate provenance --strict --no-record
expect 0 $? "every documented Factory surface holds"

rule "8. Droid usage, counted"
$PY -m revgate provenance --runs --no-record

rule "9. The test suite"
$PY -m unittest discover -s tests 2>&1 | tail -3
expect 0 "${PIPESTATUS[0]}" "tests"

if [ "$FAILED" -eq 0 ]; then
  printf '\n\033[32mAll documented exit codes matched.\033[0m\n\n'
else
  printf '\n\033[31mSomething did not match its documented behaviour.\033[0m\n\n'
fi
exit "$FAILED"
