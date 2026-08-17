"""Tests for the HTTP gating API: adapters, server, and fail-closed semantics.

These tests call ``evaluate()`` directly (no server needed) for the logic
tests, and start a real HTTP server on an ephemeral port for the transport
tests. No external dependencies.
"""

import http.client
import json
import os
import sys
import threading
import unittest
from pathlib import Path

# Ensure the repo root is importable.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from revgate.api.adapters import (
    AdapterError,
    parse_clay,
    parse_generic,
    parse_hubspot,
    parse_apollo,
    get_adapter,
    RowInput,
)
from revgate.api.server import evaluate, create_server, API_VERSION
from revgate.core.config import Config

FIXTURES = _REPO / "fixtures" / "api"


# ---------------------------------------------------------------------------
# Adapter tests
# ---------------------------------------------------------------------------

class TestAdapters(unittest.TestCase):
    def test_generic_single_row(self):
        body = {"Company": "Acme", "Domain": "acme.com"}
        rows = parse_generic(body)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].data["Company"], "Acme")
        self.assertEqual(rows[0].external_id, "row-0")

    def test_generic_batch(self):
        body = {"rows": [{"Company": "A", "_external_id": "r1"}, {"Company": "B", "_external_id": "r2"}]}
        rows = parse_generic(body)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].external_id, "r1")
        self.assertEqual(rows[1].external_id, "r2")

    def test_generic_empty_rows(self):
        with self.assertRaises(AdapterError):
            parse_generic({"rows": []})

    def test_generic_non_object(self):
        with self.assertRaises(AdapterError):
            parse_generic([])  # type: ignore[arg-type]

    def test_clay_batch(self):
        body = {"rows": [{"Company Name": "Acme", "Domain": "acme.com"}]}
        rows = parse_clay(body)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].data["Company Name"], "Acme")

    def test_clay_single_row(self):
        body = {"Company": "Acme", "Domain": "acme.com"}
        rows = parse_clay(body)
        self.assertEqual(len(rows), 1)

    def test_clay_wrapped_data(self):
        body = {"rows": [{"id": "clay-42", "data": {"Company": "Acme", "Domain": "acme.com"}}]}
        rows = parse_clay(body)
        self.assertEqual(rows[0].external_id, "clay-42")
        self.assertEqual(rows[0].data["Company"], "Acme")

    def test_clay_empty(self):
        with self.assertRaises(AdapterError):
            parse_clay({"rows": []})

    def test_clay_unrecognised(self):
        with self.assertRaises(AdapterError):
            parse_clay({"foo": "bar"})

    def test_hubspot_flat_properties(self):
        body = {
            "contact": {"vid": 1, "properties": {"firstname": "John", "email": "j@acme.com"}},
            "company": {"properties": {"name": "Acme", "domain": "acme.com", "state": "NY"}},
        }
        rows = parse_hubspot(body)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].data["firstname"], "John")
        self.assertEqual(rows[0].data["name"], "Acme")
        self.assertEqual(rows[0].data["state"], "NY")
        self.assertEqual(rows[0].external_id, "contact-1")

    def test_hubspot_nested_value(self):
        body = {
            "contact": {"vid": 2, "properties": {"email": {"value": "j@acme.com"}}},
            "company": {"properties": {"name": {"value": "Acme"}}},
        }
        rows = parse_hubspot(body)
        self.assertEqual(rows[0].data["email"], "j@acme.com")
        self.assertEqual(rows[0].data["name"], "Acme")

    def test_hubspot_events_batch(self):
        body = {
            "events": [
                {"contact": {"vid": 1, "properties": {"email": "a@x.com"}}},
                {"contact": {"vid": 2, "properties": {"email": "b@x.com"}}},
            ]
        }
        rows = parse_hubspot(body)
        self.assertEqual(len(rows), 2)

    def test_hubspot_empty(self):
        with self.assertRaises(AdapterError):
            parse_hubspot({"foo": "bar"})

    def test_apollo_prospect(self):
        body = {
            "prospect": {
                "id": "apt_1",
                "first_name": "John",
                "email": "j@acme.com",
                "organization": {"name": "Acme", "domain": "acme.com", "size": "50"},
            }
        }
        rows = parse_apollo(body)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].data["first_name"], "John")
        self.assertEqual(rows[0].data["name"], "Acme")
        self.assertEqual(rows[0].data["domain"], "acme.com")
        self.assertEqual(rows[0].external_id, "apt_1")

    def test_apollo_batch(self):
        body = {"prospects": [{"id": "a", "email": "a@x.com"}, {"id": "b", "email": "b@x.com"}]}
        rows = parse_apollo(body)
        self.assertEqual(len(rows), 2)

    def test_apollo_flat(self):
        body = {"email": "j@acme.com", "first_name": "John"}
        rows = parse_apollo(body)
        self.assertEqual(len(rows), 1)

    def test_apollo_missing(self):
        with self.assertRaises(AdapterError):
            parse_apollo({"foo": "bar"})

    def test_unknown_source(self):
        with self.assertRaises(AdapterError):
            get_adapter("nonexistent")


