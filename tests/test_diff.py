import unittest
from datetime import datetime, timezone

from kpnetwatch import diff

from support import collect, edit_json, fixture_copy, make_error


def kinds(changes):
    return [item["kind"] for item in changes]


def only(changes, kind):
    return [item for item in changes if item["kind"] == kind]


def doh(directory, name, rtype, answers=None, status=0):
    code = {"A": 1, "AAAA": 28, "NS": 2, "MX": 15, "SOA": 6}[rtype]
    body = {"Status": status, "Question": [{"name": name, "type": code}]}
    if answers:
        body["Answer"] = [{"name": name, "type": code, "TTL": 60, "data": item} for item in answers]
    edit_json(directory / f"doh-{name}-{rtype}.json", lambda data: (data.clear(), data.update(body)))


class BgpDiffTests(unittest.TestCase):
    def test_identical_snapshots_have_no_changes(self):
        self.assertEqual(diff.compare(collect(), collect()), [])

    def test_prefix_withdrawn_and_new(self):
        directory = fixture_copy(self)

        def withdraw(data):
            data["data"]["prefixes"] = [entry for entry in data["data"]["prefixes"] if entry["prefix"] != "175.45.178.0/24"]

        edit_json(directory / "ripestat-announced-prefixes-AS131279.json", withdraw)
        reduced = collect(directory)
        full = collect()
        withdrawn = diff.compare(full, reduced)
        self.assertEqual(kinds(withdrawn), ["prefix_withdrawn"])
        self.assertEqual(withdrawn[0]["subject"], "175.45.178.0/24")
        self.assertIn("322/322", withdrawn[0]["detail"])
        added = diff.compare(reduced, full)
        self.assertEqual(kinds(added), ["prefix_new"])
        self.assertEqual(added[0]["subject"], "175.45.178.0/24")

    def test_visibility_drop_and_rise(self):
        directory = fixture_copy(self)

        def thin(data):
            data["data"]["visibility"]["v4"]["ris_peers_seeing"] = 100

        edit_json(directory / "ripestat-routing-status-175.45.176.0_24.json", thin)
        degraded = collect(directory)
        full = collect()
        drop = diff.compare(full, degraded)
        self.assertEqual(kinds(drop), ["visibility_drop"])
        self.assertEqual(drop[0]["subject"], "175.45.176.0/24")
        self.assertEqual(drop[0]["detail"], "322/322 peers -> 100/322 peers")
        self.assertEqual(kinds(diff.compare(degraded, full)), ["visibility_rise"])

    def test_small_visibility_wobble_is_ignored(self):
        directory = fixture_copy(self)
        edit_json(directory / "ripestat-routing-status-175.45.176.0_24.json", lambda data: data["data"]["visibility"]["v4"].update(ris_peers_seeing=320))
        self.assertEqual(diff.compare(collect(), collect(directory)), [])

    def test_origin_change(self):
        directory = fixture_copy(self)
        edit_json(directory / "ripestat-routing-status-175.45.177.0_24.json", lambda data: data["data"]["origins"][0].update(origin=64496))
        found = diff.compare(collect(), collect(directory))
        self.assertEqual(kinds(found), ["prefix_origin_changed"])
        self.assertEqual(found[0]["detail"], "AS131279 -> AS64496")

    def test_upstream_removed(self):
        directory = fixture_copy(self)

        def drop(data):
            data["data"]["neighbours"] = [item for item in data["data"]["neighbours"] if item["asn"] != 20485]

        edit_json(directory / "ripestat-asn-neighbours-AS131279.json", drop)
        found = diff.compare(collect(), collect(directory))
        self.assertEqual(kinds(found), ["upstream_removed"])
        self.assertEqual(found[0]["subject"], "AS20485")

    def test_new_asn_and_allocation_from_discovery(self):
        directory = fixture_copy(self)

        def grow(data):
            data["data"]["resources"]["asn"].append("64511")
            data["data"]["resources"]["ipv4"].append("192.0.2.0/24")

        edit_json(directory / "ripestat-country-resource-list-kp.json", grow)
        found = diff.compare(collect(), collect(directory))
        self.assertEqual([item["subject"] for item in only(found, "asn_added")], ["64511"])
        self.assertEqual([item["subject"] for item in only(found, "allocation_added")], ["192.0.2.0/24"])

    def test_failed_discovery_does_not_remove_anything(self):
        directory = fixture_copy(self)
        make_error(directory, "ripestat-country-resource-list-kp", "500")
        found = diff.compare(collect(), collect(directory))
        self.assertEqual(kinds(found), ["source_error"])
        self.assertIn("fallback", found[0]["detail"])

    def test_failed_prefix_listing_does_not_withdraw_prefixes(self):
        directory = fixture_copy(self)
        make_error(directory, "ripestat-announced-prefixes-AS131279", "500")
        found = diff.compare(collect(), collect(directory))
        self.assertNotIn("prefix_withdrawn", kinds(found))
        self.assertEqual(kinds(found), ["source_error"])
        self.assertEqual(found[0]["subject"], "AS131279 announced-prefixes")

    def test_holder_change(self):
        directory = fixture_copy(self)
        edit_json(directory / "ripestat-as-overview-AS131279.json", lambda data: data["data"].update(holder="OTHER-KP"))
        found = diff.compare(collect(), collect(directory))
        self.assertEqual(kinds(found), ["asn_holder_changed"])


