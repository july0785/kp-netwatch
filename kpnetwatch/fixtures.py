from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .webclient import FetchError


def fixture_name(url):
    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    if parts.hostname == "stat.ripe.net":
        endpoint = parts.path.split("/")[2]
        resource = query["resource"].replace("/", "_")
        return f"ripestat-{endpoint}-{resource}"
    if parts.hostname == "crt.sh":
        return "crt-" + query["q"].lstrip("%.")
    return f"doh-{query['name']}-{query['type']}"


class FixtureFetcher:
    def __init__(self, directory):
        self.directory = Path(directory)

    def __call__(self, url, headers, timeout):
        name = fixture_name(url)
        failure = self.directory / f"{name}.error"
        if failure.exists():
            text = failure.read_text(encoding="utf-8").strip()
            raise FetchError(f"HTTP {text}" if text.isdigit() else text, status=int(text) if text.isdigit() else None)
        path = self.directory / f"{name}.json"
        if not path.exists():
            raise FetchError(f"no fixture {path.name}", status=404)
        return path.read_bytes()
