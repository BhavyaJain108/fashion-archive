# Bag and Buy — handover for the frontend

Written 2026-09-24 against branch `worktree-agent-a3c1821d563b019f0` (not merged, not pushed).
Backend only. Nothing under `web_ui/` was touched.

## What this is, in one paragraph

A signed-in person puts products from any of the shown brands into one bag. The bag is
rows in Postgres (`bag_lines`), one per (product, variant). Every read re-checks each line
against the storefront index and says whether the price changed or the variant went out of
stock. "Buy" does not take money: `GET /api/bag/checkout` returns, per shop, the shop's own
cart URL with the person's lines already in it. They pay on the shop's checkout, once per
shop, in the shop's currency. We never see a card number, an address, or an order.

## What changed on the product data

`ProductRecord` gained three fields outside E0005. They arrive on a brand's **next scrape**;
nothing was migrated, so until a brand re-runs its products carry none of them.

| field | type | Shopify | WooCommerce | sitemap+page lane |
|---|---|---|---|---|
| `offers` | `[{size, variant_id, available, price}]` | one per `variants[]`; `variant_id` = `variants[].id`; size from the option named "Size" (any position) | one per `variations[]` on a variable product, else one with the product `id`; `available` is the product's stock (the Store API list has none per variation); `price` is `null` when the product quotes a range | absent |
| `platform` | `"shopify"` / `"woo"` / `null` | `"shopify"` | `"woo"` | `null` |
| `handle` | string / `null` | `handle` | `slug` | `null` |

On the storefront tile (`/api/archive/storefront`, `/api/archive/product`):

- every `sizes[]` entry gains `variant_id` when an offer names that size. A size sold under
  several colours has several offers; the tile's `sizes[]` carries the first one **in stock**
  (else the first at all).
- `platform` is on every tile.
- `offers` is on the product-page tile only (`/api/archive/product` → `tile.offers`), not on
  grid tiles — a product with 30 variants would be 30 objects per grid cell.

Example tile fragment:

```json
{
  "url": "https://kuurth.com/products/nemo-hoodie",
  "handle": "nemo-hoodie",
  "platform": "shopify",
  "price": 126.0,
  "currency": "USD",
  "sizes": [
    {"size": "M", "available": true, "variant_id": "41000000001"},
    {"size": "L", "available": false, "variant_id": "41000000002"}
  ],
  "offers": [
    {"size": "M", "variant_id": "41000000001", "available": true, "price": 126.0},
    {"size": "L", "variant_id": "41000000002", "available": false, "price": 126.0}
  ]
}
```

## Endpoints

All six require a session (the same cookie as `/api/favourites`). All answer JSON. Every
mutation answers with the **whole bag** in the same shape as `GET /api/bag`, so the drawer
re-renders from one response and never has to merge.

### `GET /api/bag`

```json
{
  "shops": [
    {
      "brand": "kuurth.com",
      "brand_name": "Kuurth",
      "platform": "shopify",
      "currency": "USD",
      "lines": [
        {
          "id": 17,
          "brand": "kuurth.com",
          "brand_name": "Kuurth",
          "itemurl": "https://kuurth.com/products/nemo-hoodie",
          "handle": "nemo-hoodie",
          "title": "Nemo Hoodie",
          "image": "https://cdn.shopify.com/s/files/nemo-1.jpg",
          "platform": "shopify",
          "variant_id": "41000000001",
          "size": "M",
          "qty": 2,
          "price": 126.0,
          "currency": "USD",
          "added_at": "2026-09-24T10:12:03.100000+00:00",
          "updated_at": "2026-09-24T10:12:03.100000+00:00",
          "checked": true,
          "current_price": 126.0,
          "available": true,
          "changed": false,
          "unavailable": false
        }
      ],
      "quote": {
        "brand": "kuurth.com",
        "currency": "USD",
        "subtotal": 252.0,
        "lines_priced": 1,
        "lines_unpriced": 0,
        "lines_unavailable": 0,
        "excludes": ["shipping", "tax", "duties"]
      }
    }
  ],
  "line_count": 1,
  "item_count": 2,
  "checked": true,
  "max_lines": 50,
  "max_qty": 20
}
```

Per line:

- `price` / `currency` — what the catalogue said when the line was added. Fixed.
- `current_price` — what the catalogue says now (from the offer with this `variant_id`, else
  the product price). `null` if the variant is gone or the product is no longer shown.
