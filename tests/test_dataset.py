"""Normalisation and column resolution.

These are the functions that decide whether a suppression gate actually suppresses.
`https://WWW.Acme.com/pricing` and `acme.com` are the same company, and if they do
not collide here, nothing downstream will notice.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from revgate.core.dataset import (
    Dataset,
    email_domain,
    load_key_set,
    norm_domain,
    norm_email,
    norm_phone,
    parse_int,
)


def write_csv(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    tmp.write(text)
    tmp.close()
    return Path(tmp.name)


class Domains(unittest.TestCase):
    def test_strips_scheme_path_query_and_www(self):
        for raw in (
            "https://WWW.Acme.com/pricing",
            "http://acme.com?utm=x",
            "  Acme.com/  ",
            "www.acme.com#top",
        ):
            self.assertEqual(norm_domain(raw), "acme.com", raw)

    def test_pulls_host_out_of_an_email(self):
        self.assertEqual(norm_domain("Jordan@Acme.com"), "acme.com")

    def test_empty_is_empty_not_an_error(self):
        self.assertEqual(norm_domain(""), "")
        self.assertEqual(norm_domain(None), "")  # type: ignore[arg-type]

    def test_subdomains_are_preserved(self):
        # Deliberate: eu.acme.com may legitimately be a different account.
        self.assertEqual(norm_domain("https://eu.acme.com"), "eu.acme.com")


class Emails(unittest.TestCase):
    def test_case_and_whitespace_normalised(self):
        self.assertEqual(norm_email("  Jordan.Reeves@Acme.COM "), "jordan.reeves@acme.com")

    def test_domain_extraction(self):
        self.assertEqual(email_domain("Jordan@WWW.Acme.com"), "acme.com")

    def test_domain_of_a_non_email_is_empty(self):
        self.assertEqual(email_domain("jordan"), "")


class Phones(unittest.TestCase):
    def test_formatting_is_irrelevant(self):
        for raw in ("+1 (415) 555-0142", "1-415-555-0142", "415.555.0142", "4155550142"):
            self.assertEqual(norm_phone(raw), "4155550142", raw)

    def test_short_numbers_are_left_alone_rather_than_padded(self):
        self.assertEqual(norm_phone("555-0142"), "5550142")

    def test_extensions_beyond_ten_digits_keep_the_last_ten(self):
        self.assertEqual(len(norm_phone("+44 20 7946 0958 123")), 10)


class Integers(unittest.TestCase):
    def test_thousands_separators(self):
        self.assertEqual(parse_int("1,200"), 1200)

    def test_embedded_in_prose(self):
        self.assertEqual(parse_int("approx 45 staff"), 45)

    def test_unparseable_is_none_not_zero(self):
        # Zero would silently trip the headcount floor gate.
        self.assertIsNone(parse_int(""))
        self.assertIsNone(parse_int("unknown"))


class ColumnResolution(unittest.TestCase):
    def test_vendor_specific_headers_resolve_to_logical_fields(self):
        path = write_csv("Company Name,Company Website,Work Email,Employee Count\nAcme,acme.com,a@acme.com,50\n")
        ds = Dataset.load(path)
        self.assertTrue(ds.has("company", "domain", "email", "headcount"))
        self.assertEqual(ds.get(ds.rows[0], "domain"), "acme.com")
        path.unlink()

    def test_absent_fields_are_reported_not_faked(self):
        path = write_csv("Company\nAcme\n")
        ds = Dataset.load(path)
        self.assertEqual(ds.missing("domain", "email"), ["domain", "email"])
        self.assertEqual(ds.get(ds.rows[0], "domain"), "", "an unmapped field must read empty")
        path.unlink()

    def test_explicit_override_naming_a_missing_column_does_not_map(self):
        path = write_csv("Company,Site\nAcme,acme.com\n")
        ds = Dataset.load(path, overrides={"domain": "NotAColumn"})
        self.assertFalse(ds.has("domain"))
        path.unlink()

    def test_row_numbers_match_a_spreadsheet(self):
        path = write_csv("Company\nA\nB\n")
        ds = Dataset.load(path)
        self.assertEqual([n for n, _ in ds.enumerate_rows()], [2, 3],
                         "header is row 1, so the first record is row 2")
        path.unlink()

    def test_label_prefers_the_most_recognisable_identifier(self):
        path = write_csv("Company,Domain\nAcme Inc,acme.com\n")
        ds = Dataset.load(path)
        self.assertEqual(ds.label(ds.rows[0]), "acme.com")
        path.unlink()

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            Dataset.load("/nonexistent/leads.csv")


class SuppressionSources(unittest.TestCase):
    def test_harvests_whatever_columns_the_export_happens_to_have(self):
        path = write_csv("Account,Primary Email\nAcme,Jordan@Acme.com\n")
        keys = load_key_set(path, kinds=("domain", "email"))
        self.assertIn("jordan@acme.com", keys["email"])
        self.assertIn("acme.com", keys["domain"],
                      "an email in a suppression export implies its domain is in play")
        path.unlink()

    def test_blank_values_never_become_keys(self):
        path = write_csv("Domain\nacme.com\n\n")
        keys = load_key_set(path, kinds=("domain",))
        self.assertEqual(keys["domain"], {"acme.com"})
        path.unlink()

    def test_missing_source_raises_so_the_caller_can_skip_loudly(self):
        with self.assertRaises(FileNotFoundError):
            load_key_set("/nonexistent/crm.csv")


if __name__ == "__main__":
    unittest.main()
