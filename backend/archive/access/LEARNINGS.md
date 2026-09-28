# Access learnings

What each round of testing taught us about getting products out of brands that the plain
pipeline could not reach. The harness in this folder (`strategy`, `policy`, `bench`) is
the bench: it is reached only from the CLI and never from the daemon. What it *found* is
another matter — every rule below that earned its way in now lives in the real pipeline
(`fingerprint.py`, `connectors/sitemap.py`, `connectors/structured.py`, `escalate.py`),
and `access/learned.py`, where they were first proved, no longer exists.

## Adding a learning — the procedure

Since 2026-09-27 the loop in `learn/` does steps 1–7 on its own for the mechanical cases
and asks the model for the rest (README, "The learning loop"): a brand's dossier holds
what it found, the Learning page shows the walls, and `learn/learnings.jsonl` holds what
the model wrote down when a recipe landed. This section is still the procedure — the
loop follows it, and so does a person picking up a wall the loop could not open.

Anyone can do this. It needs no credentials and touches no live data: every command below
reads brands and writes nothing.

**1. Find a gap.** This prints every E0005 field against every brand you name:

```
python -m backend.archive.runner.cli coverage --shown
python -m backend.archive.runner.cli coverage www.example.com --sample 5
```

A row of zeros is either a field nobody publishes or a rule nobody has written. A column
of zeros is a brand we cannot read at all — `capability` tells you why.

**2. Open one real product page** on a brand with that gap and find the markup. Not a guess
about why the field is empty: the page. Most rules here took one page view to find.

**3. Write the narrowest rule that explains what you saw**, and put it where it belongs:

| What the rule is about | Where it goes |
|---|---|
| reading a page — a field's markup | `connectors/structured.py` |
| which URLs in a sitemap are products | `connectors/sitemap.py` |
| which sitemap to read at all | `fingerprint.py` (`_sharpen_discovery`) |
| getting in — a new transport or challenge | `transport.py`, `browser/`, and register it in `access/strategy.py` |
| anything you are not yet sure of | `access/` — prove it there first |

Never a branch on a brand name. "Any attribute whose name contains size" is a rule; "if
Vivienne Westwood, then" is a note about one shop.

**4. Verify on the brands that did not teach it.** Re-run `coverage` across several brands
and check nothing else moved. A rule that helps its own brand and quietly damages another
is worse than no rule. Add a unit test next to the code — they are hermetic, so no network:

```
venv/bin/python -m pytest tests/unit/archive -q
```

**5. Distrust the improvement.** Print the actual values, not just the fill rate. Two
counts in this file were wrong in our favour and both looked like wins first: 4,352
products were 544 locale copies, and 1,333 included the landing pages the samples were
measuring. A third read a financing widget as a product's colour.

**6. Write it down here** — a numbered section naming the brand, the date, the evidence and
the code. That is what lets a rule be deleted when a site changes, instead of surviving as
folklore nobody dares touch.

## The method

Every learning below was found the same way, and the loop matters more than any single
learning in it. Six steps:

1. **Measure everything, not the summary.** The capability matrix prints 5 columns and they
   all read 100%. E0005 has 42 fields and we filled 9. Sizes, categories and the two wrong
   catalogue counts were all invisible until the whole field set was measured at once.
   A number that only covers what already works cannot tell you what to do next.

2. **Pick the widest gap, and go and look at one real page.** Not a guess about why the
   field is empty — open the page a product actually lives on and find the markup. Sizes
   took one page view: `data-tau-size-id="XXS" title="XXS (not available)"`.

3. **Write the narrowest rule that explains what you saw.** "Any attribute whose name
   contains size, plus the neighbouring title for availability" — not "if Salesforce
   Commerce Cloud, then...". A rule aimed at one brand teaches nothing about the next.

4. **Verify on the brands that did not teach it.** The product-sitemap rule came from
   Vivienne Westwood and had to leave Van Cleef and XSAI unchanged. A rule that improves
   its own brand and quietly damages another is worse than no rule.

5. **Distrust improvements.** Every number that moved in our favour got checked, and two
   were wrong: 4,352 products were 544 country copies, and 1,333 included the landing
   pages that the samples had been measuring. Wins are where the errors hide, because
   nobody investigates good news.

6. **Write down where it came from.** Each learning below names the brand, the date and the
   evidence. That is what makes it reviewable later, and what lets a rule be deleted when a
   site changes rather than lingering as folklore.

