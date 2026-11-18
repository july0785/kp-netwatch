import json
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

USER_AGENT = "kp-netwatch/0.1"
ALLOWED_HOSTS = frozenset({"stat.ripe.net", "crt.sh", "cloudflare-dns.com", "dns.google"})
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class FetchError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class BlockedRequest(Exception):
    pass


COLLECT_ERRORS = (FetchError, KeyError, TypeError, ValueError, AttributeError)


def describe(error):
    if isinstance(error, FetchError):
        return str(error)
    return f"{type(error).__name__}: {error}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def urllib_fetch(url, headers, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with _opener.open(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise FetchError(f"HTTP {error.code}", status=error.code) from error
    except (urllib.error.URLError, socket.timeout, OSError) as error:
        raise FetchError(f"{type(error).__name__}: {error}") from error


def check_allowed(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise BlockedRequest(f"refusing to contact {parts.hostname}")


class Client:
    def __init__(self, fetch=urllib_fetch, sleep=time.sleep):
        self.fetch = fetch
        self.sleep = sleep

    def get_json(self, url, headers=None, timeout=30, attempts=3, backoff=2.0, retry_statuses=RETRY_STATUSES):
        check_allowed(url)
        failure = None
        for attempt in range(attempts):
            if attempt:
                self.sleep(backoff * 2 ** (attempt - 1))
            try:
                body = self.fetch(url, headers or {}, timeout)
            except FetchError as error:
                if error.status is not None and error.status not in retry_statuses:
                    raise
                failure = error
                continue
            try:
                return json.loads(body)
            except ValueError as error:
                failure = FetchError(f"invalid JSON: {error}")
        raise failure