- `changed` — `current_price` differs from `price` by ≥ 0.005.
- `unavailable` — the variant is out of stock, or no longer in the shop's feed.
- `checked` — `false` when the catalogue could not be asked: the storefront index is still
  building (first ~90 s after an API deploy; then the top-level `checked` is also `false`),
  or this product has left the shop front (brand gated, product delisted, photograph gone).
  An unchecked line shows its stored price and no availability.

`quote.subtotal` is `Σ price × qty` over the lines that have a price, in the **shop's**
currency. The price used is `current_price` when checked, else the stored `price`. It
excludes shipping, tax and duties — those are decided on the shop's checkout from an address
we do not have.

### `POST /api/bag/lines` → 201 + the bag

```json
{"brand": "kuurth.com", "itemurl": "https://kuurth.com/products/nemo-hoodie", "size": "M", "qty": 1}
```

- `brand` and `itemurl` are the tile's `brand_id` and `url`. Required.
- send `size` **or** `variant_id`. A size is resolved to the tile's `variant_id` for that
  size; a variant id fills in its size. A product with exactly one variant and no size
  (a tote) needs neither.
- `qty` optional, default 1, range 1–20.
- adding the same variant again **adds to the quantity** of the existing line (capped at 20)
  rather than making a second line. A different size of the same product is a second line.
- the line is titled, pictured and priced from the tile at that moment.

### `PATCH /api/bag/lines/{id}` `{"qty": 3}` → 200 + the bag

### `DELETE /api/bag/lines/{id}` → 200 + the bag

### `DELETE /api/bag` → 200 + the (empty) bag

### `GET /api/bag/checkout`

```json
{
  "provider": "cart_links",
  "charged_by": "each shop, on its own checkout, in its own currency",
  "checked": true,
  "shops": [
    {
      "brand": "kuurth.com",
      "brand_name": "Kuurth",
      "platform": "shopify",
      "currency": "USD",
      "quote": {"subtotal": 332.0, "lines_priced": 2, "lines_unpriced": 0, "lines_unavailable": 0, "...": "..."},
      "kind": "cart_links",
      "links": [
        {"url": "https://kuurth.com/cart/41000000001:2,41000000003:1", "kind": "cart", "line_ids": [17, 18]}
      ],
      "note": null,
      "line_ids": [17, 18],
      "unavailable_line_ids": []
    },
    {
      "brand": "wiacollections.com",
      "platform": "woo",
      "currency": "EUR",
      "kind": "cart_links",
      "links": [
        {"url": "https://wiacollections.com/?add-to-cart=201&quantity=1", "kind": "add_to_cart", "line_ids": [19]},
        {"url": "https://wiacollections.com/?add-to-cart=12&quantity=3", "kind": "add_to_cart", "line_ids": [20]}
      ],
      "note": "WooCommerce takes one item per link: open these 2 links in order, then check out once on the shop"
    }
  ]
}
```

Link kinds:

| `kind` | what it is | how many per shop |
|---|---|---|
| `cart` | Shopify cart permalink `https://<shop>/cart/<variant_id>:<qty>,…` — lands on the shop's checkout with every line in it | 1 |
| `add_to_cart` | WooCommerce `https://<shop>/?add-to-cart=<variation or product id>&quantity=<qty>` — adds one line to the shop's cart (a cookie on the shop) and shows the cart page | 1 per line |
| `product` | the product page; the person picks the size again there | 1 per line |

A line gets `product` when it has no `variant_id` (page-lane products, or a size the feed
did not name) or the shop is neither Shopify nor Woo. `note` says so when it happens.

Error cases, all `{"success": false, "error": "...", "code": "..."}`:

| status | code | when |
|---|---|---|
| 400 | `BAD_REQUEST` | `brand` or `itemurl` missing |
| 400 | `BAD_QTY` | qty not an integer in 1–20 |
| 400 | `UNKNOWN_VARIANT` | `variant_id` is not in the tile's `offers` |
| 400 | `UNKNOWN_SIZE` | `size` is not in the tile's `sizes` |
| 400 | `BAG_FULL` | 50 lines already |
| 400 | `EMPTY` | `/checkout` on an empty bag |
| 404 | `NOT_SHOWN` | the product is not on the shop front (gated brand, no photo, delisted, wrong url) |
| 404 | `NOT_FOUND` | line id is not in this user's bag |
| 503 | `WARMING` | adding while the storefront index is still building — retry in a few seconds |
| 401 | `NO_SESSION` / `INVALID_SESSION` | not signed in |