# ---------------------------------------------------------------------------
# Evaluate (logic) tests
# ---------------------------------------------------------------------------

class TestEvaluate(unittest.TestCase):
    def setUp(self):
        # Acknowledge that source-dependent P0 gates (suppression, DNC) are
        # intentionally not configured for these logic tests.
        self.cfg = Config(acknowledge_unconfigured=("L001", "L003", "L018"))

    def _load_fixture(self, name: str) -> dict:
        with (FIXTURES / name).open() as fh:
            return json.load(fh)

    def test_clay_pass(self):
        body = self._load_fixture("clay-pass.json")
        resp = evaluate(body, self.cfg)
        self.assertEqual(resp["verdict"], "PASS")
        self.assertEqual(resp["exit_code"], 0)
        self.assertEqual(len(resp["rows"]), 1)
        self.assertEqual(resp["rows"][0]["revgate_status"], "PASS")
        self.assertTrue(resp["rows"][0]["revgate_checked_at"])

    def test_clay_block(self):
        body = self._load_fixture("clay-block.json")
        resp = evaluate(body, self.cfg)
        self.assertEqual(resp["verdict"], "BLOCKED")
        self.assertEqual(resp["exit_code"], 2)
        self.assertGreater(resp["counts"]["P0"], 0)
        self.assertEqual(resp["rows"][0]["revgate_status"], "BLOCKED")
        self.assertTrue(resp["rows"][0]["revgate_rules"])

    def test_hubspot_pass(self):
        body = self._load_fixture("hubspot-pass.json")
        resp = evaluate(body, self.cfg)
        self.assertEqual(resp["verdict"], "PASS")
        self.assertEqual(resp["exit_code"], 0)

    def test_hubspot_block(self):
        body = self._load_fixture("hubspot-block.json")
        resp = evaluate(body, self.cfg)
        self.assertEqual(resp["verdict"], "BLOCKED")
        self.assertEqual(resp["exit_code"], 2)
        # NY restricted + headcount ceiling + name/domain mismatch + intern title + free email not (it's acme.com)
        self.assertGreater(resp["counts"]["P0"], 0)

    def test_apollo_pass(self):
        body = self._load_fixture("apollo-pass.json")
        resp = evaluate(body, self.cfg)
        self.assertEqual(resp["verdict"], "PASS")
        self.assertEqual(resp["exit_code"], 0)

    def test_apollo_block(self):
        body = self._load_fixture("apollo-block.json")
        resp = evaluate(body, self.cfg)
        self.assertEqual(resp["verdict"], "BLOCKED")
        self.assertEqual(resp["exit_code"], 2)
        self.assertGreater(resp["counts"]["P0"], 0)

    def test_batch(self):
        body = {
            "source": "generic",
            "rows": [
                {"Company": "Good Co", "Domain": "goodco.com", "Email": "ops@goodco.com", "Trigger": "opened new DC", "Copy": "Saw the new DC — congrats."},
                {"Company": "Bad Co", "Domain": "badco.com", "Email": "info@badco.com", "State": "NY", "Trigger": "good fit", "Copy": "Hi there,"},
            ],
            "config": {"restricted_states": ["NY"]},
        }
        resp = evaluate(body, self.cfg)
        self.assertEqual(resp["verdict"], "BLOCKED")
        self.assertEqual(len(resp["rows"]), 2)
        self.assertEqual(resp["rows"][0]["verdict"], "PASS")
        self.assertEqual(resp["rows"][1]["verdict"], "BLOCKED")

    def test_malformed_json(self):
        resp = evaluate({"source": "generic", "rows": []}, self.cfg)
        self.assertEqual(resp["verdict"], "BLOCKED")
        self.assertIn("error", resp)

    def test_unknown_source(self):
        resp = evaluate({"source": "nonexistent", "rows": [{"Company": "X"}]}, self.cfg)
        self.assertEqual(resp["verdict"], "BLOCKED")
        self.assertIn("error", resp)

    def test_fail_closed_on_adapter_error(self):
        resp = evaluate({"source": "clay", "foo": "bar"}, self.cfg)
        self.assertEqual(resp["verdict"], "BLOCKED")
        self.assertEqual(resp["exit_code"], 2)
        self.assertNotEqual(resp.get("error", ""), "")

    def test_writeback_fields_present(self):
        body = self._load_fixture("clay-pass.json")
        resp = evaluate(body, self.cfg)
        row = resp["rows"][0]
        for field in ("revgate_status", "revgate_severity", "revgate_rules",
                       "revgate_summary", "revgate_checked_at"):
            self.assertIn(field, row)

    def test_config_overrides_applied(self):
        body = {
            "source": "generic",
            "rows": [{"Company": "Test", "Domain": "test.com", "Email": "t@test.com", "State": "NY", "Trigger": "opened new DC", "Copy": "Saw the new DC — congrats."}],
            "config": {"restricted_states": ["NY"]},
        }
        resp = evaluate(body, self.cfg)
        self.assertEqual(resp["verdict"], "BLOCKED")
        # Without the override, NY is not restricted and the row would pass.
        resp2 = evaluate({"source": "generic", "rows": [{"Company": "Test", "Domain": "test.com", "Email": "t@test.com", "State": "NY", "Trigger": "opened new DC", "Copy": "Saw the new DC — congrats."}]}, self.cfg)
        self.assertEqual(resp2["verdict"], "PASS")

    def test_version_in_response(self):
        resp = evaluate({"source": "generic", "rows": [{"Company": "X"}]}, self.cfg)
        self.assertEqual(resp["version"], API_VERSION)


