import json
import unittest

from kpnetwatch import dnsdoh
from kpnetwatch.webclient import FetchError

from support import client_for, fake_client


def answer(name, code, *data, status=0):
    payload = {"Status": status, "Question": [{"name": name, "type": code}]}
    if data:
        payload["Answer"] = [{"name": name, "type": code, "TTL": 60, "data": item} for item in data]
    return json.dumps(payload).encode()


class ResolveTests(unittest.TestCase):
    def test_fixture_names_resolve_and_normalise(self):
        result = dnsdoh.collect(client_for(), {"kcna.kp": ["seed"], "kp": ["seed"]})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["resolvers"], ["cloudflare-dns.com"])
        kcna = result["domains"]["kcna.kp"]
        self.assertEqual(kcna["status"], "NOERROR")
        self.assertEqual(kcna["records"]["A"], ["175.45.176.71", "175.45.177.1"])
        self.assertEqual(kcna["sources"], ["seed"])
        tld = result["domains"]["kp"]
        self.assertEqual(tld["records"]["NS"], ["ns1.kptc.kp", "ns2.kptc.kp"])
        self.assertTrue(tld["records"]["SOA"][0].startswith("ns1.kptc.kp root.kptc.kp 2026102403"))

    def test_nxdomain_and_servfail_are_reported_per_name(self):
        result = dnsdoh.collect(client_for(), {"portal.net.kp": ["ct"], "star-co.net.kp": ["ct"]})
        self.assertEqual(result["domains"]["portal.net.kp"]["status"], "NXDOMAIN")
        self.assertEqual(result["domains"]["star-co.net.kp"]["status"], "SERVFAIL")
        self.assertFalse(any(dnsdoh.resolving(record) for record in result["domains"].values()))

    def test_single_unanswered_type_does_not_make_the_name_fail(self):
        servfail = answer("x.kp", 1, status=2)
        ns = answer("x.kp", 2, "ns1.x.kp.")
        client, _ = fake_client(
            [("type=AAAA", answer("x.kp", 28)), ("type=A", servfail), ("type=NS", ns), ("type=MX", answer("x.kp", 15)), ("type=SOA", answer("x.kp", 6))]
        )
        record, _ = dnsdoh.resolve_name(client, "x.kp")
        self.assertEqual(record["status"], "NOERROR")
        self.assertEqual(record["unanswered"], ["A"])
        self.assertEqual(record["records"], {"NS": ["ns1.x.kp"]})

    def test_servfail_from_first_resolver_falls_through_to_second(self):
        client, fetch = fake_client(
            [
                ("cloudflare-dns.com", answer("x.kp", 1, status=2)),
                ("dns.google", answer("x.kp", 1, "192.0.2.1")),
            ]
        )
        host, payload = dnsdoh.ask(client, "x.kp", "A")
        self.assertEqual(host, "dns.google")
        self.assertEqual(payload["Answer"][0]["data"], "192.0.2.1")
        self.assertEqual(len(fetch.calls), 2)

    def test_servfail_everywhere_is_kept_as_servfail(self):
        servfail = answer("x.kp", 1, status=2)
        client, _ = fake_client([("cloudflare-dns.com", servfail), ("dns.google", servfail)])
        record, _ = dnsdoh.resolve_name(client, "x.kp")
        self.assertEqual(record["status"], "SERVFAIL")

    def test_transport_failure_on_first_resolver_uses_second(self):
        client, _ = fake_client(
            [("cloudflare-dns.com", FetchError("HTTP 500", status=500)), ("dns.google", answer("x.kp", 1, "192.0.2.1"))]
        )
        record, resolvers = dnsdoh.resolve_name(client, "x.kp")
        self.assertEqual(resolvers, {"dns.google"})
        self.assertEqual(record["records"]["A"], ["192.0.2.1"])

    def test_both_resolvers_failing_marks_name_as_error(self):
        client, _ = fake_client([("cloudflare-dns.com", FetchError("timed out")), ("dns.google", FetchError("timed out"))])
        result = dnsdoh.collect(client, {"x.kp": ["seed"]})
        self.assertEqual(result["domains"]["x.kp"]["status"], "error")
        self.assertEqual(result["status"], "error")

    def test_requests_ask_for_dns_json(self):
        client, fetch = fake_client([("cloudflare-dns.com", answer("x.kp", 1, "192.0.2.1"))])
        dnsdoh.ask(client, "x.kp", "A")
        self.assertEqual(fetch.calls[0][1], {"accept": "application/dns-json"})

    def test_cname_is_kept_separately(self):
        client, _ = fake_client([("cloudflare-dns.com", answer("www.x.kp", 5, "x.kp."))])
        record, _ = dnsdoh.resolve_name(client, "www.x.kp")
        self.assertEqual(record["records"]["CNAME"], ["x.kp"])

    def test_resolving_needs_an_address(self):
        self.assertTrue(dnsdoh.resolving({"records": {"AAAA": ["2001:db8::1"]}}))
        self.assertFalse(dnsdoh.resolving({"records": {"NS": ["ns1.x.kp"]}}))


if __name__ == "__main__":
    unittest.main()