class CtDiffTests(unittest.TestCase):
    def setUp(self):
        self.full = collect()

    def without_newest_org_cert(self):
        directory = fixture_copy(self)

        def trim(rows):
            rows[:] = [row for row in rows if row["not_before"] < "2026-04-20"]

        edit_json(directory / "crt-org.kp.json", trim)
        return collect(directory)

    def test_new_certificate_is_grouped_by_serial(self):
        older = self.without_newest_org_cert()
        found = diff.compare(older, self.full)
        self.assertEqual(kinds(found), ["cert_new"])
        self.assertEqual(found[0]["subject"], "*.kza.org.kp, kza.org.kp")
        self.assertIn("Let's Encrypt", found[0]["detail"])

    def test_certificate_gone(self):
        older = self.without_newest_org_cert()
        self.assertEqual(kinds(diff.compare(self.full, older)), ["cert_removed"])

    def test_certificate_expiry_between_runs(self):
        before = collect(now=datetime(2026, 7, 18, 3, 0, tzinfo=timezone.utc))
        after = collect(now=datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc))
        found = diff.compare(before, after)
        self.assertEqual(kinds(found), ["cert_expired"])
        self.assertIn("kza.org.kp", found[0]["subject"])
        self.assertEqual(diff.compare(after, after), [])

    def test_failed_crt_query_does_not_remove_certificates(self):
        directory = fixture_copy(self)
        make_error(directory, "crt-org.kp", "502")
        failed = collect(directory)
        found = diff.compare(self.full, failed)
        self.assertEqual(kinds(found), ["source_error"])
        self.assertEqual(found[0]["subject"], "crt.sh %.org.kp")
        self.assertEqual(kinds(diff.compare(failed, self.full)), [])


class DnsDiffTests(unittest.TestCase):
    def test_record_change_shows_added_and_removed_values(self):
        directory = fixture_copy(self)
        doh(directory, "kcna.kp", "A", ["175.45.176.71", "203.0.113.9"])
        found = diff.compare(collect(), collect(directory))
        self.assertEqual(kinds(found), ["dns_record_changed"])
        self.assertEqual(found[0]["subject"], "kcna.kp A")
        self.assertEqual(found[0]["detail"], "+203.0.113.9 -175.45.177.1")

    def test_status_change_is_reported_without_record_noise(self):
        directory = fixture_copy(self)
        for rtype in ("A", "AAAA", "NS", "MX", "SOA"):
            doh(directory, "kcna.kp", rtype, status=3)
        found = diff.compare(collect(), collect(directory))
        self.assertEqual(kinds(found), ["dns_status_changed"])
        self.assertEqual(found[0]["detail"], "NOERROR -> NXDOMAIN")

    def test_unanswered_types_are_not_compared(self):
        directory = fixture_copy(self)
        doh(directory, "kcna.kp", "A", status=2)
        flaky = collect(directory)
        self.assertEqual(flaky["dns"]["domains"]["kcna.kp"]["unanswered"], ["A"])
        self.assertEqual(diff.compare(collect(), flaky), [])
        self.assertEqual(diff.compare(flaky, collect()), [])

    def test_total_servfail_is_reported_as_status_change(self):
        directory = fixture_copy(self)
        for rtype in ("A", "AAAA", "NS", "MX", "SOA"):
            doh(directory, "kcna.kp", rtype, status=2)
        found = diff.compare(collect(), collect(directory))
        self.assertEqual(kinds(found), ["dns_status_changed"])
        self.assertEqual(found[0]["detail"], "NOERROR -> SERVFAIL")

    def test_lookup_failure_is_a_source_error_not_a_change(self):
        directory = fixture_copy(self)
        make_error(directory, "doh-kcna.kp-A", "500")
        found = diff.compare(collect(), collect(directory))
        self.assertEqual(kinds(found), ["source_error"])
        self.assertIn("kcna.kp", found[0]["detail"])

    def test_new_domain_from_ct_is_listed(self):
        directory = fixture_copy(self)

        def extend(rows):
            rows.append({**rows[0], "id": 1, "name_value": "mail.kza.org.kp", "common_name": "mail.kza.org.kp", "serial_number": "ff"})

        edit_json(directory / "crt-org.kp.json", extend)
        found = diff.compare(collect(), collect(directory))
        self.assertEqual(only(found, "dns_domain_added")[0]["subject"], "mail.kza.org.kp")
        self.assertIn("cert_new", kinds(found))


class OrderingTests(unittest.TestCase):
    def test_output_is_deterministic_and_grouped_by_section(self):
        directory = fixture_copy(self)
        doh(directory, "kcna.kp", "A", ["203.0.113.9"])
        edit_json(directory / "ripestat-routing-status-175.45.176.0_24.json", lambda data: data["data"]["visibility"]["v4"].update(ris_peers_seeing=10))
        make_error(directory, "crt-org.kp", "502")
        found = diff.compare(collect(), collect(directory))
        self.assertEqual(found, diff.compare(collect(), collect(directory)))
        sections = [item["section"] for item in found]
        self.assertEqual(sections, sorted(sections, key=diff.SECTIONS.index))
        self.assertEqual(sections[0], "bgp")
        self.assertEqual(sections[-1], "dns")


if __name__ == "__main__":
    unittest.main()
