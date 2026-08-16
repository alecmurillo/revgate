"""CSV loading, column resolution, and the normalizers every gate shares.

Column names are the first thing that breaks. Every CRM, enrichment vendor and
sales-engagement tool exports the same field under a different header, so gates
address *logical* fields and this module resolves them against whatever the file
actually contains. When resolution fails, the gate is skipped and reported rather
than silently evaluating an empty string.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

# Logical field -> header aliases, lowercased and stripped of non-alphanumerics
# before comparison. Order matters: earlier aliases win.
ALIASES: dict[str, tuple[str, ...]] = {
    "company": ("company", "companyname", "account", "accountname", "organization", "org", "orgname"),
    "domain": ("domain", "companydomain", "website", "companywebsite", "url", "site", "primarydomain"),
    "email": ("email", "workemail", "emailaddress", "contactemail", "primaryemail"),
    "email_status": ("emailstatus", "emailverification", "verificationstatus", "verification", "emailvalidity", "emailconfidence"),
    "phone": ("phone", "phonenumber", "directphone", "mobile", "mobilephone", "mobilenumber", "directdial"),
    "first_name": ("firstname", "fname", "givenname", "contactfirstname"),
    "last_name": ("lastname", "lname", "surname", "familyname"),
    "title": ("title", "jobtitle", "role", "position"),
    "state": ("state", "stateprovince", "companystate", "region", "province"),
    "country": ("country", "companycountry", "countryname"),
    "headcount": ("headcount", "employees", "employeecount", "numemployees", "size", "companysize", "staff"),
    "trigger": ("trigger", "whynow", "whycall", "signal", "reason", "reasontocall", "triggerevent"),
    "copy": ("copy", "emailbody", "body", "message", "firstline", "opener", "personalization", "subject", "subjectline"),
    "last_contacted": ("lastcontacted", "noteslastcontacted", "lastactivity", "lasttouch", "lastcontactdate", "lastoutreach"),
    "enriched_date": ("enricheddate", "lastverified", "dataverified", "verificationdate", "lastenriched", "enrichedon", "dataasof", "lastupdated", "datelastupdated"),
    "owner": ("owner", "assignedto", "rep", "bdr", "accountowner", "dealowner"),
}


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (header or "").strip().lower())


def norm_domain(value: str) -> str:
    """Reduce anything domain-shaped to a bare comparable host.

    Suppression matching on a raw column is the single most common way a list
    passes a clean check and still collides: `https://WWW.Acme.com/pricing` and
    `acme.com` are the same company and no string comparison says so.
    """
    v = (value or "").strip().lower()
    if not v:
        return ""
    v = re.sub(r"^[a-z][a-z0-9+.-]*://", "", v)
    v = v.split("/")[0].split("?")[0].split("#")[0]
    v = v.split("@")[-1]
    if v.startswith("www."):
        v = v[4:]
    return v.strip().strip(".")


def norm_email(value: str) -> str:
    return (value or "").strip().lower()


def email_domain(value: str) -> str:
    e = norm_email(value)
    return norm_domain(e.split("@")[-1]) if "@" in e else ""


def norm_phone(value: str) -> str:
    """Digits only, North-America-normalised to the last 10.

    A do-not-call list stored as `(415) 555-0142` and a lead stored as
    `+1 415 555 0142` must collide, or the gate is decorative.
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits[-10:] if len(digits) >= 10 else digits


def parse_int(value: str) -> int | None:
    m = re.search(r"\d[\d,]*", value or "")
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


@dataclass
class Dataset:
    """A loaded CSV plus the logical-field mapping resolved against its headers."""

    path: Path
    headers: list[str]
    rows: list[dict[str, str]]
    mapping: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path, overrides: dict[str, str] | None = None) -> "Dataset":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"no such file: {p}")
        with p.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            headers = [h for h in (reader.fieldnames or []) if h is not None]
            rows = [{(k or ""): (v if v is not None else "") for k, v in row.items()} for row in reader]
        ds = cls(path=p, headers=headers, rows=rows)
        ds.mapping = ds._resolve(overrides or {})
        return ds

    def _resolve(self, overrides: dict[str, str]) -> dict[str, str]:
        by_key = {_key(h): h for h in self.headers}
        mapping: dict[str, str] = {}
        for logical, aliases in ALIASES.items():
            explicit = overrides.get(logical)
            if explicit:
                # An override that names a column the file does not have is a
                # configuration bug worth surfacing, not silently ignoring.
                if explicit in self.headers:
                    mapping[logical] = explicit
                continue
            for alias in aliases:
                if alias in by_key:
                    mapping[logical] = by_key[alias]
                    break
        return mapping

    def has(self, *logical: str) -> bool:
        return all(name in self.mapping for name in logical)

    def missing(self, *logical: str) -> list[str]:
        return [name for name in logical if name not in self.mapping]

    def get(self, row: dict[str, str], logical: str) -> str:
        header = self.mapping.get(logical)
        if not header:
            return ""
        return (row.get(header) or "").strip()

    def label(self, row: dict[str, str]) -> str:
        """The most human-recognisable identifier available for a row."""
        for logical in ("domain", "company", "email", "phone"):
            v = self.get(row, logical)
            if v:
                return v
        return "(unidentified row)"

    def column(self, logical: str) -> str:
        return self.mapping.get(logical, logical)

    def enumerate_rows(self):
        """1-based row numbers matching what a spreadsheet shows (header is row 1)."""
        for i, row in enumerate(self.rows, start=2):
            yield i, row

    def __len__(self) -> int:
        return len(self.rows)


def load_key_set(path: str | Path, kinds: tuple[str, ...] = ("domain", "email", "phone")) -> dict[str, set[str]]:
    """Load a reference export (CRM, do-not-call, prior campaign) into lookup sets.

    Accepts any CSV and harvests every column that looks like a domain, email or
    phone, because suppression sources are exported by whoever happened to export
    them and never share a schema.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no such file: {p}")
    out: dict[str, set[str]] = {k: set() for k in kinds}
    with p.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = [h for h in (reader.fieldnames or []) if h]
        by_key = {_key(h): h for h in headers}
        cols: dict[str, list[str]] = {k: [] for k in kinds}
        for logical in kinds:
            for alias in ALIASES.get(logical, ()):
                if alias in by_key and by_key[alias] not in cols[logical]:
                    cols[logical].append(by_key[alias])
        for row in reader:
            for logical in kinds:
                for header in cols[logical]:
                    raw = (row.get(header) or "").strip()
                    if not raw:
                        continue
                    if logical == "domain":
                        out["domain"].add(norm_domain(raw))
                    elif logical == "email":
                        e = norm_email(raw)
                        out["email"].add(e)
                        if "domain" in out:
                            # An email in a suppression export implies its domain
                            # is in play, which is the level most collisions occur at.
                            out["domain"].add(email_domain(raw))
                    elif logical == "phone":
                        out["phone"].add(norm_phone(raw))
    for k in out:
        out[k].discard("")
    return out
