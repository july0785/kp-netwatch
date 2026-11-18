import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from kpnetwatch import snapshot

from support import NOW, collect


class SnapshotTests(unittest.TestCase):
    def test_same_inputs_give_identical_bytes(self):
        first = snapshot.dumps(collect())
        second = snapshot.dumps(collect())
        self.assertEqual(first, second)

    def test_output_is_sorted_and_ends_with_newline(self):
        text = snapshot.dumps(collect())
        data = json.loads(text)
        self.assertEqual(text, json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
        ids = [cert["id"] for cert in data["ct"]["certs"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(list(data["bgp"]["prefixes"]), sorted(data["bgp"]["prefixes"]))

    def test_top_level_shape(self):
        data = collect()
        self.assertEqual(sorted(data), ["bgp", "ct", "dns", "generated_at", "schema", "summary", "tool"])
        self.assertEqual(data["generated_at"], "2026-11-19T03:17:05Z")
        self.assertEqual(data["schema"], 1)

    def test_summary_counts(self):
        summary = collect()["summary"]
        self.assertEqual(summary["asns"], 1)
        self.assertEqual(summary["prefixes_announced"], 4)
        self.assertEqual(summary["domains"], 15)
        self.assertEqual(summary["domains_resolving"], 5)
        self.assertEqual(summary["certs_unexpired"], 0)
        self.assertEqual(summary["sources"], {"bgp": "ok", "ct": "ok", "dns": "ok"})

    def test_unexpired_count_depends_on_the_clock(self):
        earlier = collect(now=datetime(2025, 9, 23, tzinfo=timezone.utc))
        self.assertGreater(earlier["summary"]["certs_unexpired"], 0)

    def test_candidate_names_merge_seeds_and_ct(self):
        certs = [
            {"names": ["*.kza.org.kp", "kza.org.kp"]},
            {"names": ["sns.star.net.kp"]},
            {"names": ["*.*.bad.kp", "example.com"]},
        ]
        names = snapshot.candidate_names(certs)
        self.assertEqual(names["kza.org.kp"], ["ct", "seed"])
        self.assertEqual(names["sns.star.net.kp"], ["ct"])
        self.assertEqual(names["star.net.kp"], ["ct", "seed"])
        self.assertEqual(names["kcna.kp"], ["seed"])
        self.assertNotIn("example.com", names)
        self.assertFalse(any("*" in name for name in names))

    def test_write_creates_dated_file_and_latest(self):
        data = collect()
        with tempfile.TemporaryDirectory() as folder:
            path = snapshot.write(data, folder)
            self.assertEqual(path.name, "2026-11-19.json")
            latest = Path(folder) / "latest.json"
            self.assertEqual(path.read_bytes(), latest.read_bytes())
            self.assertEqual(snapshot.load(latest), data)
            self.assertNotIn(b"\r\n", latest.read_bytes())

    def test_parse_time_treats_naive_stamps_as_utc(self):
        self.assertEqual(snapshot.parse_time("2026-07-19T01:11:16"), datetime(2026, 7, 19, 1, 11, 16, tzinfo=timezone.utc))
        self.assertEqual(snapshot.parse_time("2026-11-19T03:17:05Z"), NOW)


if __name__ == "__main__":
    unittest.main()
