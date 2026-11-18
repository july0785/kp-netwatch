from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from .webclient import COLLECT_ERRORS, FetchError, describe
from .ripestat import rollup

RESOLVERS = (
    ("cloudflare-dns.com", "https://cloudflare-dns.com/dns-query"),
    ("dns.google", "https://dns.google/resolve"),
)
RECORD_TYPES = ("A", "AAAA", "NS", "MX", "SOA")
TYPE_NAMES = {1: "A", 28: "AAAA", 2: "NS", 15: "MX", 6: "SOA", 5: "CNAME"}
RCODES = {0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED"}
TIMEOUT = 20


def ask(client, name, rtype):
    failure = None
    servfail = None
    for host, base in RESOLVERS:
        url = base + "?" + urlencode({"name": name, "type": rtype})
        try:
            payload = client.get_json(url, headers={"accept": "application/dns-json"}, timeout=TIMEOUT, attempts=2, backoff=1.0)
        except FetchError as error:
            failure = error
            continue
        if payload.get("Status") == 2:
            servfail = (host, payload)
            continue
        return host, payload
    if servfail:
        return servfail
    raise failure


def normalize(data):
    return " ".join(token.rstrip(".") for token in data.lower().split())


def parse(payload):
    code = payload["Status"]
    rcode = RCODES.get(code, f"RCODE{code}")
    records = {}
    for answer in payload.get("Answer", []):
        rtype = TYPE_NAMES.get(answer["type"])
        if rtype:
            records.setdefault(rtype, set()).add(normalize(answer["data"]))
    return rcode, records


def resolve_name(client, name):
    rcodes = {}
    records = {}
    resolvers = set()
    failed = []
    for rtype in RECORD_TYPES:
        try:
            host, payload = ask(client, name, rtype)
            rcode, found = parse(payload)
        except COLLECT_ERRORS as error:
            failed.append(describe(error))
            continue
        resolvers.add(host)
        rcodes[rtype] = rcode
        for kind, values in found.items():
            records.setdefault(kind, set()).update(values)
    unanswered = sorted(rtype for rtype, rcode in rcodes.items() if rcode not in ("NOERROR", "NXDOMAIN"))
    status = "NOERROR"
    if "NXDOMAIN" in rcodes.values():
        status = "NXDOMAIN"
    elif rcodes and len(unanswered) == len(rcodes):
        status = "SERVFAIL" if "SERVFAIL" in rcodes.values() else sorted(set(rcodes.values()))[0]
    result = {
        "status": status,
        "unanswered": unanswered,
        "records": {kind: sorted(values) for kind, values in sorted(records.items())},
    }
    if failed:
        result["status"] = "error"
        result["error"] = failed[0]
    return result, resolvers


def resolving(record):
    return bool(record["records"].get("A") or record["records"].get("AAAA"))


def collect(client, names, workers=4):
    ordered = sorted(names)
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda name: resolve_name(client, name), ordered))
    domains = {}
    resolvers = set()
    for name, (record, used) in zip(ordered, results):
        record["sources"] = list(names[name])
        domains[name] = record
        resolvers |= used
    return {
        "status": rollup(record["status"] if record["status"] == "error" else "ok" for record in domains.values()),
        "resolvers": sorted(resolvers),
        "domains": domains,
    }
