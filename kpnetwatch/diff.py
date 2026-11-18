from . import crtsh
from .snapshot import parse_time

VISIBILITY_STEP = 0.05
SECTIONS = ("bgp", "ct", "dns")


def change(section, kind, subject, detail=""):
    return {"section": section, "kind": kind, "subject": subject, "detail": detail}


def ratio(visibility):
    if not visibility or not visibility["total"]:
        return None
    return visibility["seeing"] / visibility["total"]


def peers(visibility):
    return f"{visibility['seeing']}/{visibility['total']} peers"


def visibility_changes(subject, old, new):
    before, after = ratio(old), ratio(new)
    if before is None or after is None or abs(after - before) < VISIBILITY_STEP:
        return []
    kind = "visibility_drop" if after < before else "visibility_rise"
    return [change("bgp", kind, subject, f"{peers(old)} -> {peers(new)}")]


def set_changes(section, added_kind, removed_kind, old, new, detail=""):
    found = [change(section, added_kind, item, detail) for item in sorted(set(new) - set(old))]
    found += [change(section, removed_kind, item, detail) for item in sorted(set(old) - set(new))]
    return found


def compare_asn(asn, old, new):
    found = []
    if "as-overview" not in old["errors"] and "as-overview" not in new["errors"]:
        if old["holder"] != new["holder"]:
            found.append(change("bgp", "asn_holder_changed", f"AS{asn}", f"{old['holder']} -> {new['holder']}"))
        if old["announced"] != new["announced"]:
            state = "announced" if new["announced"] else "not announced"
            found.append(change("bgp", "asn_announced_changed", f"AS{asn}", f"now {state}"))
    if "asn-neighbours" not in old["errors"] and "asn-neighbours" not in new["errors"]:
        before = {item["asn"] for item in old["neighbours"]}
        after = {item["asn"] for item in new["neighbours"]}
        found += [change("bgp", "upstream_added", f"AS{item}", f"neighbour of AS{asn}") for item in sorted(after - before)]
        found += [change("bgp", "upstream_removed", f"AS{item}", f"neighbour of AS{asn}") for item in sorted(before - after)]
    if "routing-status" not in old["errors"] and "routing-status" not in new["errors"]:
        for family in sorted(set(old["visibility"]) & set(new["visibility"])):
            found += visibility_changes(f"AS{asn} {family}", old["visibility"][family], new["visibility"][family])
    return found


def compare_bgp(old, new):
    found = []
    old_discovery, new_discovery = old["discovery"], new["discovery"]
    if old_discovery["status"] == "ok" and new_discovery["status"] == "ok":
        found += set_changes("bgp", "asn_added", "asn_removed", old_discovery["asn"], new_discovery["asn"])
        found += set_changes(
            "bgp",
            "allocation_added",
            "allocation_removed",
            old_discovery["ipv4"] + old_discovery["ipv6"],
            new_discovery["ipv4"] + new_discovery["ipv6"],
        )
    trusted = []
    for asn in sorted(set(old["asns"]) & set(new["asns"])):
        before, after = old["asns"][asn], new["asns"][asn]
        found += compare_asn(asn, before, after)
        if "announced-prefixes" not in before["errors"] and "announced-prefixes" not in after["errors"]:
            trusted.append(asn)
    old_prefixes = {p: r for p, r in old["prefixes"].items() if r["asn"] in trusted}
    new_prefixes = {p: r for p, r in new["prefixes"].items() if r["asn"] in trusted}
    for prefix in sorted(set(new_prefixes) - set(old_prefixes)):
        found.append(change("bgp", "prefix_new", prefix, f"announced by AS{new_prefixes[prefix]['asn']}"))
    for prefix in sorted(set(old_prefixes) - set(new_prefixes)):
        before = old_prefixes[prefix]
        detail = f"was announced by AS{before['asn']}"
        if before["status"] == "ok":
            detail += f", seen by {peers(before['visibility'])}"
        found.append(change("bgp", "prefix_withdrawn", prefix, detail))
    for prefix in sorted(set(old_prefixes) & set(new_prefixes)):
        before, after = old_prefixes[prefix], new_prefixes[prefix]
        if before["status"] != "ok" or after["status"] != "ok":
            continue
        if before["origins"] != after["origins"]:
            origins = lambda item: ",".join(f"AS{o}" for o in item["origins"]) or "none"
            found.append(change("bgp", "prefix_origin_changed", prefix, f"{origins(before)} -> {origins(after)}"))
        found += visibility_changes(prefix, before["visibility"], after["visibility"])
    return found