Rules were first written in `access/learned.py`, applied on top of the pipeline rather than
inside it, so the production extractor kept its own behaviour until a rule had earned its
way in. All of them have now (2026-09-20), and that file is gone. Where each lives:

| Learning | Rule | Now in |
|---|---|---|
| 4 | `trust_a_named_product_sitemap` | `fingerprint.py` |
| 7 | `widen_to_the_biggest_url_family` | `fingerprint.py` |
| 10 | `dedupe_locale_copies` | `connectors/sitemap.py` |
| 11 | `drop_landing_pages` | `connectors/sitemap.py` |
| 9 | `sizes_from_swatches` | `connectors/structured.py` |
| 12 | `categories_from_breadcrumbs` | `connectors/structured.py` |
| 13 | `variant_from_sku`, `color_from_variant` | `connectors/structured.py` |
| 1, 2 | climb T0 → T1 → T2, a timeout is a refusal | `escalate.py` |
| 6, 14 | wait out the challenge, mint once | `browser/challenge.py` |

**Scope:** brands on the roster that are not Shopify (including Shopify behind a custom
front end) and did not already work. As of 2026-09-17 that is Vivienne Westwood, Van Cleef
& Arpels, Gentle Monster and XSAI. Out of scope: STAUD, Psylos1, The Outnet, MARRKNULL,
Ragamalak, Sicko Kittens, LINISS (all Shopify).

## Where each brand stands

All four in scope give up their catalogues. Counts corrected 2026-09-17 — see learnings
10 and 11; the earlier figures of 4,352 and 1,333 were both wrong.

| Brand | Gets in with | Products | Core fields | Sizes | Size avail. | Category levels |
|---|---|---|---|---|---|---|
| Vivienne Westwood | `cffi:chrome142` | 492 | 100% | 100% | 100% | 3 |
| Van Cleef & Arpels | `cffi:chrome142` | 1,299 | 100% | 0% (jewellery) | — | 2 |
| Gentle Monster | `playwright` (challenge-aware) | 1,332 | 100% | 0% (eyewear) | — | 1 |
| XSAI | `cffi:chrome142` | 103 | 100% | 100% | 0% | 0 (has none) |

Core fields = title, price, in_stock, main_image_url, all_images, description.
Fill measured on 5 sampled products per brand.

## How much of E0005 we actually get

E0005 has 42 fields. We fill 9-13 of them. Measured 2026-09-17:

Everywhere: itemurl, product_title, description, price, in_stock, main_image_url, all_images,
category1 (except XSAI, which publishes no category level).
Mostly: product_code (3 of 4), brand (3 of 4), additional_code_1 + type (2 of 4).
Gentle Monster only: specifications, color_info, material_info, category1.
Vivienne Westwood + XSAI only: size_info. Vivienne Westwood only: size_availability.
Categories: 3 levels on Vivienne Westwood, 2 on Van Cleef, 1 on Gentle Monster.

Vivienne Westwood also: color_info (~51% of its catalogue) and variant_info (~59%).

Empty on all four: additional_code_2/3 (+types), size_stock_counts,
full_price, promotion_type, promotion_end_date, ppu, unit_type, package_desc, quantity,
category4-10, additional_tags, delivery, additional_content.

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

### 9. Sizes live in swatch attributes, under any name — 2026-09-17
Why sizes were 0% everywhere: the shared DOM fallback looks only for `data-size` and
`data-option-value`. Vivienne Westwood runs Salesforce Commerce Cloud and writes
`data-tau-size-id="XXS" title="XXS (not available)"`, so every size on the site was
invisible — and with it the per-size stock, which is the point of re-scraping fashion.
Matching any attribute whose name contains "size", and reading the neighbouring
title/aria-label for availability, gives Vivienne Westwood 100% sizes with 100%
availability and XSAI 100% sizes. Code: `learned.sizes_from_swatches`.

Van Cleef (necklaces) and Gentle Monster (eyewear) are still 0%, and that looks correct
rather than missing: neither publishes a wearable size. Gentle Monster's only size-like
value is a frame measurement, `47-23-154.8`. Worth re-checking on a Van Cleef ring.

