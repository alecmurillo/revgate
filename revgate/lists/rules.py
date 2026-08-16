"""The gates.

Each rule encodes one mistake that costs money when it ships. The `origin` field
on every finding is the reason the gate exists, kept next to the code so the next
person to find it inconvenient has to argue with the reason rather than delete an
unexplained check.

Adding a gate: write a `_check_*` function with the signature
`(ds, cfg, ctx) -> list[Finding]`, then add a `Rule` entry to `RULES`. A rule that
cannot evaluate must call `ctx.skip(...)` and return `[]`; it must never return an
empty list to mean "clean".
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from ..core.config import Config
from ..core.dataset import (
    Dataset,
    email_domain,
    norm_domain,
    norm_email,
    norm_phone,
    parse_int,
)
from ..core.findings import Finding, Severity, Skipped

P0, P1, P2 = Severity.P0, Severity.P1, Severity.P2


@dataclass
class Context:
    """Reference data loaded once and shared by every gate."""

    suppression: dict[str, set[str]] | None = None
    suppression_path: Path | None = None
    dnc: set[str] | None = None
    dnc_path: Path | None = None
    skips: list[Skipped] = field(default_factory=list)

    def skip(self, rule: str, reason: str, *, blocking: bool = False) -> None:
        self.skips.append(Skipped(rule=rule, reason=reason, blocking=blocking))


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    severity: Severity
    summary: str
    origin: str
    check: Callable[[Dataset, Config, Context], list[Finding]]


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------

_US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "puerto rico": "PR", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
_STATE_CODES = set(_US_STATES.values())

_LEGAL_SUFFIXES = {
    "inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "plc",
    "gmbh", "ag", "sa", "sas", "bv", "nv", "ab", "oy", "as", "pty", "srl", "spa",
    "kk", "group", "holdings", "technologies", "technology", "labs", "software",
    "solutions", "systems", "services", "the", "and",
}

_DATE_FORMATS = (
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%m-%Y", "%m-%d-%Y",
    "%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%Y%m%d",
)

_ADDRESS_ENTITY = re.compile(
    r"^\s*\d+\s+[\w'’.\- ]+?\b(street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|court|ct|place|pl|highway|hwy)\b",
    re.IGNORECASE,
)

# Each entry: (pattern, label, explanation)
_COPY_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\{\{[^}]{0,80}\}\}"), "unrendered merge field",
     "a handlebars placeholder survived the render and will send literally"),
    (re.compile(r"(?<![\w}])\{[A-Za-z_][A-Za-z0-9_. ]{0,40}\}"), "unrendered merge field",
     "a single-brace placeholder survived the render and will send literally"),
    (re.compile(r"\[\[[^\]]{0,60}\]\]"), "unrendered merge field",
     "a bracket placeholder survived the render and will send literally"),
    (re.compile(r"<[A-Za-z_][A-Za-z0-9_ ]{0,30}>"), "unrendered merge field",
     "an angle-bracket placeholder survived the render and will send literally"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "raw date",
     "a machine-formatted date reached the copy instead of a month name"),
    (re.compile(r"(?<![\d.,$])\d{7,}(?!\d)"), "raw number",
     "an unformatted number reached the copy instead of a rounded figure"),
    (re.compile(r"(?<=[^\s.!?:;]) {2,}(?=\S)"), "collapsed merge field",
     "a double space mid-sentence, the signature of a merge field that rendered empty"),
    (re.compile(r",\s*,|\s,|\(\s*\)|\s\."), "dangling punctuation",
     "punctuation left stranded by a merge field that rendered empty"),
)


def parse_date(value: str) -> date | None:
    s = (value or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    if s.isdigit() and len(s) in (10, 13):
        try:
            return datetime.fromtimestamp(int(s) / (1000 if len(s) == 13 else 1), tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    return None


def norm_state(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    if len(s) == 2 and s.upper() in _STATE_CODES:
        return s.upper()
    return _US_STATES.get(s.lower(), s.upper())


def name_tokens(company: str) -> list[str]:
    raw = re.split(r"[^A-Za-z0-9]+", (company or "").lower())
    return [t for t in raw if t and t not in _LEGAL_SUFFIXES]


def _norm_trigger(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().strip(".,;:!-–—").lower())


# --------------------------------------------------------------------------
# L001 — suppression collision
# --------------------------------------------------------------------------

def _check_suppression(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L001"
    if ctx.suppression is None:
        ctx.skip(rule, "no suppression source configured; set [lint.sources].suppression or pass --suppress")
        return []
    if not (ctx.suppression.get("domain") or ctx.suppression.get("email")):
        ctx.skip(
            rule,
            f"suppression source {ctx.suppression_path} yielded no domains or emails, "
            "so every row would pass unchecked",
            blocking=True,
        )
        return []
    if not ds.has("domain") and not ds.has("email"):
        ctx.skip(rule, "list has neither a domain nor an email column to match on")
        return []

    known_domains = ctx.suppression.get("domain", set())
    known_emails = ctx.suppression.get("email", set())
    out: list[Finding] = []
    for n, row in ds.enumerate_rows():
        email = norm_email(ds.get(row, "email"))
        domain = norm_domain(ds.get(row, "domain")) or email_domain(email)
        hit = ""
        if email and email in known_emails:
            hit = f"email {email}"
        elif domain and domain in known_domains:
            hit = f"domain {domain}"
        if hit:
            out.append(Finding(
                rule=rule, severity=P0,
                title="Already present in the suppression source",
                detail=f"{hit} already appears in {ctx.suppression_path.name if ctx.suppression_path else 'the suppression source'}",
                remedy="Remove the row before enrichment runs. Suppress first, spend credits second.",
                origin=(
                    "Suppressing after enrichment pays a vendor to tell you about somebody you "
                    "already know, then puts a second rep on an account that is already owned."
                ),
                row=n, key=ds.label(row),
            ))
    return out


# --------------------------------------------------------------------------
# L002 — recently contacted
# --------------------------------------------------------------------------

def _check_recent_contact(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L002"
    if not ds.has("last_contacted"):
        ctx.skip(rule, "list has no last-contacted column, so recency cannot be checked")
        return []

    today = cfg.reference_date()
    window = cfg.recent_contact_days
    out: list[Finding] = []
    unparseable = 0
    for n, row in ds.enumerate_rows():
        raw = ds.get(row, "last_contacted")
        if not raw:
            continue
        when = parse_date(raw)
        if when is None:
            unparseable += 1
            continue
        age = (today - when).days
        if 0 <= age <= window:
            out.append(Finding(
                rule=rule, severity=P0,
                title=f"Contacted within the last {window} days",
                detail=f"last contacted {raw} ({age} day{'s' if age != 1 else ''} ago)",
                remedy=f"Hold the row until it is older than {window} days, or route it to the rep who already owns the thread.",
                origin=(
                    "Deal stage and lead status both miss somebody who was called yesterday. "
                    "The recency field is the only one that catches a live conversation."
                ),
                row=n, key=ds.label(row), column=ds.column("last_contacted"),
            ))
    if unparseable:
        out.append(Finding(
            rule=rule, severity=P1,
            title="Last-contacted dates that could not be parsed",
            detail=f"{unparseable} row(s) carry an unrecognised date format and were not gated for recency",
            remedy="Normalise the column to YYYY-MM-DD before linting, or those rows bypass the recency gate entirely.",
            origin="A gate that cannot read its input reports a pass. Unreadable values are reported, never assumed clean.",
            column=ds.column("last_contacted"),
        ))
    return out


# --------------------------------------------------------------------------
# L003 — do-not-call
# --------------------------------------------------------------------------

def _check_dnc(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L003"
    if ctx.dnc is None:
        ctx.skip(rule, "no do-not-call source configured; set [lint.sources].dnc or pass --dnc")
        return []
    if not ctx.dnc:
        ctx.skip(
            rule,
            f"do-not-call source {ctx.dnc_path} contained no usable numbers, so every number "
            "would publish as if it had been checked",
            blocking=True,
        )
        return []
    if not ds.has("phone"):
        ctx.skip(rule, "list has no phone column to match on")
        return []

    out: list[Finding] = []
    for n, row in ds.enumerate_rows():
        phone = norm_phone(ds.get(row, "phone"))
        if phone and phone in ctx.dnc:
            out.append(Finding(
                rule=rule, severity=P0,
                title="Number is on the do-not-call list",
                detail=f"{ds.get(row, 'phone')} normalises to {phone}, which is suppressed",
                remedy="Remove the row. Do not flag it and leave it in the file for a human to notice.",
                origin=(
                    "A number that reaches a dialler has been dialled. Flagging instead of removing "
                    "assumes every downstream consumer reads the flag column."
                ),
                row=n, key=ds.label(row), column=ds.column("phone"),
            ))
    return out


# --------------------------------------------------------------------------
# L004 — restricted jurisdiction
# --------------------------------------------------------------------------

def _check_jurisdiction(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L004"
    if not cfg.restricted_states:
        ctx.skip(rule, "no restricted jurisdictions configured; set [lint].restricted_states")
        return []
    if not ds.has("state"):
        ctx.skip(rule, "list has no state column, so jurisdiction cannot be checked")
        return []

    blocked = {norm_state(s) for s in cfg.restricted_states}
    out: list[Finding] = []
    for n, row in ds.enumerate_rows():
        raw = ds.get(row, "state")
        st = norm_state(raw)
        if st and st in blocked:
            out.append(Finding(
                rule=rule, severity=P0,
                title="Row sits in a restricted jurisdiction",
                detail=f"state {raw or st} is on the restricted list",
                remedy="Remove the row, or route it to a channel cleared for that jurisdiction.",
                origin=(
                    "Jurisdiction rules are the one list-building constraint with a statutory "
                    "penalty attached. They are also invisible in every enrichment vendor's UI."
                ),
                row=n, key=ds.label(row), column=ds.column("state"),
            ))
    return out


# --------------------------------------------------------------------------
# L005 — missing or meaningless trigger
# --------------------------------------------------------------------------

def _check_trigger(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L005"
    if not ds.has("trigger"):
        ctx.skip(
            rule,
            "list has no trigger column at all, which is itself the finding: no row carries a "
            "reason for the outreach",
            blocking=True,
        )
        return []

    generic = {g.lower() for g in cfg.generic_triggers}
    out: list[Finding] = []
    seen: Counter[str] = Counter()

    for n, row in ds.enumerate_rows():
        raw = ds.get(row, "trigger")
        norm = _norm_trigger(raw)
        if not norm:
            out.append(Finding(
                rule=rule, severity=P0,
                title="No trigger on the row",
                detail="the trigger column is empty",
                remedy="Fill it with a specific, checkable event, or drop the row from the send.",
                origin=(
                    "A personalisation system left 99% empty is worse than none: the campaign "
                    "claims a reason for the call and then never states one."
                ),
                row=n, key=ds.label(row), column=ds.column("trigger"),
            ))
            continue
        if norm in generic:
            out.append(Finding(
                rule=rule, severity=P0,
                title="Trigger is a placeholder, not an event",
                detail=f"trigger reads {raw!r}, which asserts nothing a recipient can verify",
                remedy="Replace it with a dated, specific event, or drop the row.",
                origin="'Growing fast' is true of every company a rep has ever called and predicts nothing.",
                row=n, key=ds.label(row), column=ds.column("trigger"),
            ))
            continue
        seen[norm] += 1

    total = len(ds)
    if total >= cfg.min_rows_for_distribution_checks and seen:
        text, count = seen.most_common(1)[0]
        ratio = count / total
        if ratio > cfg.max_trigger_repeat_ratio:
            out.append(Finding(
                rule=rule, severity=P0,
                title="One trigger repeats across most of the list",
                detail=(
                    f"{count} of {total} rows ({ratio:.0%}) carry the identical trigger {text!r}"
                ),
                remedy="A value identical on every row is a segment label. Give each row its own event, or say plainly that this is a segment send.",
                origin=(
                    "A constant column looks like personalisation in the spreadsheet and reads as "
                    "a form letter in the inbox."
                ),
                column=ds.column("trigger"),
            ))
    return out


# --------------------------------------------------------------------------
# L006 — copy that did not finish rendering
# --------------------------------------------------------------------------

def _check_unrendered_copy(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L006"
    targets = [c for c in ("copy", "trigger") if ds.has(c)]
    if not targets:
        ctx.skip(rule, "list has no copy or trigger column to inspect")
        return []

    out: list[Finding] = []
    for n, row in ds.enumerate_rows():
        for logical in targets:
            value = ds.get(row, logical)
            if not value:
                continue
            for pattern, label, explanation in _COPY_PATTERNS:
                m = pattern.search(value)
                if not m:
                    continue
                excerpt = value[max(0, m.start() - 30): m.end() + 30].strip()
                out.append(Finding(
                    rule=rule, severity=P0,
                    title=f"Copy contains {label}",
                    detail=f"{explanation} — …{excerpt}…",
                    remedy="Render and format values before they reach the sending tool. Every merge field needs a fallback, and the sentence has to survive that fallback being empty.",
                    origin=(
                        "Sending tools print whatever is in the cell. A raw timestamp, a nine-digit "
                        "number, or a hole where a merge field should be all ship exactly as stored."
                    ),
                    row=n, key=ds.label(row), column=ds.column(logical),
                ))
                break
    return out


# --------------------------------------------------------------------------
# L007 — unverified email
# --------------------------------------------------------------------------

def _check_email_verified(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L007"
    if not ds.has("email_status"):
        ctx.skip(rule, "list carries no email verification status column")
        return []

    ok = {s.lower() for s in cfg.verified_email_statuses}
    out: list[Finding] = []
    for n, row in ds.enumerate_rows():
        status = ds.get(row, "email_status").strip().lower()
        if not status:
            out.append(Finding(
                rule=rule, severity=P1,
                title="Email carries no verification status",
                detail="the verification column is empty for this row",
                remedy="Verify before sending, or move the row to a channel where a bounce costs nothing.",
                origin="An unverified address is a coin flip charged against the sending domain's reputation.",
                row=n, key=ds.label(row), column=ds.column("email_status"),
            ))
            continue
        if status in ok:
            continue
        catch_all = "catch" in status
        out.append(Finding(
            rule=rule, severity=P1,
            title="Catch-all domain accepted as verified" if catch_all else "Email is not verified",
            detail=f"verification status is {status!r}",
            remedy="Drop catch-all and unverified addresses from the send.",
            origin=(
                "A catch-all domain accepts any address, so it passes verification and then bounces. "
                "That is how a campaign reaches a bounce rate that suspends the domain."
            ),
            row=n, key=ds.label(row), column=ds.column("email_status"),
        ))
    return out


# --------------------------------------------------------------------------
# L008 — mailbox shape
# --------------------------------------------------------------------------

def _check_mailbox_shape(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L008"
    if not ds.has("email"):
        ctx.skip(rule, "list has no email column")
        return []

    roles = {r.lower() for r in cfg.role_mailboxes}
    free = {f.lower() for f in cfg.free_email_domains}
    out: list[Finding] = []
    for n, row in ds.enumerate_rows():
        email = norm_email(ds.get(row, "email"))
        if not email or "@" not in email:
            continue
        local, _, host = email.partition("@")
        host = norm_domain(host)
        base_local = re.split(r"[.\-+_]", local)[0]
        if base_local in roles or local in roles:
            out.append(Finding(
                rule=rule, severity=P2,
                title="Shared mailbox, not a person",
                detail=f"{email} is a role address",
                remedy="Find the individual, or accept that the reply lands in a queue nobody owns.",
                origin="A role mailbox has no owner, so a reply to it is nobody's job.",
                row=n, key=ds.label(row), column=ds.column("email"),
            ))
            continue
        if host in free:
            out.append(Finding(
                rule=rule, severity=P2,
                title="Personal mailbox on a free provider",
                detail=f"{email} is hosted on {host}",
                remedy="Confirm this is really the work address before treating the row as a business contact.",
                origin="A free-provider address on a B2B list usually means the enrichment guessed.",
                row=n, key=ds.label(row), column=ds.column("email"),
            ))
            continue
        company_domain = norm_domain(ds.get(row, "domain"))
        if company_domain and host and host != company_domain and not (
            host.endswith("." + company_domain) or company_domain.endswith("." + host)
        ):
            out.append(Finding(
                rule=rule, severity=P2,
                title="Email domain does not match the company domain",
                detail=f"{email} does not sit on {company_domain}",
                remedy="Reconcile the two columns. One of them is about a different company.",
                origin="Two domains on one row means the join was wrong somewhere upstream.",
                row=n, key=ds.label(row), column=ds.column("email"),
            ))
    return out


# --------------------------------------------------------------------------
# L009 — name/domain mismatch
# --------------------------------------------------------------------------

def _check_name_domain(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L009"
    if not ds.has("company", "domain"):
        missing = ", ".join(ds.missing("company", "domain"))
        ctx.skip(rule, f"needs both a company and a domain column (missing: {missing})")
        return []

    out: list[Finding] = []
    for n, row in ds.enumerate_rows():
        company = ds.get(row, "company")
        domain = norm_domain(ds.get(row, "domain"))
        if not company or not domain:
            continue
        label = domain.split(".")[0]
        tokens = name_tokens(company)
        if not tokens:
            continue
        joined = "".join(tokens)
        acronym = "".join(t[0] for t in tokens)
        matched = (
            joined in label
            or label in joined
            or any(t in label for t in tokens if len(t) >= 4)
            or (len(acronym) >= 3 and acronym == label)
        )
        if not matched:
            out.append(Finding(
                rule=rule, severity=P1,
                title="Company name and domain do not correspond",
                detail=f"{company!r} against {domain}: no shared token",
                remedy="Confirm the domain by hand before spending an enrichment credit or writing a first line about the wrong company.",
                origin=(
                    "Name matching silently resolves to the wrong company. Generic one-word names "
                    "are the worst offenders and enrichment vendors guess at them confidently."
                ),
                row=n, key=ds.label(row), column=ds.column("domain"),
            ))
    return out


# --------------------------------------------------------------------------
# L010 — not an operating company
# --------------------------------------------------------------------------

def _check_entity_type(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L010"
    if not ds.has("company"):
        ctx.skip(rule, "list has no company column")
        return []

    terms = [t.lower() for t in cfg.entity_terms]
    out: list[Finding] = []
    for n, row in ds.enumerate_rows():
        company = ds.get(row, "company")
        if not company:
            continue
        low = company.lower()
        if _ADDRESS_ENTITY.search(company):
            out.append(Finding(
                rule=rule, severity=P1,
                title="Row is a property entity, not a company",
                detail=f"{company!r} is an address wearing a corporate suffix",
                remedy="Strip address-shaped entities before the list is sized or costed.",
                origin="Regulatory filing sources are full of single-asset entities that have no staff to sell to.",
                row=n, key=ds.label(row), column=ds.column("company"),
            ))
            continue
        hit = next((t for t in terms if re.search(rf"\b{re.escape(t)}\b", low)), None)
        if hit:
            out.append(Finding(
                rule=rule, severity=P1,
                title="Row looks like an investment vehicle, not an operating company",
                detail=f"{company!r} contains {hit!r}",
                remedy="Confirm it employs people and buys software before it stays on the list.",
                origin=(
                    "Public filing sources are majority funds and holding entities. They pass every "
                    "firmographic filter and buy nothing."
                ),
                row=n, key=ds.label(row), column=ds.column("company"),
            ))
    return out


# --------------------------------------------------------------------------
# L011 / L012 — headcount policy
# --------------------------------------------------------------------------

def _check_headcount_exclusion(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L011"
    if not ds.has("headcount"):
        ctx.skip(rule, "list has no headcount column")
        return []

    ceiling = cfg.headcount_exclude_above
    out: list[Finding] = []
    for n, row in ds.enumerate_rows():
        size = parse_int(ds.get(row, "headcount"))
        if size is not None and size > ceiling:
            out.append(Finding(
                rule=rule, severity=P1,
                title=f"Headcount above the configured ceiling of {ceiling}",
                detail=f"{size} employees",
                remedy="Route to a motion built for that size, or exclude the row.",
                origin=(
                    "Size belongs in the score, with one exception: past a ceiling the motion itself "
                    "is wrong, and that exclusion should be explicit rather than emergent."
                ),
                row=n, key=ds.label(row), column=ds.column("headcount"),
            ))
    return out


def _check_headcount_floor(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L012"
    if not ds.has("headcount"):
        ctx.skip(rule, "list has no headcount column")
        return []

    sizes = [parse_int(ds.get(row, "headcount")) for _, row in ds.enumerate_rows()]
    known = [s for s in sizes if s is not None]
    if len(known) < cfg.min_rows_for_distribution_checks:
        ctx.skip(
            rule,
            f"only {len(known)} row(s) carry a headcount, below the {cfg.min_rows_for_distribution_checks} "
            "needed before a distribution claim means anything",
        )
        return []

    floor = min(known)
    if floor >= cfg.headcount_floor_warn:
        return [Finding(
            rule=rule, severity=P2,
            title="List appears to have been filtered on company size",
            detail=(
                f"smallest headcount on the list is {floor}; nothing below it survived, "
                f"across {len(known)} rows"
            ),
            remedy="Score size instead of filtering on it. Keep the small accounts and rank them lower.",
            origin=(
                "A minimum-headcount filter is the most expensive default in outbound: the smallest "
                "band is usually both the largest share of volume and the best close rate."
            ),
            column=ds.column("headcount"),
        )]
    return []


# --------------------------------------------------------------------------
# L013 — duplicate accounts
# --------------------------------------------------------------------------

def _check_duplicates(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L013"
    if not ds.has("domain"):
        ctx.skip(rule, "list has no domain column to group on")
        return []

    groups: dict[str, list[int]] = defaultdict(list)
    for n, row in ds.enumerate_rows():
        domain = norm_domain(ds.get(row, "domain"))
        if domain:
            groups[domain].append(n)

    out: list[Finding] = []
    for domain, rows in sorted(groups.items()):
        if len(rows) > 1:
            out.append(Finding(
                rule=rule, severity=P1,
                title="Same account appears more than once",
                detail=f"{domain} appears on rows {', '.join(str(r) for r in rows)}",
                remedy="Collapse to one row per account, or confirm the motion intends multiple contacts and says so.",
                origin=(
                    "Two rows on one account become two reps on one account, which the account "
                    "notices before either rep does."
                ),
                key=domain, column=ds.column("domain"),
            ))
    return out


# --------------------------------------------------------------------------
# L014 — duplicate phone across accounts
# --------------------------------------------------------------------------

def _check_duplicate_phone(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L014"
    if not ds.has("phone"):
        ctx.skip(rule, "list has no phone column")
        return []

    groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for n, row in ds.enumerate_rows():
        phone = norm_phone(ds.get(row, "phone"))
        if phone:
            groups[phone].append((n, ds.label(row)))

    out: list[Finding] = []
    for phone, entries in sorted(groups.items()):
        if len(entries) > 1:
            domains = {label for _, label in entries}
            if len(domains) > 1:
                rows_str = ", ".join(f"row {n} ({label})" for n, label in entries)
                out.append(Finding(
                    rule=rule, severity=P1,
                    title="Same phone number on multiple accounts",
                    detail=f"{phone} appears on {rows_str}",
                    remedy="Resolve to one account, or confirm this is a shared switchboard and route accordingly.",
                    origin=(
                        "A shared main number mapped to every contact is the most common enrichment "
                        "failure. The dialer reaches a receptionist three times and the rep never knows."
                    ),
                    key=phone, column=ds.column("phone"),
                ))
    return out


# --------------------------------------------------------------------------
# L015 — stale enrichment
# --------------------------------------------------------------------------

def _check_stale_enrichment(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L015"
    if not ds.has("enriched_date"):
        ctx.skip(rule, "list has no enrichment-date or last-verified column, so freshness cannot be checked")
        return []

    today = cfg.reference_date()
    threshold = cfg.stale_enrichment_days
    out: list[Finding] = []
    unparseable = 0
    for n, row in ds.enumerate_rows():
        raw = ds.get(row, "enriched_date")
        if not raw:
            continue
        when = parse_date(raw)
        if when is None:
            unparseable += 1
            continue
        age = (today - when).days
        if age > threshold:
            out.append(Finding(
                rule=rule, severity=P1,
                title=f"Enrichment is older than {threshold} days",
                detail=f"last verified {raw} ({age} days ago)",
                remedy=f"Re-verify before sending, or accept the higher bounce and wrong-number rate that stale data carries.",
                origin=(
                    "Enrichment decays. A phone number verified in January is not verified in August. "
                    "A list that was clean when it was built is not clean when it is sent."
                ),
                row=n, key=ds.label(row), column=ds.column("enriched_date"),
            ))
    if unparseable:
        out.append(Finding(
            rule=rule, severity=P2,
            title="Enrichment dates that could not be parsed",
            detail=f"{unparseable} row(s) carry an unrecognised date format and were not gated for freshness",
            remedy="Normalise the column to YYYY-MM-DD, or those rows bypass the freshness gate entirely.",
            origin="A gate that cannot read its input reports a pass. Unreadable values are reported, never assumed clean.",
            column=ds.column("enriched_date"),
        ))
    return out


# --------------------------------------------------------------------------
# L016 — missing recipient name
# --------------------------------------------------------------------------

def _check_missing_recipient(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L016"
    has_first = ds.has("first_name")
    has_last = ds.has("last_name")
    if not has_first and not has_last:
        ctx.skip(rule, "list has neither a first-name nor a last-name column")
        return []

    out: list[Finding] = []
    for n, row in ds.enumerate_rows():
        first = ds.get(row, "first_name") if has_first else ""
        last = ds.get(row, "last_name") if has_last else ""
        if not first and not last:
            out.append(Finding(
                rule=rule, severity=P2,
                title="Row has no recipient name",
                detail="both first and last name are empty",
                remedy="Enrich the name, or accept that the personalisation will read 'Hi there' and the reply rate will reflect it.",
                origin=(
                    "A row with no name sends to 'Hi there' or 'To whom it may concern', which is the "
                    "same as sending nothing and costs the same."
                ),
                row=n, key=ds.label(row),
            ))
    return out


# --------------------------------------------------------------------------
# L017 — title scope mismatch
# --------------------------------------------------------------------------

def _check_title_scope(ds: Dataset, cfg: Config, ctx: Context) -> list[Finding]:
    rule = "L017"
    if not ds.has("title"):
        ctx.skip(rule, "list has no title column")
        return []

    keywords = {k.lower() for k in cfg.title_exclude_keywords}
    out: list[Finding] = []
    for n, row in ds.enumerate_rows():
        title = ds.get(row, "title")
        if not title:
            continue
        low = title.lower()
        hit = next((kw for kw in keywords if re.search(rf"\b{re.escape(kw)}\b", low)), None)
        if hit:
            out.append(Finding(
                rule=rule, severity=P2,
                title="Title indicates the wrong seniority for this motion",
                detail=f"title reads {title!r}, which contains {hit!r}",
                remedy="Route to a different motion, or confirm the individual has buying authority despite the title.",
                origin=(
                    "An intern cannot sign a contract and cannot route one. A title that says "
                    "'assistant' is a gatekeeper worth respecting, not a decision-maker worth pitching."
                ),
                row=n, key=ds.label(row), column=ds.column("title"),
            ))
    return out


RULES: tuple[Rule, ...] = (
    Rule("L001", "suppression-collision", P0,
         "Row already exists in the suppression or CRM source",
         "Suppress before you enrich, not after.", _check_suppression),
    Rule("L002", "recent-contact", P0,
         "Row was contacted inside the cooling-off window",
         "Deal stage misses somebody who was called yesterday.", _check_recent_contact),
    Rule("L003", "do-not-call", P0,
         "Number appears on the do-not-call source",
         "Remove, never flag.", _check_dnc),
    Rule("L004", "restricted-jurisdiction", P0,
         "Row sits in a jurisdiction this motion is not cleared for",
         "The only list constraint with a statutory penalty.", _check_jurisdiction),
    Rule("L005", "missing-trigger", P0,
         "Row carries no specific, checkable reason for the outreach",
         "Empty personalisation is worse than none.", _check_trigger),
    Rule("L006", "unrendered-copy", P0,
         "Copy still contains placeholders, raw values, or holes",
         "Sending tools print whatever is in the cell.", _check_unrendered_copy),
    Rule("L007", "email-unverified", P1,
         "Address is unverified or on a catch-all domain",
         "Catch-all passes verification and then bounces.", _check_email_verified),
    Rule("L008", "mailbox-shape", P2,
         "Address is a role mailbox, a free provider, or off-domain",
         "A reply nobody owns is a reply nobody answers.", _check_mailbox_shape),
    Rule("L009", "name-domain-mismatch", P1,
         "Company name and domain do not correspond",
         "Name matches lie.", _check_name_domain),
    Rule("L010", "non-operating-entity", P1,
         "Row is a fund, holding entity, or property vehicle",
         "Filing sources are majority non-operating entities.", _check_entity_type),
    Rule("L011", "headcount-ceiling", P1,
         "Row is larger than the motion is built for",
         "One explicit ceiling beats an implicit filter.", _check_headcount_exclusion),
    Rule("L012", "headcount-floor", P2,
         "List looks filtered on size rather than scored on it",
         "Score size, never filter on it.", _check_headcount_floor),
    Rule("L013", "duplicate-account", P1,
         "The same account appears on more than one row",
         "Two rows become two reps on one account.", _check_duplicates),
    Rule("L014", "duplicate-phone", P1,
         "Same phone number appears on multiple accounts",
         "A shared main number is the most common enrichment failure.", _check_duplicate_phone),
    Rule("L015", "stale-enrichment", P1,
         "Enrichment data is older than the configured freshness threshold",
         "A list that was clean when built is not clean when sent.", _check_stale_enrichment),
    Rule("L016", "missing-recipient", P2,
         "Row carries no recipient name at all",
         "A nameless row sends to nobody and costs the same.", _check_missing_recipient),
    Rule("L017", "title-scope", P2,
         "Title indicates the wrong seniority for the motion",
         "An intern cannot sign a contract.", _check_title_scope),
)

RULES_BY_ID: dict[str, Rule] = {r.id: r for r in RULES}