def cert_groups(certs, usable):
    groups = {}
    for cert in certs:
        suffixes = {crtsh.suffix_of(name) for name in cert["names"]} - {None}
        if suffixes and not suffixes & usable:
            continue
        key = cert.get("serial") or f"id:{cert['id']}"
        groups.setdefault(key, []).append(cert)
    return groups


def cert_label(certs):
    names = sorted({name for cert in certs for name in cert["names"]})
    return ", ".join(names)


def cert_detail(certs):
    first = min(certs, key=lambda cert: cert["id"])
    issuer = first["issuer"] or "unknown issuer"
    return f"{issuer}, {first['not_before']} to {first['not_after']}, crt.sh id {first['id']}"


def usable_suffixes(old, new):
    usable = set()
    for query, info in old["queries"].items():
        if info["status"] == "ok" and new["queries"].get(query, {}).get("status") == "ok":
            usable.add(crtsh.suffix_of(query))
    return usable


def compare_ct(old_snap, new_snap):
    old, new = old_snap["ct"], new_snap["ct"]
    usable = usable_suffixes(old, new)
    before = cert_groups(old["certs"], usable)
    after = cert_groups(new["certs"], usable)
    found = []
    for key in sorted(set(after) - set(before)):
        found.append(change("ct", "cert_new", cert_label(after[key]), cert_detail(after[key])))
    for key in sorted(set(before) - set(after)):
        found.append(change("ct", "cert_removed", cert_label(before[key]), cert_detail(before[key])))
    start = parse_time(old_snap["generated_at"])
    end = parse_time(new_snap["generated_at"])
    for key in sorted(set(before) & set(after)):
        not_after = after[key][0]["not_after"]
        if not_after and start < parse_time(not_after) <= end:
            found.append(change("ct", "cert_expired", cert_label(after[key]), cert_detail(after[key])))
    return found


def compare_dns(old, new):
    found = []
    for name in sorted(set(new["domains"]) - set(old["domains"])):
        found.append(change("dns", "dns_domain_added", name, ", ".join(new["domains"][name]["sources"])))
    for name in sorted(set(new["domains"]) & set(old["domains"])):
        before, after = old["domains"][name], new["domains"][name]
        if "error" in (before["status"], after["status"]):
            continue
        if before["status"] != after["status"]:
            found.append(change("dns", "dns_status_changed", name, f"{before['status']} -> {after['status']}"))
            continue
        skipped = set(before["unanswered"]) | set(after["unanswered"])
        for rtype in sorted(set(before["records"]) | set(after["records"])):
            if rtype in skipped:
                continue
            old_values = before["records"].get(rtype, [])
            new_values = after["records"].get(rtype, [])
            if old_values == new_values:
                continue
            parts = [f"+{value}" for value in new_values if value not in old_values]
            parts += [f"-{value}" for value in old_values if value not in new_values]
            found.append(change("dns", "dns_record_changed", f"{name} {rtype}", " ".join(parts)))
    return found


def source_errors(new):
    found = []
    discovery = new["bgp"]["discovery"]
    if discovery["status"] != "ok":
        found.append(change("bgp", "source_error", "country-resource-list", f"{discovery['error']}; fallback ASN seed used"))
    for asn, record in sorted(new["bgp"]["asns"].items()):
        for endpoint, message in sorted(record["errors"].items()):
            found.append(change("bgp", "source_error", f"AS{asn} {endpoint}", message))
    for prefix, record in new["bgp"]["prefixes"].items():
        if record["status"] == "error":
            found.append(change("bgp", "source_error", f"routing-status {prefix}", record["error"]))
    for query, info in sorted(new["ct"]["queries"].items()):
        if info["status"] == "error":
            found.append(change("ct", "source_error", f"crt.sh {query}", info["error"]))
    failed = sorted(name for name, record in new["dns"]["domains"].items() if record["status"] == "error")
    if failed:
        found.append(change("dns", "source_error", f"{len(failed)} names", "DoH lookup failed for " + ", ".join(failed)))
    return found


def compare(old, new):
    found = compare_bgp(old["bgp"], new["bgp"])
    found += compare_ct(old, new)
    found += compare_dns(old["dns"], new["dns"])
    found += source_errors(new)
    order = {name: index for index, name in enumerate(SECTIONS)}
    return sorted(found, key=lambda item: (order[item["section"]], item["kind"] == "source_error", item["kind"], item["subject"]))
