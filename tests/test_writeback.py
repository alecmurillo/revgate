"""Tests for the optional writeback adapters."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from revgate.api.writeback import (
    writeback_clay,
    writeback_hubspot,
    writeback,
    WritebackError,
)


class TestWritebackClay(unittest.TestCase):
    def test_missing_api_key_raises(self):
        with self.assertRaises(WritebackError) as ctx:
            writeback_clay(api_key="", rows=[{"external_id": "r1"}])
        self.assertIn("CLAY_API_KEY", str(ctx.exception))

    def test_missing_source_id_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(WritebackError) as ctx:
                writeback_clay(api_key="sk-test", rows=[{"external_id": "r1"}])
        self.assertIn("CLAY_SOURCE_ID", str(ctx.exception))

    @patch("revgate.api.writeback.urllib.request.urlopen")
    def test_successful_writeback(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"ok": true}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        rows = [
            {"external_id": "r1", "revgate_status": "blocked", "revgate_severity": "P0",
             "revgate_rules": "L001", "revgate_summary": "Missing email", "revgate_checked_at": "2026-01-01"},
            {"external_id": "r2", "revgate_status": "pass", "revgate_severity": "",
             "revgate_rules": "", "revgate_summary": "", "revgate_checked_at": "2026-01-01"},
        ]
        results = writeback_clay(api_key="sk-test", rows=rows, source_id="src123")
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["ok"])
        self.assertTrue(results[1]["ok"])

    @patch("revgate.api.writeback.urllib.request.urlopen")
    def test_http_error_returns_error(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            url="https://api.clay.com/v3/sources/src/items",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )

        rows = [{"external_id": "r1", "revgate_status": "blocked"}]
        results = writeback_clay(api_key="sk-test", rows=rows, source_id="src123")
        self.assertFalse(results[0]["ok"])
        self.assertIn("401", results[0]["error"])

    @patch("revgate.api.writeback.urllib.request.urlopen")
    def test_network_error_returns_error(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("connection refused")

        rows = [{"external_id": "r1", "revgate_status": "blocked"}]
        results = writeback_clay(api_key="sk-test", rows=rows, source_id="src123")
        self.assertFalse(results[0]["ok"])
        self.assertIn("network error", results[0]["error"])

    def test_missing_external_id(self):
        rows = [{"revgate_status": "blocked"}]
        results = writeback_clay(api_key="sk-test", rows=rows, source_id="src123")
        self.assertFalse(results[0]["ok"])
        self.assertIn("missing external_id", results[0]["error"])


class TestWritebackHubSpot(unittest.TestCase):
    def test_missing_api_key_raises(self):
        with self.assertRaises(WritebackError) as ctx:
            writeback_hubspot(api_key="", rows=[{"external_id": "c1"}])
        self.assertIn("HUBSPOT_API_KEY", str(ctx.exception))

    @patch("revgate.api.writeback.urllib.request.urlopen")
    def test_successful_writeback(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"ok": true}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        rows = [
            {"external_id": "c1", "revgate_status": "pass", "revgate_severity": "",
             "revgate_rules": "", "revgate_summary": "", "revgate_checked_at": "2026-01-01"},
        ]
        results = writeback_hubspot(api_key="pat-test", rows=rows)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])

    @patch("revgate.api.writeback.urllib.request.urlopen")
    def test_http_error_returns_error(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            url="https://api.hubapi.com/crm/v3/objects/contacts/c1",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=None,
        )

        rows = [{"external_id": "c1", "revgate_status": "blocked"}]
        results = writeback_hubspot(api_key="pat-test", rows=rows)
        self.assertFalse(results[0]["ok"])
        self.assertIn("404", results[0]["error"])


class TestWritebackDispatch(unittest.TestCase):
    def test_unknown_adapter_raises(self):
        with self.assertRaises(WritebackError) as ctx:
            writeback("apollo", api_key="x", rows=[])
        self.assertIn("unknown writeback adapter", str(ctx.exception))

    def test_clay_dispatch(self):
        with patch("revgate.api.writeback.writeback_clay") as mock_clay:
            mock_clay.return_value = [{"ok": True}]
            result = writeback("clay", api_key="sk-test", rows=[], source_id="src")
            self.assertEqual(len(result), 1)

    def test_hubspot_dispatch(self):
        with patch("revgate.api.writeback.writeback_hubspot") as mock_hs:
            mock_hs.return_value = [{"ok": True}]
            result = writeback("hubspot", api_key="pat-test", rows=[])
            self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
