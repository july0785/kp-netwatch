from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from .webclient import COLLECT_ERRORS, RETRY_STATUSES, describe
from .ripestat import rollup

URL = "https://crt.sh/?"
SUFFIXES = ("aca", "com", "edu", "gov", "law", "net", "org", "rep", "sca", "tra")
RETRY_ON = RETRY_STATUSES | {404}
TIMEOUT = 60
ATTEMPTS = 4
BACKOFF = 5.0


def query_string(suffix):
    return f"%.{suffix}.kp"


def suffix_of(name):
    labels = name.split(".")
    if len(labels) >= 3 and labels[-1] == "kp":
        return labels[-2]
    return None


def parse_rows(rows):
    certs = {}
    for row in rows:
        cert_id = int(row["id"])
        if cert_id in certs:
            continue
        names = {part.strip().lower() for part in (row.get("name_value") or "").split("\n") if part.strip()}
        if not names and row.get("common_name"):
            names = {row["common_name"].lower()}
        certs[cert_id] = {
            "id": cert_id,
            "names": sorted(names),
            "common_name": row.get("common_name"),
            "issuer": row.get("issuer_name"),
            "not_before": row.get("not_before"),
            "not_after": row.get("not_after"),
            "serial": row.get("serial_number"),
            "entry_timestamp": row.get("entry_timestamp"),
        }
    return certs


def query(client, suffix):
    url = URL + urlencode({"q": query_string(suffix), "output": "json"})
    try:
        rows = client.get_json(url, timeout=TIMEOUT, attempts=ATTEMPTS, backoff=BACKOFF, retry_statuses=RETRY_ON)
        if not isinstance(rows, list):
            raise ValueError("expected a JSON list")
        return {"status": "ok", "rows": len(rows)}, parse_rows(rows)
    except COLLECT_ERRORS as error:
        return {"status": "error", "error": describe(error)}, {}


def collect(client, suffixes=SUFFIXES, workers=2):
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda suffix: query(client, suffix), suffixes))
    queries = {query_string(suffix): info for suffix, (info, _) in zip(suffixes, results)}
    certs = {}
    for _, found in results:
        certs.update(found)
    return {
        "status": rollup(info["status"] for info in queries.values()),
        "queries": queries,
        "certs": [certs[cert_id] for cert_id in sorted(certs)],
    }
