import unittest

from kpnetwatch import ripestat
from kpnetwatch.fixtures import FixtureFetcher
from kpnetwatch.webclient import Client

from support import FIXTURES, client_for, edit_json, fixture_copy, make_error


class RecordingFetch:
    def __init__(self, inner):
        self.inner = inner
        self.urls = []

    def __call__(self, url, headers, timeout):
        self.urls.append(url)
        return self.inner(url, headers, timeout)


class DiscoveryTests(unittest.TestCase):
    def test_reads_resources_from_country_resource_list(self):
        found = ripestat.discover(client_for())
        self.assertEqual(found["status"], "ok")
        self.assertFalse(found["fallback"])
        self.assertEqual(found["asn"], ["131279"])
        self.assertEqual(found["ipv4"], ["175.45.176.0/22"])
        self.assertEqual(found["ipv6"], [])
        self.assertEqual(found["source"], "country-resource-list")

    def test_falls_back_to_seed_asn_and_says_so(self):
        directory = fixture_copy(self)
        make_error(directory, "ripestat-country-resource-list-kp", "500")
        found = ripestat.discover(client_for(directory))
        self.assertEqual(found["status"], "error")
        self.assertTrue(found["fallback"])
        self.assertEqual(found["source"], "fallback-seed")
        self.assertEqual(found["asn"], ["131279"])
        self.assertIn("500", found["error"])

    def test_empty_asn_list_counts_as_failed_discovery(self):
        directory = fixture_copy(self)
        edit_json(directory / "ripestat-country-resource-list-kp.json", lambda data: data["data"]["resources"].update(asn=[]))
        self.assertTrue(ripestat.discover(client_for(directory))["fallback"])

    def test_error_envelope_counts_as_failed_discovery(self):
        directory = fixture_copy(self)
        edit_json(directory / "ripestat-country-resource-list-kp.json", lambda data: data.update(status="error", message="maintenance"))
        found = ripestat.discover(client_for(directory))
        self.assertTrue(found["fallback"])
        self.assertIn("maintenance", found["error"])

    def test_additional_asns_are_picked_up(self):
        directory = fixture_copy(self)
        edit_json(directory / "ripestat-country-resource-list-kp.json", lambda data: data["data"]["resources"].update(asn=["64511", "131279"]))
        self.assertEqual(ripestat.discover(client_for(directory))["asn"], ["64511", "131279"])


class CollectTests(unittest.TestCase):
    def test_collects_asn_prefixes_and_visibility(self):
        bgp = ripestat.collect(client_for())
        self.assertEqual(bgp["status"], "ok")
        asn = bgp["asns"]["131279"]
        self.assertEqual(asn["holder"], "STAR-KP - Ryugyong-dong")
        self.assertTrue(asn["announced"])
        self.assertEqual([item["asn"] for item in asn["neighbours"]], [20485, 134544])
        self.assertEqual(asn["visibility"]["v4"], {"seeing": 322, "total": 322})
        expected = ["175.45.176.0/24", "175.45.177.0/24", "175.45.178.0/24", "175.45.179.0/24"]
        self.assertEqual(sorted(bgp["prefixes"]), expected)
        for record in bgp["prefixes"].values():
            self.assertEqual(record["origins"], [131279])
            self.assertEqual(record["status"], "ok")

    def test_every_request_carries_sourceapp(self):
        recorder = RecordingFetch(FixtureFetcher(FIXTURES))
        ripestat.collect(Client(recorder, sleep=lambda seconds: None))
        self.assertGreaterEqual(len(recorder.urls), 9)
        for url in recorder.urls:
            self.assertTrue(url.startswith("https://stat.ripe.net/data/"), url)
            self.assertIn("sourceapp=kp-netwatch", url)

    def test_withdrawn_prefix_is_not_listed(self):
        directory = fixture_copy(self)

        def withdraw(data):
            for entry in data["data"]["prefixes"]:
                if entry["prefix"] == "175.45.179.0/24":
                    entry["timelines"] = [{"starttime": "2026-11-04T08:00:00", "endtime": "2026-11-10T08:00:00"}]

        edit_json(directory / "ripestat-announced-prefixes-AS131279.json", withdraw)
        bgp = ripestat.collect(client_for(directory))
        self.assertNotIn("175.45.179.0/24", bgp["prefixes"])
        self.assertEqual(len(bgp["prefixes"]), 3)

    def test_failing_endpoint_is_recorded_not_raised(self):
        directory = fixture_copy(self)
        make_error(directory, "ripestat-asn-neighbours-AS131279", "500")
        bgp = ripestat.collect(client_for(directory))
        asn = bgp["asns"]["131279"]
        self.assertEqual(asn["status"], "partial")
        self.assertIn("asn-neighbours", asn["errors"])
        self.assertEqual(bgp["status"], "partial")
        self.assertEqual(len(bgp["prefixes"]), 4)

    def test_failing_prefix_lookup_marks_only_that_prefix(self):
        directory = fixture_copy(self)
        make_error(directory, "ripestat-routing-status-175.45.177.0_24", "timed out")
        bgp = ripestat.collect(client_for(directory))
        self.assertEqual(bgp["prefixes"]["175.45.177.0/24"]["status"], "error")
        self.assertEqual(bgp["prefixes"]["175.45.176.0/24"]["status"], "ok")
        self.assertEqual(bgp["status"], "partial")

    def test_fallback_discovery_still_collects(self):
        directory = fixture_copy(self)
        make_error(directory, "ripestat-country-resource-list-kp", "502")
        bgp = ripestat.collect(client_for(directory))
        self.assertTrue(bgp["discovery"]["fallback"])
        self.assertEqual(list(bgp["asns"]), ["131279"])
        self.assertEqual(bgp["status"], "partial")


if __name__ == "__main__":
    unittest.main()