### 10. One product, not one per country — 2026-09-17
Vivienne Westwood's product sitemap lists each product once per locale (/en-fr/, /en-de/,
…). 4,352 URLs are 544 products. An inflated count is worse than a wrong one: it reads as
success. Code: `learned.dedupe_locale_copies`.

### 11. A landing page is not a product, and it is first in the sitemap — 2026-09-17
Van Cleef's product family /us/en/collections/ also holds its collection landing pages.
Those pages carry several Product blocks of their own, so the extractor read one and
produced a product called "Jewelry collections" priced at whatever was featured. They sort
first, so they were exactly the 5 that every sample measured — the earlier "100% on Van
Cleef" was measured on category pages.

Products in a family sit at one depth; 1,299 of its 1,333 URLs are at depth 8-10 and the 34
landings at 6-7. Keeping everything at or deeper than the most common depth drops them, at
no request cost, and changes nothing for brands whose products share one depth.
Code: `learned.drop_landing_pages`.

### 12. Categories are the breadcrumbs, minus the root and the product — 2026-09-17
All four brands publish `BreadcrumbList` JSON-LD and none of it was being read. The shape
is the same everywhere: first crumb is the site root, last is the product itself, and what
remains is the category path.

    Home → Women → Clothing → Skirts → Scribble Check Skirt        → 3 levels
    Homepage → Jewelry → Alhambra - Jewelry → Magic Alhambra…      → 2 levels
    Home → Glasses → Jennie - Zen C1                               → 1 level
    XSAI → WIDE PANTS                                              → 0, correctly

The last crumb is often truncated, so it is matched loosely against the product title
rather than exactly. XSAI yields nothing and that is the right answer — it has no category
level, and a rule that invented one would be worse than the blank. Values spot-checked:
Women/Clothing/Skirts, Women/Clothing/Knitwear, Jewelry/Alhambra - Jewelry.
Only blank fields are filled, so a channel that names a category still wins.
Code: `learned.categories_from_breadcrumbs`.

### 11b. …and a limit must not stop the walk inside a file — 2026-09-20
Learning 11 was verified without a limit; production runs with one. `--max-products 4`
stopped the walk after four URLs, which on Van Cleef are its four collection landing
pages, so the depth filter had no distribution to judge and four category pages were
stored as products, `itemurl` and all. The limit now stops the walk between files, never
inside one: the file is already downloaded, so reading the rest of it is free.

The lesson generalises past the bug — **verify in the configuration that ships**, not the
one that is convenient to test.

### 13. A variant SKU names the variant, which is usually but not always a colour — 2026-09-20
Vivienne Westwood publishes no `color` in its JSON-LD and the page's only colour markup is
a swatch id. The SKU carries it: `1802002B-C00A1--RED`. Of 4,336 URLs, 2,560 name a
variant (59%), and 2,232 of those (87%) are colours.

The other 13% are why this fills `variant_info` first and reaches `color_info` only when a
word in it is a colour. The Worlds End Swing Dress is `--SEX`, after the shop; others are
prints (`PRIMAVERA CHERUBS`) or materials (`BLACK PU GRAIN`). Recording those as colours
would be confidently wrong in a field shoppers filter on.

The rule deliberately does *not* read `data-*color*` attributes — the shape that worked for
sizes. Van Cleef's pages carry `data-affirm-color="black"` on a financing widget, so that
rule would have called a gold necklace black, and scored as a win on the fill map doing it.
Code: `structured.variant_from_sku`, `structured.color_from_variant`.

### 14. A challenge is solved once, not once a page — 2026-09-21
Gentle Monster's challenge produces a cookie, and the site then answers ordinary HTTP that
carries it. The first version drove all 1,332 product pages through the browser because
that is what had solved the challenge, which is paying a browser's price for a cookie's
problem: 3s a page instead of 0.3s, and 477 MB resident for the length of the run instead
of 2.5 seconds.

So the browser mints and is put away, and everything after it goes over plain HTTP with the
token attached, re-minting when it expires. Measured: 18 requests in 34 seconds, same 1,332
products, same 100% on titles, prices, stock and images.

Worth generalising: when a defence produces a credential, the expensive tool is needed to
*obtain* it, not to *use* it. Ask what the site actually checks on each request.
Code: `browser/challenge.ChallengeAwareBrowser`, `render=True` to keep every request in the
browser for a site whose products only exist after its JavaScript runs.

