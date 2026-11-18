import json
from datetime import datetime, timezone
from pathlib import Path

from . import crtsh, dnsdoh, ripestat

SCHEMA = 1
TOOL = "kp-netwatch/0.1"
SEED_DOMAINS = (
    "kcna.kp",
    "kp",
    "kza.org.kp",
    "naenara.com.kp",
    "ns1.kptc.kp",
    "ns2.kptc.kp",
    "portal.net.kp",
    "rodong.rep.kp",
    "star-co.net.kp",
    "star.net.kp",
)


def iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text):
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def candidate_names(certs):
    sources = {}
    for name in SEED_DOMAINS:
        sources.setdefault(name, set()).add("seed")
    for cert in certs:
        for name in cert["names"]:
            name = name.removeprefix("*.")
            if "*" in name or not name.endswith(".kp"):
                continue
            sources.setdefault(name, set()).add("ct")
            labels = name.split(".")
            if len(labels) >= 3:
                sources.setdefault(".".join(labels[-3:]), set()).add("ct")
    return {name: sorted(found) for name, found in sources.items()}


def summarize(snap):
    now = parse_time(snap["generated_at"])
    certs = snap["ct"]["certs"]
    domains = snap["dns"]["domains"]
    return {
        "asns": len(snap["bgp"]["asns"]),
        "prefixes_announced": len(snap["bgp"]["prefixes"]),
        "certs": len(certs),
        "certs_unexpired": sum(1 for cert in certs if cert["not_after"] and parse_time(cert["not_after"]) > now),
        "domains": len(domains),
        "domains_resolving": sum(1 for record in domains.values() if dnsdoh.resolving(record)),
        "sources": {name: snap[name]["status"] for name in ("bgp", "ct", "dns")},
    }


def collect(client, now):
    bgp = ripestat.collect(client)
    ct = crtsh.collect(client)
    dns = dnsdoh.collect(client, candidate_names(ct["certs"]))
    snap = {"schema": SCHEMA, "tool": TOOL, "generated_at": iso(now), "bgp": bgp, "ct": ct, "dns": dns}
    snap["summary"] = summarize(snap)
    return snap


def dumps(snap):
    return json.dumps(snap, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(snap, data_dir):
    data_dir = Path(data_dir)
    snapshots = data_dir / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    text = dumps(snap)
    dated = snapshots / f"{snap['generated_at'][:10]}.json"
    for path in (dated, data_dir / "latest.json"):
        path.write_text(text, encoding="utf-8", newline="\n")
    return dated
