import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from kpnetwatch import snapshot
from kpnetwatch.fixtures import FixtureFetcher
from kpnetwatch.webclient import Client

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 19, 3, 17, 5, tzinfo=timezone.utc)


class Sequence:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)

    def next(self):
        return self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]


class FakeFetch:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers)))
        for needle, outcome in self.routes:
            if needle in url:
                if isinstance(outcome, Sequence):
                    outcome = outcome.next()
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(f"unexpected request {url}")


def fake_client(routes):
    fetch = FakeFetch(routes)
    sleeps = []
    client = Client(fetch, sleep=sleeps.append)
    client.sleeps = sleeps
    return client, fetch


def client_for(directory=FIXTURES):
    return Client(FixtureFetcher(directory), sleep=lambda seconds: None)


def collect(directory=FIXTURES, now=NOW):
    return snapshot.collect(client_for(directory), now)


def fixture_copy(case):
    holder = tempfile.TemporaryDirectory()
    case.addCleanup(holder.cleanup)
    target = Path(holder.name) / "fixtures"
    shutil.copytree(FIXTURES, target)
    return target


def edit_json(path, change):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    change(data)
    Path(path).write_text(json.dumps(data), encoding="utf-8")


def make_error(directory, name, content):
    (Path(directory) / f"{name}.error").write_text(content, encoding="utf-8")