### 15. robots.txt names one country's sitemap; ask for ours — 2026-09-27
Marni's robots.txt points at `/en-ca/sitemap_index.xml`. The same index exists at
`/en-us/`, with the same products at the prices the archive holds. The probe now tries the
US locale's copy of any sitemap URL that carries another country's locale segment, one
request, and keeps what robots named when there is none.
Code: `fingerprint._market_sitemap`.

### 16. Of two unnamed sitemaps, the bigger one is the products — 2026-09-27
Marni's index has two children under `/en-us/`: `sitemap_0.xml` (72 URLs: looks, the
collaborations, an awards page) and `sitemap-en-us.xml` (1,838 products). Neither name
says "product", the locale rule matched both, and the first was read. Every look page
carries a Product JSON-LD with no price and no image, so 69 "products" were found and every
fetch was "no product data". Now two or three children with nothing to tell them apart by
name are all read and the biggest is used — learning 7 applied between sitemaps instead of
within one — and a child of nothing but the family is adopted even when the prefix stands.
Measured: 917 products, 100% on title, price, stock and images.
Code: `fingerprint._one_sitemap`, `_widen_to_the_biggest_url_family`.

### 17. One entry, forty countries: read the market's alternate — 2026-09-27
Acne Studios' five sitemaps hold 500 entries each. Each entry is one page with its
hreflang alternates inline — forty `<xhtml:link>`s — and a canonical `<loc>` in whichever
country the generator chose: of 500, 7 are US locs and 275 carry a US alternate. Reading
locs alone found 7 products; the parent-path clustering then saw every product in a folder
of its own (`/us/en/<slug>/<CODE>.html`) and the biggest clusters were the category pages.

Three rules, each narrow: an entry's URL is its `en-us` alternate where it lists one, else
its loc (the same fact as learning 10, stated the other way round); when a sitemap mixes
locales as separate entries, only our country's are kept before any counting; and the
family folder (the deepest holding half the URLs) is a cluster worth sampling, from its
middle (learning 11: the landing page is first). The index stays the sitemap to read when
its many children have no telling name — adopting `sitemap_1.xml` would have dropped four
fifths of the catalogue. Measured: 598 products, 100% on every core field and sizes, over
plain HTTP.
Code: `connectors/sitemap.market_link`, `fingerprint._entries`, `_one_market`,
`_biggest_family`, `_probe_ldjson`.

### 18. A Gatsby site keeps its pages as JSON beside the pages — 2026-09-27
LUAR sells through EQL's launch platform (luar.runfair.com). No sitemap (the URL answers
with the app's HTML), no JSON-LD, no feed — and `/page-data/index/page-data.json`, which
Gatsby writes for every page, lists the retailer's draws with a country and a slug, and
`/page-data/us/<slug>/page-data.json` is the whole product: name, price, currency,
description, photographs, SKU, and the window it sells in. A draw outside its window is
out of stock whatever the page says. New lane: `page_data × platform_json`.
Code: `connectors/runfair.py`, `fingerprint.probe` (`___gatsby` in the homepage).

### 19. Shopify with the feed switched off still answers one product at a time — 2026-09-27
fengofficiel.com — a Haravan store, Shopify's shape to the last field — serves 404 at
`/products.json` and the whole product record at `/products/<handle>.json`. Only a
Shopify-shaped index names its product sitemap `sitemap_products_N.xml`, so the probe
asks for one product's JSON there and nowhere else. The per-product endpoint writes `tags`
as one string or null, and takes no market, so the prices are the shop's own; `/meta.json`
stays open and names the currency (VND). 8 of its 43 handles are placeholders — every
variant at 0, unavailable, no photograph — and are not products. New lane:
`sitemap × platform_json`, which outranks reading the pages.
Code: `fingerprint._probe_product_json`, `connectors/shopify.ShopifyPageConnector`.

### 20. Our own second probe is the 429 — 2026-09-27
Maketh Thou, Cooperative, Oh Polly, JW PEI and Bronze Snake all produced products on a
first capability run and "no-answer" on a second run minutes later, from the same
address. The bench already knew this (a brand held by our worker is not a clean reading);
it is as true of two probes by hand. Re-probe with a gap before calling a brand blocked.

