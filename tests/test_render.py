import tempfile
import unittest
from pathlib import Path

from kpnetwatch import diff, render

from support import collect, edit_json, fixture_copy


class EntryTests(unittest.TestCase):
    def test_first_snapshot_has_no_comparison(self):
        text = render.entry(collect(), None, None)
        self.assertTrue(text.startswith("## 2026-11-19 03:17 UTC\n"))
        self.assertIn("First snapshot. 1 ASN, 4 prefixes announced, 47 certificates (0 unexpired), 5/15 names resolving.", text)

    def test_no_changes_is_a_single_line(self):
        snap = collect()
        text = render.entry(snap, snap, [])
        self.assertEqual(text, "## 2026-11-19 03:17 UTC\n\nNo changes since 2026-11-19 03:17 UTC.\n")

    def test_changes_are_listed_one_per_line(self):
        directory = fixture_copy(self)

        def withdraw(data):
            data["data"]["prefixes"] = [entry for entry in data["data"]["prefixes"] if entry["prefix"] != "175.45.178.0/24"]

        edit_json(directory / "ripestat-announced-prefixes-AS131279.json", withdraw)
        old, new = collect(), collect(directory)
        text = render.entry(new, old, diff.compare(old, new))
        self.assertIn("- [bgp] prefix withdrawn: 175.45.178.0/24 (was announced by AS131279, seen by 322/322 peers)", text)
        self.assertEqual(text.count("\n- "), 1)

    def test_every_change_kind_has_a_label(self):
        directory = fixture_copy(self)
        edit_json(directory / "ripestat-as-overview-AS131279.json", lambda data: data["data"].update(holder="OTHER"))
        found = diff.compare(collect(), collect(directory))
        for item in found:
            self.assertIn(item["kind"], render.LABELS)


class ChangesFileTests(unittest.TestCase):
    def test_creates_file_and_prepends_newest_first(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "CHANGES.md"
            render.prepend_changes(path, "## 2026-11-18 03:17 UTC\n\nFirst snapshot.\n")
            render.prepend_changes(path, "## 2026-11-19 03:17 UTC\n\nNo changes since 2026-11-18 03:17 UTC.\n")
            text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Changes\n"))
        self.assertEqual(text.count("# Changes"), 1)
        self.assertLess(text.index("2026-11-19"), text.index("2026-11-18"))
        self.assertIn("\n\n## 2026-11-19", text)
        self.assertIn("\n\n## 2026-11-18", text)

    def test_existing_header_text_is_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "CHANGES.md"
            path.write_text("# Changes\n\nnotes about this file\n\n## 2026-01-01 00:00 UTC\n\nold\n", encoding="utf-8")
            render.prepend_changes(path, "## 2026-01-02 00:00 UTC\n\nnew\n")
            text = path.read_text(encoding="utf-8")
        self.assertIn("notes about this file", text)
        self.assertLess(text.index("2026-01-02"), text.index("2026-01-01"))


class ReadmeTests(unittest.TestCase):
    TEMPLATE = "# kp-netwatch\n\nintro\n\n<!-- status:start -->\nold table\n<!-- status:end -->\n\nrest of the file\n"

    def write_readme(self, folder, text=TEMPLATE):
        path = Path(folder) / "README.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_replaces_only_the_marked_block(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_readme(folder)
            render.update_readme(path, collect())
            text = path.read_text(encoding="utf-8")
        self.assertNotIn("old table", text)
        self.assertTrue(text.startswith("# kp-netwatch\n\nintro\n\n<!-- status:start -->\n| item | value |"))
        self.assertIn("| ASNs | 1 |", text)
        self.assertIn("| prefixes announced | 4 |", text)
        self.assertIn("| certificates in CT | 47 (0 unexpired) |", text)
        self.assertIn("| names resolving | 5 |", text)
        self.assertIn("| last run | 2026-11-19 03:17 UTC |", text)
        self.assertTrue(text.endswith("<!-- status:end -->\n\nrest of the file\n"))

    def test_update_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_readme(folder)
            render.update_readme(path, collect())
            once = path.read_text(encoding="utf-8")
            render.update_readme(path, collect())
            self.assertEqual(path.read_text(encoding="utf-8"), once)

    def test_missing_markers_raise(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_readme(folder, "# no markers here\n")
            with self.assertRaises(render.MarkersMissing):
                render.update_readme(path, collect())
            self.assertEqual(path.read_text(encoding="utf-8"), "# no markers here\n")

    def test_report_lists_prefixes_and_names(self):
        text = render.report(collect())
        self.assertIn("AS131279 STAR-KP - Ryugyong-dong", text)
        self.assertIn("175.45.177.0/24 321/322 peers", text)
        self.assertIn("kcna.kp NOERROR 175.45.176.71, 175.45.177.1", text)


if __name__ == "__main__":
    unittest.main()
