# Access learnings

What each round of testing taught us about getting products out of brands that the plain
pipeline could not reach. Research for a general shopping bot: nothing here is wired into
the production scraper.

## The method

Every learning below was found the same way, and the loop matters more than any single
learning in it. Six steps:

1. **Measure everything, not the summary.** The capability matrix prints 5 columns and they
   all read 100%. E0005 has 45 fields and we filled 9. Sizes, categories and the two wrong
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

Rules live in `access/learned.py`, applied on top of the pipeline rather than inside it, so
the production extractor keeps its own behaviour until a rule has earned its way in. Only
one has so far: learning 8, which was a plain bug.

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

E0005 has 45 fields. We fill 9-13 of them. Measured 2026-09-17:

Everywhere: itemurl, product_title, description, price, in_stock, main_image_url, all_images,
category1 (except XSAI, which publishes no category level).
Mostly: product_code (3 of 4), brand (3 of 4), additional_code_1 + type (2 of 4).
Gentle Monster only: specifications, color_info, material_info, category1.
Vivienne Westwood + XSAI only: size_info. Vivienne Westwood only: size_availability.
Categories: 3 levels on Vivienne Westwood, 2 on Van Cleef, 1 on Gentle Monster.

Empty on all four: additional_code_2/3 (+types), size_stock_counts, variant_info,
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

## Open

Next, in the order they look worth doing:

1. **color_info** — filled only on Gentle Monster. Vivienne Westwood carries colour in the
   SKU and the URL (`--RED`), and has colour swatches beside the size swatches.
3. **full_price / promotion fields** — empty everywhere, but these only exist on discounted
   products and nothing sampled was on sale. Needs a sale item to test against, not a fix.
4. **size_stock_counts** — none of the four publish per-size counts; only in/out. Probably
   genuinely unavailable rather than missed.
5. **variant_info** — the colour variants are on the page (Gentle Monster lists them in
   `hasVariant`); nothing reads them into the field yet.

- **robots.txt disallows `/api/*` on Gentle Monster**, so their JSON API is off limits even
  though the page calls it. Everything above comes from product pages and sitemaps.
