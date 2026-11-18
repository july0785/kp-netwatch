import json
import unittest

from kpnetwatch import crtsh
from kpnetwatch.webclient import FetchError

from support import FIXTURES, Sequence, client_for, fake_client, fixture_copy, make_error

ROW = {
    "issuer_ca_id": 295809,
    "issuer_name": "C=US, O=Let's Encrypt, CN=E8",
    "common_name": "*.kza.org.kp",
    "name_value": "*.kza.org.kp\nkza.org.kp",
    "id": 100,
    "not_before": "2026-04-20T01:11:17",
    "not_after": "2026-07-19T01:11:16",
    "serial_number": "05b6",
    "entry_timestamp": "2026-04-20T02:11:17.123",
}


def body(*rows):
    return json.dumps(list(rows)).encode()


class ParseTests(unittest.TestCase):
    def test_dedupes_by_id_and_keeps_fields(self):
        certs = crtsh.parse_rows([ROW, dict(ROW), {**ROW, "id": 101}])
        self.assertEqual(sorted(certs), [100, 101])
        cert = certs[100]
        self.assertEqual(cert["names"], ["*.kza.org.kp", "kza.org.kp"])
        self.assertEqual(cert["issuer"], "C=US, O=Let's Encrypt, CN=E8")
        self.assertEqual(cert["not_before"], "2026-04-20T01:11:17")
        self.assertEqual(cert["not_after"], "2026-07-19T01:11:16")
        self.assertEqual(cert["serial"], "05b6")
        self.assertEqual(cert["entry_timestamp"], "2026-04-20T02:11:17.123")

    def test_missing_entry_timestamp_is_null(self):
        row = {key: value for key, value in ROW.items() if key != "entry_timestamp"}
        self.assertIsNone(crtsh.parse_rows([row])[100]["entry_timestamp"])

    def test_names_are_lowercased(self):
        certs = crtsh.parse_rows([{**ROW, "name_value": "WWW.Example.ORG.kp"}])
        self.assertEqual(certs[100]["names"], ["www.example.org.kp"])

    def test_suffix_of(self):
        self.assertEqual(crtsh.suffix_of("www.portal.net.kp"), "net")
        self.assertEqual(crtsh.suffix_of("%.org.kp"), "org")
        self.assertIsNone(crtsh.suffix_of("kcna.kp"))


class CollectTests(unittest.TestCase):
    def test_collects_from_fixtures(self):
        result = crtsh.collect(client_for())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(sorted(result["queries"]), sorted(f"%.{suffix}.kp" for suffix in crtsh.SUFFIXES))
        ids = [cert["id"] for cert in result["certs"]]
        self.assertEqual(ids, sorted(set(ids)))
        names = {name for cert in result["certs"] for name in cert["names"]}
        self.assertIn("portal.net.kp", names)
        self.assertIn("*.kza.org.kp", names)
        raw = []
        for name in ("crt-net.kp.json", "crt-org.kp.json"):
            raw += json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        self.assertEqual(len(ids), len({row["id"] for row in raw}))

    def test_server_error_on_one_query_is_recorded(self):
        directory = fixture_copy(self)
        make_error(directory, "crt-org.kp", "502")
        result = crtsh.collect(client_for(directory))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["queries"]["%.org.kp"]["status"], "error")
        self.assertIn("502", result["queries"]["%.org.kp"]["error"])
        self.assertEqual(result["queries"]["%.net.kp"]["status"], "ok")
        self.assertTrue(result["certs"])

    def test_every_query_timing_out_gives_error_status_without_raising(self):
        client, fetch = fake_client([("crt.sh", FetchError("TimeoutError: timed out"))])
        result = crtsh.collect(client)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["certs"], [])
        self.assertTrue(all(info["status"] == "error" for info in result["queries"].values()))
        self.assertEqual(len(fetch.calls), crtsh.ATTEMPTS * len(crtsh.SUFFIXES))

    def test_not_found_is_retried(self):
        route = Sequence(FetchError("HTTP 404", status=404), FetchError("HTTP 404", status=404), body(ROW))
        client, fetch = fake_client([("crt.sh", route)])
        info, certs = crtsh.query(client, "org")
        self.assertEqual(info, {"status": "ok", "rows": 1})
        self.assertEqual(list(certs), [100])
        self.assertEqual(len(fetch.calls), 3)

    def test_html_error_page_is_an_error(self):
        client, _ = fake_client([("crt.sh", b"<html>502</html>")])
        info, certs = crtsh.query(client, "org")
        self.assertEqual(info["status"], "error")
        self.assertEqual(certs, {})

    def test_unexpected_json_shape_is_an_error(self):
        client, _ = fake_client([("crt.sh", b'{"error": "nope"}')])
        info, _ = crtsh.query(client, "org")
        self.assertEqual(info["status"], "error")

    def test_query_url_uses_percent_encoded_wildcard(self):
        client, fetch = fake_client([("crt.sh", b"[]")])
        crtsh.query(client, "net")
        self.assertEqual(fetch.calls[0][0], "https://crt.sh/?q=%25.net.kp&output=json")


if __name__ == "__main__":
    unittest.main()
