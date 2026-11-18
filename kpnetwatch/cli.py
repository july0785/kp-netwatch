import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import diff, render, snapshot
from .fixtures import FixtureFetcher
from .webclient import Client


def build_client(fixtures):
    if fixtures:
        return Client(FixtureFetcher(fixtures), sleep=lambda seconds: None)
    return Client()


def run(args):
    client = build_client(args.offline_fixtures)
    current = snapshot.collect(client, datetime.now(timezone.utc))
    data_dir = Path(args.data_dir)
    latest = data_dir / "latest.json"
    previous = snapshot.load(latest) if latest.exists() else None
    changes = diff.compare(previous, current) if previous else None
    path = snapshot.write(current, data_dir)
    render.prepend_changes(args.changes, render.entry(current, previous, changes))
    readme = Path(args.readme)
    if readme.exists():
        try:
            render.update_readme(readme, current)
        except render.MarkersMissing as error:
            print(f"warning: {error}", file=sys.stderr)
    print(render.report(current))
    print(f"wrote {path}")
    return 0


def show_diff(args):
    changes = diff.compare(snapshot.load(args.old), snapshot.load(args.new))
    if not changes:
        print("no changes")
    for item in changes:
        print(render.change_line(item))
    return 0


def show_report(args):
    print(render.report(snapshot.load(args.file)))
    return 0


def parser():
    root = argparse.ArgumentParser(prog="kpnetwatch", description="passive monitor of the KP public internet footprint")
    commands = root.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="collect, diff against data/latest.json, write outputs")
    run_parser.add_argument("--data-dir", default="data")
    run_parser.add_argument("--changes", default="CHANGES.md")
    run_parser.add_argument("--readme", default="README.md")
    run_parser.add_argument("--offline-fixtures", metavar="DIR")
    run_parser.set_defaults(handler=run)
    diff_parser = commands.add_parser("diff", help="compare two snapshot files")
    diff_parser.add_argument("old")
    diff_parser.add_argument("new")
    diff_parser.set_defaults(handler=show_diff)
    report_parser = commands.add_parser("report", help="print a summary of a snapshot")
    report_parser.add_argument("--file", default="data/latest.json")
    report_parser.set_defaults(handler=show_report)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    return args.handler(args)