### 21. A block on the address is not a block on the handshake — 2026-09-27
yeezy.com answers every rung with Cloudflare's "Sorry, you have been blocked" — a WAF
*block*, not a challenge: no script to run, no cookie to mint, `cf-ray` and a 403 from the
edge. Every transport we own leaves from the same datacenter address, so every rung was
the same question asked of a rule about the address. The classifier already said so
(`waf_403` at `httpx`, `cffi:chrome142`, `cffi:safari184` alike); the ladder had nothing
above T1 that changed the thing being judged.

Rung added: T1P, the T1 handshake through an egress proxy the owner configures
(`ARCHIVE_PROXY_URL`; `ARCHIVE_PROXY_URL_<CC>` for a country's own exit). It is tier 2 on
the shelf because each request is paid for, it exists only when the variable is set, and
the prober climbs to it only after T1 has been refused. Not yet measured against yeezy.com:
there is no proxy to measure with. `cli access yeezy.com` says the moment there is.
Code: `transport.CurlCffiTransport(proxy=)`, `transport.for_level`, `escalate.cheap_levels`,
`access/strategy` (`cffi:chrome142@proxy`).

604service.com and 604service-en.com serve a static "접근 제한" (access restricted) page
from S3 through CloudFront, to every rung. First read as a rule about the country; the
owner's home connection gets in (2026-09-28), so it is a rule about the kind of address —
cloud ranges refused, residential ones served. A residential exit (ARCHIVE_PROXY_URL,
not a KR one) is the test, and until one exists the brand stays on the roster, unread.

### Not a shop
bellaspantzel.com is a Cargo portfolio (`hasShopModel: false`, pages `/` and `/about`,
credits for Rick Owens, Robert Wun, Heliot Emil). There is nothing to sell and nothing to
read; it is kept on the roster withheld from the page.

## Open

Next, in the order they look worth doing:

1. **full_price / promotions** — empty everywhere, but these exist only on discounted
   products and nothing sampled was on sale. Needs a sale item to test against, not a fix.
2. **material_info / specifications** — filled on Gentle Monster from its JSON-LD. Vivienne
   Westwood states fabric in prose inside the description, which needs parsing rather than
   reading, so the value is lower and the risk of inventing data higher.
3. **variant_info beyond a SKU suffix** — Gentle Monster lists its colour variants in
   `hasVariant` and nothing reads them into the field.
4. **size_stock_counts** — none of the four publish per-size counts, only in or out of
   stock. Probably genuinely unavailable rather than missed.
5. **Categories on XSAI** — it publishes no category level at all. Its collection pages
   might supply one, but that is discovery work rather than page reading.

- **robots.txt disallows `/api/*` on Gentle Monster**, so its JSON API is off limits even
  though the page calls it. Everything here comes from product pages and sitemaps.
- **T1P has not been measured.** yeezy.com is the brand to measure it on, 604SERVICE
  the one that wants a Korean exit; both wait on an egress proxy being configured.
- **A browser through the proxy (T2P)** does not exist yet: a site that blocks the address
  *and* runs a challenge would need it. None on the roster does today.
- **The browser lane is not in the scraper image.** Gentle Monster needs `--browser`, which
  playwright provides locally and the deployed worker does not have. Turning it on means a
  larger image and roughly 1.3 GB of egress per full pass at ~1 MB a page.

### 22. A headless site's catalogue lives on its platform's host, not its own — 2026-09-27
yeezy.com is a Svelte app on Swell (swell.is): every image URL names the store
(`cdn.swell.store/yzy-prod/…`) and the page embeds the store's publishable key
(`pk_…`) beside its Google Pay config — the same key the site's own JavaScript sends to
`yzy-prod.swell.store/api/products`. That host is under no Cloudflare rule about our
address: it answers plain httpx with the whole catalogue (35 products, price, sale price,
SKU, stock, options, photographs), paginated, with the key as HTTP basic auth
(`store:key`). The rung that "needed a proxy" (entry 21) needed no proxy at all; the
brand host was never where the products were.

Rule, keyed on the shape: a page naming `cdn.swell.store/<store>/` and carrying a
`pk_` key is a Swell storefront; the probe confirms it with one API request and the
planner takes `swell_api` before anything else, whatever the brand host says. A
challenge on the brand host is not a wall for this lane (`challenged` is cleared when
the API answers). Verified: the model's own analysis of yeezy.com found the same tell
and proposed the API path, guessing `/api/products/{id}` on the brand host (404); the
lane in code is the version that reads.