## States the UI goes through

```
tile / product page ──add──▶ bag (GET /api/bag) ──"Buy"──▶ GET /api/bag/checkout ──▶ shop's cart
                                  │                                   │
                            changed / unavailable                one link per shop
                            badges per line                      (Shopify: 1; Woo: 1 per line)
```

1. **Add.** Size button → `POST /api/bag/lines {brand, itemurl, size}`. Use the 201 body to
   open/refresh the drawer. A 503 `WARMING` means retry, not fail.
2. **Bag.** Render `shops[]`; each shop is a section with its own subtotal in its own
   currency and a converted figure beside it (below). Lines with `changed` show old → new;
   lines with `unavailable` are greyed and excluded from "Buy" for that shop
   (`unavailable_line_ids` on checkout says which).
3. **Buy.** `GET /api/bag/checkout`. One "Go to <shop>" button per shop, opening
   `links[0].url` in a new tab. For a Woo shop with several lines, open the links one after
   another (each returns the shop's cart page; the cart accumulates) and show `note`.
   For `product` links, say "pick your size on the shop".
4. **After paying.** We do not know. The shop has the order; we do not. Offer "Empty this
   shop's lines" (DELETE each line id) or "Empty bag" (`DELETE /api/bag`). Do not empty
   automatically on click — the tab may have been closed before paying.

## Currency

- A shop charges in **its own** currency (`shop.currency`). That is the number on the card
  statement; the card network converts at its own rate.
- The UI shows the visitor's currency with `web_ui/src/shared/money.js` exactly as the grid
  does: `priceText(amount, shopCurrency, visitorCurrency, rates)` renders `≈ €117` and falls
  back to the shop's figure when there is no rate. Rates come from `/api/archive/rates`
  (ECB via frankfurter.dev, base USD, cached 6 h; no RUB since 2022).
- Show **both** on the bag: the converted figure large, the shop's figure small ("charged as
  $252.00 USD"). Never sum across shops in one currency without the ≈ mark.
- The backend does no conversion. `quote.subtotal` is always in `quote.currency`.

## What the tile and the product page need

- Product page: a size row built from `tile.sizes[]`. A size with `variant_id` and
  `available: true` is a live "Add" button; `available: false` is shown struck through;
  no `variant_id` (page-lane brand) still adds — the line will have no cart id and checkout
  will hand the person the product page.
- If the page ever offers colour, read `tile.offers` (product page only) and post
  `variant_id` instead of `size`.
- A bag icon with `item_count` from `GET /api/bag` on load.
- A bag drawer rendering the shape above.

## Buyer of record: what exists in 2026 and what it would cost

The question: can one checkout on **our** site buy from arbitrary Shopify and WooCommerce
shops we have no relationship with? Findings from public pages, 2026-09-24:

| provider | works on merchants who did nothing? | what the merchant must do | fees (public) | shipping / tax / currency | platforms |
|---|---|---|---|---|---|
| **Rye** (Universal Checkout API) | **Yes** — "any product URL"; 15,000+ merchants claimed | nothing | Developer plan $149/month incl. $50 credits, then $0.05 per order placed and $0.02 per product fetch; enterprise custom. Third-party costs passed through at cost. 30-day trial | Rye returns price, shipping and tax for a real address and places the order; payment via tokenised card (Stripe / Prava); Rye does not publish who is merchant of record or how currency is handled | Shopify, Amazon, long-tail sites |
| **Shopify Collective** | No | supplier must be on a paid Shopify plan with Shopify Payments active, in one of 47 countries, and *accept our store's connection request*; we would need to be a Shopify store ourselves | free (Shopify takes nothing beyond normal fees); retailer margin 20–40 % set by supplier | supplier ships; our Shopify store charges the customer in our store's currency; 18 payout currencies | Shopify → Shopify only |
| **Carro** | No | brand installs Carro and approves us | from 5 % of GMV | supplier fulfils; we are the seller of record | Shopify (others via API) |
| **Canal** | No | brand installs Canal, is curated in, sets commission; we apply as a retailer | retailer: SaaS or hybrid, undisclosed; supplier keeps 70–80 % of MSRP, small per-sale fee | supplier ships; we charge the customer; supplier paid weekly via Stripe | Shopify first, "any back-end via API" |
| **Shopify Agentic Storefronts / UCP / ACP** | Partly — but for AI agents, not websites | merchant opts in to agentic storefronts (millions have, per Shopify, March 2026); checkout through ChatGPT (ACP, OpenAI+Stripe) or Google (UCP) | none published for third parties | the merchant's own checkout | Shopify; ACP adopted by 25+ platforms |
| **Bolt** | No | merchant integrates Bolt checkout | not public | Bolt is the checkout, merchant is MoR | any, if the merchant uses Bolt |
| **Shopify Storefront API / Buy SDK** | No | needs a Storefront access token issued by *that* merchant | free | the merchant's checkout | Shopify |

Sources: rye.com/pricing, rye.com/docs/api-v2/introduction, rye.com/blog/whitepaper-universal-checkout-api-agentic-commerce,
help.shopify.com (Collective requirements; cart permalinks at shopify.dev/docs/apps/build/checkout/create-cart-permalinks),
getcarro.com/get-custom-pricing and G2, shopcanal.com/faq, help.shopify.com agentic storefronts,
woocommerce.com/document/quick-guide-to-woocommerce-add-to-cart-urls.

**Recommendation.** Ship cart links now; they need nothing from any merchant and cover every
Shopify brand with one click and every Woo brand with one click per line. If a single
checkout across shops becomes worth paying for, **Rye is the only option that works on
merchants who did nothing** and the only one with a public price ($149/month + $0.05/order).
Cost at 200 orders/month: ~$159. What it would need from us: a Rye key, a hosted-checkout
session per bag (lines as product URL + variant id), a webhook to store order ids, and
address collection on our side — which is personal data we do not hold today. The
`buyer_of_record` adapter is where that goes; the route and the JSON do not change.

Things a buyer-of-record provider still cannot fix: a merchant that blocks bots at checkout
(the same WAFs that block the scraper), password-gated shops, and pre-orders/selling plans
(Shopify says cart permalinks do not carry them either).

## Not done

- **No live brand has been checked.** Cart-link formats are from Shopify's and
  WooCommerce's documentation, not from clicking one on a roster brand. The Woo
  `?add-to-cart=<variation_id>` form is documented to work without a `variation_id`
  parameter; a shop with a plugin that rewrites cart URLs will differ.
- **Offers arrive on the next scrape.** Until a brand re-runs, its tiles have no
  `variant_id`, the bag stores lines without one, and checkout hands back product pages.
- **Woo variation stock and price are the product's**, not the variation's — the Store API
  product list does not carry them. A size out of stock on a Woo shop reads as in stock here
  until the person reaches the shop.
- **Shopify markets.** Another session is adding market/currency selection to the Shopify
  connector; `offers[].price` follows whatever price `variants[].price` carries. A shop
  that prices by market will show the scraped market's price here and charge the buyer's
  market's price on its checkout.
- **Colour is not a first-class choice.** `sizes[].variant_id` picks one colour per size; a
  colour picker has to read `offers` (product page only) and post `variant_id`.
- **The bag is not shared to the frontend yet** — nothing under `web_ui/` reads these
  endpoints.
- **Buyer of record is a stub**: `CHECKOUT_PROVIDER=buyer_of_record` answers
  `kind: "provider_session"` with no links.
- **No order history**, no "did they buy it", no emptying after purchase.
- **No rate limit** specific to these endpoints beyond the session requirement.
- Storefront-index lookups are a linear scan of the tiles per line (≈ 30k tiles ×
  ≤ 50 lines); fine at this size, worth a dict if the roster grows 10×.

## Tests

- `tests/unit/archive/test_shopify_connector.py`, `test_woo_connector.py`, `test_domain.py`,
  `test_storefront.py` — offers, platform, handle, and the tile's `variant_id` per size (8 tests).
- `tests/unit/api/test_checkout_adapters.py` — the URL shapes and sums (7 tests).
- `tests/unit/api/test_bag_routes.py` — the route logic with rows in memory (15 tests).
- `tests/db/test_bag_routes.py` — the SQL against a real Postgres (5 tests; skip without one).

Run: `venv/bin/python -m pytest tests/unit -q` (794 pass) and, with Postgres on
`127.0.0.1:55432`, `venv/bin/python -m pytest tests/db/test_bag_routes.py tests/api/test_route_protection.py -q`.
