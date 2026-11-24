# kp-netwatch

A daily, passive snapshot of North Korea's public internet footprint: BGP-announced prefixes for KP ASNs, Certificate Transparency entries for `.kp` names, and DNS records for `.kp` domains. Each run is diffed against the previous one and the differences go into `CHANGES.md`.

Almost nothing about this footprint changes often. According to [Wikipedia](https://en.wikipedia.org/wiki/Internet_in_North_Korea) it has been four /24 prefixes announced by AS131279, with traffic going out through China and, since 2017, also Russia. A prefix disappearing, a new certificate, or a nameserver moving is worth a look because the baseline is so quiet. These are indicators for further research, not conclusions.

<!-- status:start -->
| item | value |
| --- | --- |
| last run | 2026-11-24 13:39 UTC |
| ASNs | 1 |
| prefixes announced | 4 |
| certificates in CT | 47 (0 unexpired) |
| names tracked | 15 |
| names resolving | 8 |
| source status | bgp ok, ct ok, dns ok |
<!-- status:end -->

## Method

1. Resources are discovered from RIPEstat `country-resource-list` for `kp`, not hardcoded. If that call fails, AS131279 is used as a seed and the snapshot says `"fallback": true`.
2. For each ASN: `as-overview`, `announced-prefixes`, `routing-status`, `asn-neighbours`. For each announced prefix: `routing-status` (RIS peers seeing it, origin ASNs). A prefix counts as announced if its last timeline reaches the latest data point.
3. crt.sh is queried per second-level suffix (`%.org.kp`, `%.net.kp`, `%.com.kp`, `%.edu.kp`, `%.gov.kp`, `%.rep.kp`, `%.aca.kp`, `%.law.kp`, `%.sca.kp`, `%.tra.kp`). The plain `%.kp` query returned 404 or 502 every time I tried it. Results are deduplicated by certificate id; SANs, issuer, validity, serial and entry timestamp are kept.
4. DNS names are the `.kp` names found in CT, their parent domains, and a short seed list: `kp` and its nameservers, `kcna.kp`, `naenara.com.kp`, `rodong.rep.kp` (listed on the [.kp Wikipedia page](https://en.wikipedia.org/wiki/.kp)), plus a few names that appear in CT. A, AAAA, NS, MX and SOA are looked up over DNS-over-HTTPS.
5. The diff only compares what both snapshots could actually see. A failed source never turns into "everything withdrawn"; it shows up as a source error.

Visibility changes are reported when the share of RIS peers seeing a prefix moves by 5 points or more.

## Sources

| source | used for | notes |
| --- | --- | --- |
| [RIPEstat Data API](https://stat.ripe.net/docs/data_api) | resources, prefixes, visibility, neighbours | `sourceapp=kp-netwatch` on every call. No request limit, 8 concurrent per IP, register above 1,000 requests a day. [Terms](https://www.ripe.net/about-us/legal/ripestat-service-terms-and-conditions). |
| [crt.sh](https://crt.sh/) | CT log entries | Run by Sectigo. No published usage terms or rate limits that I could find. Slow and unreliable, hence retries with backoff and per-query error status. |
| [Cloudflare DoH JSON](https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/), [Google DoH JSON](https://developers.google.com/speed/public-dns/docs/doh/json) | DNS records | Cloudflare first, Google if it fails or answers SERVFAIL. No rate limits documented. |

The IANA record for `.kp` ([iana.org](https://www.iana.org/domains/root/db/kp.html)) lists `ns1.kptc.kp` and `ns2.kptc.kp` as nameservers and Star Joint Venture Company as sponsoring organisation.

## Passive only

The tool never sends HTTP, ICMP or port-scan traffic to KP hosts, and the HTTP client refuses any host other than `stat.ripe.net`, `crt.sh`, `cloudflare-dns.com` and `dns.google`, and any redirect. The one thing to know: when a public resolver answers a `.kp` query it may contact the `.kp` authoritative servers itself. I saw Google report timeouts against `175.45.176.x` addresses. That is ordinary recursive DNS performed by the resolver, not traffic from this tool, but it is the one place where a lookup you trigger can lead to a packet reaching a KP network.

Contact with North Korean systems can carry legal risk depending on where you live. This repository is built so that it never makes that contact itself. It is not legal advice.

## Run it

Python 3.12, standard library only.

```
python -m kpnetwatch run
python -m kpnetwatch report
python -m kpnetwatch diff data/snapshots/2026-11-18.json data/latest.json
python -m kpnetwatch run --offline-fixtures tests/fixtures
python -m unittest discover -s tests -v
```

`run` collects, compares with `data/latest.json`, writes `data/snapshots/YYYY-MM-DD.json` and `data/latest.json`, prepends a section to `CHANGES.md` and refreshes the table above. A crt.sh run can take several minutes when it is misbehaving.

`.github/workflows/watch.yml` does the same every day at 03:17 UTC (and on manual dispatch) and commits `data/`, `CHANGES.md` and `README.md` as `github-actions[bot]` only when something changed.

## Snapshot schema

Sorted keys, two-space indent, so git diffs stay readable.

- `generated_at`, `schema`, `tool`, `summary` (counts and per-source status)
- `bgp.discovery`: resources found, `fallback` flag. `bgp.asns.<asn>`: holder, announced, neighbours, visibility, per-endpoint `errors`. `bgp.prefixes.<prefix>`: origin ASNs, RIS peers seeing it.
- `ct.queries`: status per crt.sh query. `ct.certs`: id, names, issuer, not_before, not_after, serial, entry_timestamp.
- `dns.domains.<name>`: status (NOERROR, NXDOMAIN, SERVFAIL, error), `unanswered` record types, records, where the name came from.

Every section has a `status` of `ok`, `partial` or `error`.

## Limitations

- RIPEstat and crt.sh data lag the real world, and RIPEstat hides routes seen by fewer than 10 RIS peers.
- CT only contains certificates from publicly trusted CAs. Most `.kp` services will never appear there, and the `.kp` names that do appear are a small, mostly Let's Encrypt, sample.
- What DNS-over-HTTPS returns is one resolver's view, including cache. SERVFAIL on a name can be the resolver timing out against the KP nameservers rather than the name being gone, so record types that got no answer are left out of the comparison.
- A single certificate shows up as two crt.sh ids (precertificate and certificate); the change log groups them by serial.
- One ASN and four prefixes means the numbers are small. Treat any single day with caution.

## License

MIT, see `LICENSE`.

## 한국어 요약

북한(KP)의 공개 인터넷 흔적을 하루에 한 번 수동적으로 기록하는 도구입니다. RIPEstat에서 북한 ASN과 BGP 경로 정보를, crt.sh에서 `.kp` 도메인의 인증서 투명성 기록을, DNS-over-HTTPS로 `.kp` 도메인의 DNS 레코드를 가져와 JSON 스냅샷으로 저장하고, 전날과 달라진 점을 `CHANGES.md`에 남깁니다. GitHub Actions로 매일 자동 실행됩니다.

북한 호스트에는 HTTP, ICMP, 포트 스캔 등 어떤 트래픽도 직접 보내지 않으며, 제3자 공개 API와 공용 DNS 리졸버만 사용합니다. 다만 공용 리졸버가 `.kp` 질의를 처리하면서 북한 쪽 네임서버에 접속할 수는 있습니다. 변화는 결론이 아니라 추가 조사를 위한 단서이고, 데이터에는 지연과 누락이 있을 수 있습니다.
