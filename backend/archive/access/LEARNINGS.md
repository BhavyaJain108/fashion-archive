# Access learnings

What each round of testing taught us about getting products out of brands that the plain
pipeline could not reach. Research for a general shopping bot: nothing here is wired into
the production scraper.

**Scope:** brands on the roster that are not Shopify (including Shopify behind a custom
front end) and did not already work. As of 2026-09-17 that is Vivienne Westwood, Van Cleef
& Arpels, Gentle Monster and XSAI. Out of scope: STAUD, Psylos1, The Outnet, MARRKNULL,
Ragamalak, Sicko Kittens, LINISS (all Shopify).

## Where each brand stands

| Brand | Gets in with | Products found | Title / price / stock / images | Sizes |
|---|---|---|---|---|
| Vivienne Westwood | `cffi:chrome142` | 4,352 | 100% | 0% |
| Van Cleef & Arpels | `cffi:chrome142` | 200 | 100% | 0% |
| XSAI | `httpx` (plain) | 103 | 100% | 0% |
| Gentle Monster | not yet | — | — | — |

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

## Open

- **Gentle Monster**: AWS WAF JS challenge. Next: a real browser, which runs the challenge
  as any visitor's browser does. No forging of challenge tokens.
- **Sizes are 0% on all three brands we got into.** JSON-LD on these sites carries no sizes
  and the DOM fallback finds none.
