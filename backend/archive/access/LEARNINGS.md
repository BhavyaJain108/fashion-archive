# Access learnings

What each round of testing taught us about getting products out of brands that the plain
pipeline could not reach. Research for a general shopping bot: nothing here is wired into
the production scraper.

**Scope:** brands on the roster that are not Shopify (including Shopify behind a custom
front end) and did not already work. As of 2026-09-17 that is Vivienne Westwood, Van Cleef
& Arpels, Gentle Monster and XSAI. Out of scope: STAUD, Psylos1, The Outnet, MARRKNULL,
Ragamalak, Sicko Kittens, LINISS (all Shopify).

## Where each brand stands

All four in scope now give up their catalogues (verified end to end 2026-09-17T17:49Z,
53 requests, 70 seconds, $0):

| Brand | Gets in with | Products found | Title / price / stock / images | Sizes |
|---|---|---|---|---|
| Vivienne Westwood | `cffi:chrome142` | 4,352 | 100% | 0% |
| Van Cleef & Arpels | `cffi:chrome142` | 1,333 | 100% | 0% |
| Gentle Monster | `playwright` (challenge-aware) | 1,332 | 100% | 0% |
| XSAI | `cffi:chrome142` | 103 | 100% | 0% |

Fill rates are measured on 5 sampled products per brand.

## Learnings

### 1. Use a browser's TLS handshake, not Python's — 2026-09-14
Plain Python HTTP sends Chrome's headers over Python's TLS, and the mismatch is visible
before any header is read. `curl_cffi` impersonating Chrome 142 fixed it.
- Vivienne Westwood: 403 → 200.
- Van Cleef & Arpels: timeout → 200.

### 2. A timeout can be a refusal — 2026-09-17
Van Cleef never answered plain HTTP; the connection just hung until 15s. That looks
exactly like a dead host, so the first sweep gave up on it. Treating a timeout as
"try the next handshake" opened it in 9 seconds.

### 3. The existing pipeline works unchanged once it can get in — 2026-09-17
Handing the curl_cffi transport to the existing `sitemap → JSON-LD` pipeline produced
full titles, prices, stock and images on both enterprise brands with no change to the
connectors. Access was the whole problem for them, not extraction.

### 4. Believe a sitemap that says it lists products — 2026-09-17
Vivienne Westwood keeps each product in its own folder
(`/women/<cat>/<subcat>/<slug>/<SKU>.html`), so the URL pattern learned from one sample
matched only that product's 6 colour variants. Its sitemap index names
`sitemap_0-product.xml`; using that directly gave 4,352 products.
Held on Van Cleef and XSAI unchanged. Code: `learned.trust_a_named_product_sitemap`.

### 5. A 200 homepage does not mean the site is open — 2026-09-17
Gentle Monster's homepage returns 200 (1 MB, served from cache), but `/sitemap.xml`
returns 202 with an AWS WAF JavaScript challenge (`gokuProps`, `challenge.js`). The first
sweep called it an "empty room" (reachable, nothing readable); it is really a challenge on
every path except the cached homepage.

### 6. Let the challenge script finish before asking again — 2026-09-17
Gentle Monster's AWS WAF challenge is solved by the page's own script, which sets
`aws-waf-token` about two seconds after load. The browser transport read each page and
closed the tab at once, killing the script mid-calculation, so no token ever appeared and
every request stayed at 202 — which is why the brand read as an "empty room" for three
rounds. Holding a tab open until the cookie appears turns every later request into a 200.
We wait for the site's own script; we never compute or forge the token.
Code: `access/browser.ChallengeAwareBrowser`. Also paces at 1.1s for their `Crawl-delay: 1`.

### 7. Products are the biggest family of URLs in a sitemap — 2026-09-17
Gentle Monster gives each product its own folder (`/us/en/item/<code>/<slug>`) and has one
sitemap per country, of which the probe happened to read Korea's. Reading the US sitemap
and taking the deepest folder holding at least half its URLs gives `/us/en/item/` — 1,332
of 1,395. Same rule found 1,333 products on Van Cleef, up from 200.
Code: `learned.widen_to_the_biggest_url_family`.

### 8. Prefer the priced Product over the ProductGroup — 2026-09-17
Gentle Monster publishes both a ProductGroup (the style: name, colours, no price) and the
Product on the page (price, stock, images). The extractor returned whichever came first,
so 3 of every 5 products had a title and nothing else. Preferring a node that carries
offers fixed it. This one is a genuine bug in the shared extractor, so unlike the others it
was fixed in `connectors/structured.py` rather than kept here.

## Open

- **Sizes are 0% on all four brands.** The JSON-LD on these sites carries no sizes and the
  DOM fallback finds none. On Gentle Monster the only size-like field is a frame
  measurement (`47-23-154.8`), not a wearable size. Not yet investigated on the others.
- **robots.txt disallows `/api/*` on Gentle Monster**, so their JSON API is off limits even
  though the page calls it. Everything above comes from product pages and sitemaps.