# ---------------------------------------------------------------------------
# HTTP server tests
# ---------------------------------------------------------------------------

class TestHTTPServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(port=0, auth_key="test-secret",
                                   config=Config(acknowledge_unconfigured=("L001", "L003", "L018")))
        # Port 0 lets the OS assign an ephemeral port.
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _request(self, method: str, path: str, body: bytes | None = None,
                headers: dict[str, str] | None = None) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        h = headers or {}
        if body:
            h.setdefault("Content-Type", "application/json")
            h.setdefault("Content-Length", str(len(body)))
        conn.request(method, path, body=body, headers=h)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        payload = json.loads(data) if data else {}
        return resp.status, payload

    def test_health(self):
        status, body = self._request("GET", "/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_auth_missing(self):
        status, body = self._request("POST", "/v1/lint",
                                     json.dumps({"source": "generic", "rows": [{"Company": "X"}]}).encode())
        self.assertEqual(status, 401)
        self.assertEqual(body["verdict"], "BLOCKED")

    def test_auth_wrong(self):
        status, body = self._request("POST", "/v1/lint",
                                     json.dumps({"source": "generic", "rows": [{"Company": "X"}]}).encode(),
                                     {"X-Revgate-Key": "wrong"})
        self.assertEqual(status, 401)

    def test_auth_correct_pass(self):
        status, body = self._request("POST", "/v1/lint",
                                     json.dumps({"source": "generic", "rows": [{"Company": "Good Co", "Domain": "goodco.com", "Email": "ops@goodco.com", "Trigger": "opened new DC", "Copy": "Saw the new DC — congrats."}]}).encode(),
                                     {"X-Revgate-Key": "test-secret"})
        self.assertEqual(status, 200)
        self.assertEqual(body["verdict"], "PASS")

    def test_auth_correct_block(self):
        status, body = self._request("POST", "/v1/lint",
                                     json.dumps({"source": "generic", "rows": [{"Company": "Bad Co", "Domain": "badco.com", "Email": "info@badco.com", "State": "NY"}], "config": {"restricted_states": ["NY"]}}).encode(),
                                     {"X-Revgate-Key": "test-secret"})
        self.assertEqual(status, 422)
        self.assertEqual(body["verdict"], "BLOCKED")

    def test_malformed_json(self):
        status, body = self._request("POST", "/v1/lint", b"{not json",
                                     {"X-Revgate-Key": "test-secret"})
        self.assertEqual(status, 400)
        self.assertEqual(body["verdict"], "BLOCKED")

    def test_clay_fixture_via_http(self):
        with (FIXTURES / "clay-block.json").open() as fh:
            payload = json.load(fh)
        status, body = self._request("POST", "/v1/lint",
                                     json.dumps(payload).encode(),
                                     {"X-Revgate-Key": "test-secret"})
        self.assertEqual(status, 422)
        self.assertEqual(body["verdict"], "BLOCKED")
        self.assertGreater(body["counts"]["P0"], 0)
        self.assertEqual(body["rows"][0]["revgate_status"], "BLOCKED")

    def test_404(self):
        status, body = self._request("GET", "/unknown")
        self.assertEqual(status, 404)

    def test_malformed_content_length(self):
        # H7: malformed Content-Length must not crash
        status, body = self._request("POST", "/v1/lint", b"{}",
                                     {"X-Revgate-Key": "test-secret", "Content-Length": "abc"})
        self.assertEqual(status, 400)
        self.assertEqual(body["verdict"], "BLOCKED")

    def test_oversized_body_rejected(self):
        # H7: body over 1MB must be rejected with 413.
        # The server sends 413 and closes before reading the body, so the
        # client may get a BrokenPipeError — that's expected.
        big = json.dumps({"source": "generic", "rows": [{"Company": "X" * 1_100_000}]})
        try:
            status, body = self._request("POST", "/v1/lint", big.encode(),
                                         {"X-Revgate-Key": "test-secret"})
        except (ConnectionError, BrokenPipeError, OSError):
            return  # server closed the connection after 413 — expected
        self.assertEqual(status, 413)
        self.assertEqual(body["verdict"], "BLOCKED")


class ServerSecurity(unittest.TestCase):
    def test_refuses_non_loopback_without_auth(self):
        # H6: binding 0.0.0.0 without an auth key must raise
        with self.assertRaises(ValueError):
            create_server(port=0, host="0.0.0.0")

    def test_allows_non_loopback_with_auth(self):
        # H6: binding 0.0.0.0 with an auth key is allowed
        s = create_server(port=0, host="0.0.0.0", auth_key="secret")
        s.server_close()


if __name__ == "__main__":
    unittest.main()
