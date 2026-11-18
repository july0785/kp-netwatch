import ipaddress
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from .webclient import COLLECT_ERRORS, FetchError, describe

BASE_URL = "https://stat.ripe.net/data/{}/data.json"
SOURCEAPP = "kp-netwatch"
FALLBACK_ASNS = ("131279",)
TIMEOUT = 45


def rollup(statuses):
    statuses = list(statuses)
    if all(status == "ok" for status in statuses):
        return "ok"
    if all(status == "error" for status in statuses):
        return "error"
    return "partial"


def call(client, endpoint, **params):
    url = BASE_URL.format(endpoint) + "?" + urlencode({**params, "sourceapp": SOURCEAPP})
    payload = client.get_json(url, timeout=TIMEOUT)
    if payload.get("status") != "ok":
        raise FetchError(f"{endpoint}: {payload.get('message') or payload.get('status')}")
    return payload["data"]


def network_key(prefix):
    network = ipaddress.ip_network(prefix)
    return (network.version, int(network.network_address), network.prefixlen)


def discover(client):
    try:
        data = call(client, "country-resource-list", resource="kp")
        resources = data["resources"]
        asns = sorted({str(asn) for asn in resources["asn"]}, key=int)
        if not asns:
            raise ValueError("country-resource-list returned no ASNs")
        return {
            "status": "ok",
            "source": "country-resource-list",
            "fallback": False,
            "query_time": data.get("query_time"),
            "asn": asns,
            "ipv4": sorted(resources.get("ipv4", []), key=network_key),
            "ipv6": sorted(resources.get("ipv6", []), key=network_key),
        }
    except COLLECT_ERRORS as error:
        return {
            "status": "error",
            "error": describe(error),
            "source": "fallback-seed",
            "fallback": True,
            "asn": list(FALLBACK_ASNS),
            "ipv4": [],
            "ipv6": [],
        }


def parse_overview(data):
    return {"holder": data.get("holder"), "announced": bool(data.get("announced"))}


def parse_announced(data):
    latest = data.get("latest_time") or data["query_endtime"]
    current = {
        entry["prefix"]
        for entry in data["prefixes"]
        if any(timeline["endtime"] >= latest for timeline in entry.get("timelines", []))
    }
    return {"prefixes": sorted(current, key=network_key)}


def parse_routing(data):
    visibility = {
        family: {"seeing": value["ris_peers_seeing"], "total": value["total_ris_peers"]}
        for family, value in data["visibility"].items()
    }
    return {
        "visibility": visibility,
        "observed_neighbours": data.get("observed_neighbours"),
        "first_seen": (data.get("first_seen") or {}).get("time"),
    }


def parse_neighbours(data):
    neighbours = [{"asn": int(item["asn"]), "type": item["type"]} for item in data["neighbours"]]
    return {"neighbours": sorted(neighbours, key=lambda item: (item["asn"], item["type"]))}


ASN_STEPS = (
    ("as-overview", parse_overview),
    ("announced-prefixes", parse_announced),
    ("routing-status", parse_routing),
    ("asn-neighbours", parse_neighbours),
)


def collect_asn(client, asn):
    record = {"prefixes": []}
    errors = {}
    for endpoint, parse in ASN_STEPS:
        try:
            record.update(parse(call(client, endpoint, resource=f"AS{asn}")))
        except COLLECT_ERRORS as error:
            errors[endpoint] = describe(error)
    record["errors"] = errors
    record["status"] = rollup(["error" if name in errors else "ok" for name, _ in ASN_STEPS])
    return record


def collect_prefix(client, prefix, asn):
    try:
        data = call(client, "routing-status", resource=prefix)
        family = f"v{ipaddress.ip_network(prefix).version}"
        seen = data["visibility"][family]
        origins = sorted({int(item["origin"]) for item in data.get("origins", [])})
        return {
            "asn": asn,
            "status": "ok",
            "origins": origins,
            "visibility": {"seeing": seen["ris_peers_seeing"], "total": seen["total_ris_peers"]},
        }
    except COLLECT_ERRORS as error:
        return {"asn": asn, "status": "error", "error": describe(error)}


def collect(client, workers=4):
    discovery = discover(client)
    asns = {asn: collect_asn(client, asn) for asn in discovery["asn"]}
    jobs = [(prefix, asn) for asn, record in asns.items() for prefix in record["prefixes"]]
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda job: collect_prefix(client, *job), jobs))
    prefixes = {prefix: result for (prefix, _), result in zip(jobs, results)}
    statuses = [discovery["status"]]
    statuses += [record["status"] for record in asns.values()]
    statuses += [result["status"] for result in prefixes.values()]
    return {"status": rollup(statuses), "discovery": discovery, "asns": asns, "prefixes": prefixes}
