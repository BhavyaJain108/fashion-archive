# Access harness: measuring what it costs to get in

**Date:** 2026-09-13
**Status:** approved, ready to implement

## The problem

Ten of the 37 brands on the roster cannot be scraped. `brands.yml` records the symptoms:

| Symptom | Brands |
|---|---|
| `429 to plain http` | LINISS, STAUD, Sicko Kittens, By Ellen With Love |
| `shopify json challenged` | MARRKNULL, Ragamalak |
| `enterprise 403` / `TLS-level block` / `enterprise challenge` | Vivienne Westwood, Van Cleef & Arpels, Gentle Monster, The Outnet |
| `custom nextjs` | Psylos1, XSAI |

Four password-gated brands (BU-BULLY, COLTMCR, Eight, Skid Row Studio) are out of scope: no
transport opens a password.

### Why the first three rows fail

`HttpxTransport` sends `BROWSER_HEADERS` claiming Chrome 126 over Python's TLS stack, on
HTTP/1.1. A WAF hashes the TLS ClientHello (JA3/JA4) and the HTTP/2 SETTINGS frame before
reading a single header, so it sees a Chrome claim delivered with a Python fingerprint on
the wrong protocol version. The contradiction is a stronger bot signal than an honest
`python-httpx` User-Agent would be.

The 429s are the same verdict, not rate limiting. Shopify's edge answers 429/430 to
non-browser fingerprints regardless of request rate — which is why `HostBudget` slowing
down has never opened them.

### Why the fourth row is not the same problem

Psylos1 and XSAI return 200. They are reachable. They render products client-side, so the
served HTML carries no JSON-LD and there is no platform API to read. **A better transport
cannot help**; only rendering the page or finding its data endpoint can.

Conflating these two situations is the expensive mistake: it leads to buying a residential
proxy to solve a rendering problem.

## What we are building

An **access layer** — a named, swappable way of getting bytes from a host, plus a dated
record of which way works for which brand and what it costs.

Explicitly **not** in scope: the connectors, extraction, the catalog, the planner. The
`Transport` protocol in `backend/archive/transport.py` is already the seam. Everything above
it is untouched.

### The two rules the design rests on

1. **A locked door and an empty room are different failures.** One needs a better key; the
   other needs a renderer. The classifier must distinguish them and the escalation policy
   must branch on them.
2. **Try the cheapest strategy first, and stop when one works.** At the refresh rate the
   product needs (fresh stock ⇒ tens of thousands of requests a day), a 3-second browser
   tier does not fit inside a day. Cost is not a footnote; it is the selection criterion.

## Architecture

```
backend/archive/access/
  outcome.py    Outcome enum + classify()          pure
  policy.py     next_tier() escalation rules       pure
  strategy.py   registry: name -> Strategy         lazy imports
  cffi.py       CurlCffiTransport                  optional dep
  probe.py      try_access(): one matrix cell
  bench.py      sweep(): brands x strategies
  store.py      time-series persistence
```

Two edits outside the package:

- `transport.py` — extract the ledger/budget/`_retry_after` bookkeeping into a
  `LedgeredTransport` base so `CurlCffiTransport` does not copy it.
- `browser/transport.py` — a `driver` parameter selecting `playwright` or `patchright`.

### `outcome.py` — the classifier

```python
class Outcome(StrEnum):
    OK           # reached, and an extractable signal exists
    OK_THIN      # reached, 200, no product signal at all
    TLS_BLOCKED  # handshake refused
    WAF_403
    RATE_429
    CHALLENGE
    GATED
    UNREACHABLE
```

`classify(cap, exc, statuses) -> Outcome`, a pure function over the `Capability` that
`fingerprint.probe` already returns, the exception it raised (if any), and the transport
ledger's statuses. Precedence, highest first:

1. `exc` is an SSL/TLS error → `TLS_BLOCKED`
2. `exc` is connect/DNS/timeout → `UNREACHABLE`
3. `cap.password_gated` → `GATED`
4. any status 429 → `RATE_429`
5. any status 401/403 → `WAF_403`
6. `cap.challenged` → `CHALLENGE`
7. no `bulk_json`, no `woo_api`, no `ldjson_product`, no `sitemap_url` → `OK_THIN`
8. otherwise → `OK`

429 and 403 are checked before `cap.challenged` because `probe()` sets `challenged` for
*any* of 401/403/429; the raw status is the more specific fact and the one that tells us
which fix to reach for.

### `policy.py` — escalation

`next_strategies(outcome, remaining) -> list[Strategy]`, pure:

| Outcome | Next |
|---|---|
| `OK` | `[]` — stop, do not pay for a dearer tier |
| `RATE_429`, `WAF_403`, `TLS_BLOCKED`, `CHALLENGE` | all remaining, cheapest first |
| `OK_THIN` | remaining `kind == "browser"` only — a better fingerprint cannot render JS |
| `GATED` | `[]` |
| `UNREACHABLE` | `[]` after one retry of the same strategy |

### `strategy.py` — the registry

```python
@dataclass(frozen=True)
class Strategy:
    name: str                       # "cffi:chrome124"
    tier: int                       # sort key, cheapest first
    usd_per_1k: float
    kind: Literal["http", "browser"]
    level: TransportLevel           # what fingerprint.probe gates deep probes on
    build: Callable[[], Transport]
```

v1 registers, in tier order:

| name | tier | kind | usd/1k | notes |
|---|---|---|---|---|
| `httpx` | 0 | http | 0.00 | today's transport, the control |
| `cffi:chrome124` | 1 | http | 0.00 | curl_cffi Chrome impersonation |
| `cffi:chrome131` | 1 | http | 0.00 | brands fingerprint specific versions |
| `cffi:safari17` | 1 | http | 0.00 | |
| `playwright` | 3 | browser | 0.00 | existing `PlaywrightTransport` |
| `patchright` | 4 | browser | 0.00 | CDP-level patches |

Tier is separate from dollars because at free tiers the cost is **seconds and fragility**,
not money. `usd_per_1k` exists so paid adapters slot in later without a schema change.

Every import is lazy. A missing `curl_cffi` makes that strategy report `available=False`; it
must never raise at import time or break the CLI.

`build(name) -> Transport` also replaces the 8 hardcoded construction sites over time. That
is not required for v1 and is not part of this change.

**Patchright must not receive `STEALTH_JS`.** Patchright patches at the CDP layer; injecting
the hand-rolled `Object.defineProperty` patches on top re-adds exactly the detectable traces
it removes. The `driver` parameter therefore selects the init-script behaviour too, which is
what makes `playwright` and `patchright` genuinely different cells worth measuring.

### `probe.py` — one cell

```python
@dataclass
class AccessResult:
    domain: str
    strategy: str
    outcome: Outcome
    seconds: float
    requests: int
    statuses: list[int]
    usd: float
    daemon_active: bool | None # None = unknown; see "Contention" below
    note: str
    capability: Capability | None
```

`try_access(domain, strategy, budget=None) -> AccessResult` builds a **fresh** transport per
cell (a warmed browser context holding challenge cookies would contaminate the next
strategy's reading), runs `fingerprint.probe`, times it, classifies, and tears down.

### `bench.py` — the sweep

`sweep(domains, strategies, ...) -> list[AccessResult]`. Per domain: sort strategies by tier,
run the cheapest, consult `policy.next_strategies` with the outcome, repeat.

Cost of a full sweep with early exit: ~37 cheap probes + ~10 brands climbing ~4 tiers ≈ 75
probes × ~4 GETs ≈ **300 requests**, throttled by the existing `HostBudget`. The full cross
product would be 37 × 6 × 4 = 888.

### `store.py` — the dated notebook

Reuses the existing `ObjectStore`, so `--objects <dir>` gives a local run with no R2:

- `access/sweeps/<iso-timestamp>.json` — every result from that sweep, append-only. **This is
  the time series.** Whatever works today will stop working; storing only the current answer
  means a brand goes quietly dark until a customer notices.
- `access/current.json` — `{domain: {strategy, outcome, seconds, usd, first_seen,
  last_verified}}`. The rolled-up winner per brand.

`current.json` is the single file a planner would later read to auto-select a transport. That
wiring is **not** part of this change.

### Contention with the live daemon

The scraper now runs continuously as a Render worker, hitting the same hosts. A 429 measured
while that daemon is working may be our own worker rather than a fingerprint verdict.

Sharing a `HostBudget` is not possible — the daemon is a separate process on another host — so
the honest option is to record the caveat rather than pretend it away.

The scheduler already stamps `claimed_by` and `claimed_at` on a brand's fleet row while a
worker holds it (`scheduler.py:154`), so this is answerable **per domain** rather than as a
global guess: `daemon_active` is true when the domain's fleet row carries a non-stale claim at
the moment the cell runs. The CLI prints a warning next to any `RATE_429` or `WAF_403`
recorded with `daemon_active=True`, because those are the two outcomes our own traffic can
manufacture. When no object store is configured the field is `None`, meaning "not known" — it
is never silently reported as `False`.

### CLI

```
python -m backend.archive.runner.cli access [options]
  --domain X          one brand
  --only-failing      brands whose brands.yml notes record a failure
  --strategies a,b,c  restrict the ladder
  --objects DIR       local object store
  --dry-run           print the request plan, send nothing
  --gap SECONDS       per-host pacing (default 0.5, via HostBudget)
```

Output is the matrix: one row per brand, one column per strategy attempted, plus the winner
and its cost.

## Testing

All unit, no network, following the existing `httpx.MockTransport` route-fake pattern in
`tests/unit/archive/test_fingerprint.py`.

| File | Covers |
|---|---|
| `test_access_outcome.py` | `classify()` — table-driven over every precedence branch |
| `test_access_policy.py` | `next_strategies()` — table-driven, especially the `OK_THIN` → browser-only jump and `OK` → stop |
| `test_access_strategy.py` | every name builds; a monkeypatched-missing module yields `available=False` rather than an exception |
| `test_access_bench.py` | scripted fake transports: early exit on `OK`, browser jump on `OK_THIN`, `GATED` stops immediately |
| `test_access_store.py` | round-trip against the local `ObjectStore` the existing tests use |

Live probing happens only when the CLI is run, deliberately and by hand.

## Dependencies

`curl_cffi>=0.7` goes into `requirements-scraper.txt`. It is a ~5 MB wheel with no browser,
which is the point: that file's header notes playwright was excluded because a browser lane
means a second, larger image. curl_cffi gets browser-grade *access* without a browser, so it
belongs in the small image.

`patchright` is dev-only — it pulls a Chromium. It goes in `requirements-dev.txt` and its
strategy reports `available=False` in production.

## What this does not promise

- The six fingerprint/rate brands: rung 2 is likely to open them. Free if so.
- Gentle Monster, The Outnet, Van Cleef, Vivienne Westwood: serious commercial defences. These
  may simply cost money. The harness makes that a measured decision, not an argument.
- Psylos1 and XSAI: not an access problem. The harness's job here is to *say so* — to return
  `OK_THIN` — not to fix it.
