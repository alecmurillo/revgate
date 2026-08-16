---
name: revgate-list-review
description: Gate an outbound lead list before it is sent. Use when the user has a CSV of leads, prospects or accounts and wants it checked for suppression collisions, unrendered merge fields, stale contact recency, restricted jurisdictions or missing triggers, or when a revgate lint run has produced findings that need triage.
---

# Reviewing an outbound lead list

A lead list is code that runs once, against real people, and cannot be rolled back.
This skill runs the gate and then does the part the gate cannot: deciding which
findings are the list's fault and which are the pipeline's.

## 1. Run the gate first

```bash
python3 -m revgate lint <path-to-csv> --format text
```

Do not read the CSV row by row before doing this. The gate reads all of it in
milliseconds and reports with row numbers that match what the operator sees in a
spreadsheet. Your attention is worth more on the findings than on the parsing.

If the command exits 3, the arguments or config are wrong. Fix that before
interpreting anything: a usage error is not a clean list.

## 2. Read the skip list before the findings

The report prints skipped gates above findings, and that ordering is deliberate.
A skipped gate is not a passed gate. If the suppression source was missing, L001
did not run, and the absence of suppression findings means nothing at all.

Any skip marked blocking means the verdict is BLOCKED regardless of how few
findings there are. Say so explicitly in your summary rather than leading with a
low finding count.

## 3. Triage by cause, not by severity

Every finding carries an `origin` field: the specific mistake the gate exists to
prevent. Use it. The severity tells you whether the send is blocked; the origin
tells you where the bug actually is.

Sort the findings into three buckets and report them that way:

- **Row-level defects.** One or two rows are wrong; the pipeline is fine. Remove
  the rows. Example: two entries on a do-not-call export.
- **Pipeline defects.** The rows are symptoms. `L006 unrendered-copy` firing on
  five rows means the render step has no fallback for an empty merge field, and
  fixing five cells leaves the bug in place for the next list. Say which stage
  needs the fix.
- **Motion defects.** The list is technically correct and strategically wrong.
  `L012 headcount-floor` firing means somebody filtered on company size instead
  of ranking on it, and the fix is a decision, not an edit.

The distinction between the second and third bucket is the one people get wrong.
A pipeline defect is a bug. A motion defect is a choice that should be made
deliberately by a human, and your job is to surface it, not to resolve it.

## 4. Propose fixes upstream of the file

For every pipeline defect, name the stage that should have caught it and the
change that would stop the class of error, not the instance. "Add a fallback for
`first_name` and assert the sentence still reads if it is empty" is a fix.
"Delete row 15" is a patch.

## 5. Re-run before claiming it is clean

```bash
python3 -m revgate lint <path-to-csv> --format text
```

Exit 0 with zero blocking skips is the only clean result. Report the exit code
you actually observed. If you did not re-run the gate, say that instead of
implying the list is clear.

## Machine-readable output

For CI or for feeding another tool:

```bash
python3 -m revgate lint <path-to-csv> --format json --out findings.json
python3 -m revgate lint <path-to-csv> --format md --out review.md   # PR comments
```

Add `--strict` to make advisory findings blocking. Use it when the send is large
enough that P1 volume matters more than P1 severity.

## Reference

`python3 -m revgate rules` prints all thirteen gates with the origin of each.
Read it before proposing a new gate, and read the config section of the README
before concluding that a gate is wrong: several are tuned by `revgate.toml`
rather than being hard-coded.
