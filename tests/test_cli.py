import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kpnetwatch import cli, snapshot

from support import FIXTURES, fixture_copy, make_error

ROOT = Path(__file__).resolve().parent.parent


class CliTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.folder = Path(holder.name)
        self.readme = self.folder / "README.md"
        self.readme.write_text("# t\n\n<!-- status:start -->\n<!-- status:end -->\n", encoding="utf-8")

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(list(args))
        return code, out.getvalue()

    def run_offline(self, fixtures=FIXTURES):
        return self.run_cli(
            "run",
            "--offline-fixtures",
            str(fixtures),
            "--data-dir",
            str(self.folder / "data"),
            "--changes",
            str(self.folder / "CHANGES.md"),
            "--readme",
            str(self.readme),
        )

    def test_run_writes_snapshot_latest_changes_and_readme(self):
        code, output = self.run_offline()
        self.assertEqual(code, 0)
        self.assertIn("wrote ", output)
        latest = self.folder / "data" / "latest.json"
        self.assertTrue(latest.exists())
        dated = list((self.folder / "data" / "snapshots").glob("*.json"))
        self.assertEqual(len(dated), 1)
        self.assertEqual(dated[0].read_bytes(), latest.read_bytes())
        self.assertIn("First snapshot.", (self.folder / "CHANGES.md").read_text(encoding="utf-8"))
        self.assertIn("| prefixes announced | 4 |", self.readme.read_text(encoding="utf-8"))

    def test_second_run_against_same_data_reports_no_changes(self):
        self.run_offline()
        self.run_offline()
        text = (self.folder / "CHANGES.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("\n## "), 2)
        self.assertIn("No changes since", text)

    def test_run_survives_every_crt_query_failing(self):
        directory = fixture_copy(self)
        for suffix in ("aca", "com", "edu", "gov", "law", "net", "org", "rep", "sca", "tra"):
            make_error(directory, f"crt-{suffix}.kp", "502")
        code, _ = self.run_offline(directory)
        self.assertEqual(code, 0)
        data = snapshot.load(self.folder / "data" / "latest.json")
        self.assertEqual(data["ct"]["status"], "error")
        self.assertEqual(data["summary"]["sources"]["ct"], "error")
        self.assertIn("Sources with errors: ct.", (self.folder / "CHANGES.md").read_text(encoding="utf-8"))

    def test_run_without_markers_still_succeeds(self):
        self.readme.write_text("# no markers\n", encoding="utf-8")
        code, _ = self.run_offline()
        self.assertEqual(code, 0)

    def test_diff_command_prints_changes(self):
        self.run_offline()
        latest = self.folder / "data" / "latest.json"
        first = self.folder / "first.json"
        first.write_bytes(latest.read_bytes())
        directory = fixture_copy(self)
        make_error(directory, "doh-kcna.kp-A", "500")
        self.run_offline(directory)
        code, output = self.run_cli("diff", str(first), str(latest))
        self.assertEqual(code, 0)
        self.assertIn("[dns] source error: 1 names (DoH lookup failed for kcna.kp)", output)
        code, output = self.run_cli("diff", str(first), str(first))
        self.assertEqual((code, output), (0, "no changes\n"))

    def test_report_command(self):
        self.run_offline()
        code, output = self.run_cli("report", "--file", str(self.folder / "data" / "latest.json"))
        self.assertEqual(code, 0)
        self.assertIn("1 ASN, 4 prefixes announced", output)

    def test_module_entry_point(self):
        self.run_offline()
        result = subprocess.run(
            [sys.executable, "-m", "kpnetwatch", "report", "--file", str(self.folder / "data" / "latest.json")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sources: bgp ok, ct ok, dns ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
