"""What to do about a brand next, read off what the last run recorded.

Everything here is already in the database — the scorecard, the search record, the field
validator, the host ledger. What was missing is anything that reads them together and
says which thing to fix first, so the answer lived in my head and had to be re-derived
every time.

The ordering is not a preference. It follows from what each finding costs to act on and
what it blocks:

  1 FAILED GATE    a shop cannot sell without a name, price, stock and pictures, so a
                   blank there is our bug and the run did not succeed. A field that
                   used to be filled and is not any more ranks here too: something we
                   changed took it away, and that is the most recoverable kind of loss.
  2 WRONG DATA     a field holding the wrong kind of thing is worse than an empty one,
                   because it is believed. Free to fix — no scraping, no model.
  3 BLOCKED HOST   a brand answering 403 needs a different transport, not better rules.
  4 UNSEARCHED     fields nobody has ever looked for on the page. The cheapest real
                   gains, and the largest count.
  5 DEAD END       asked for and not found. Only worth revisiting when the site changes.
  6 EXPENSIVE      working, but costing more than it should per brand.

Run: python -m backend.archive.recommend [domain ...]
"""

import sys

from backend.archive.domain.product import E0005_FIELDS
from backend.archive.evidence import describe
from backend.archive.score import regressions
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import object_store
from backend.archive.validate import check_brand_catalogue

# What one brand may cost per run before it is worth a look. Per brand, not per
# product: what we are buying is a set of rules for a shop, and a shop with 200
# products should not cost more than one with 20 once its rules are learned.
_COST_PER_BRAND = 1.00
# A rule winning less than this share of its field's fills was learned from one page's
# accident rather than the shop's layout.
_NARROW_RULE = 0.15


def recommend(catalog: Catalog, domain: str) -> list[tuple[int, str, str]]:
    """(priority, headline, what to do) for one brand, most urgent first."""
    rows = catalog.current_products(domain)
    if not rows:
        return [(1, "nothing stored", "the last run kept no products — read its log first")]

    evidence = catalog.load_evidence(domain)
    cards = catalog.scorecards(domain, limit=2)
    card = cards[0] if cards else None
    out: list[tuple[int, str, str]] = []

    # 1 — what this run lost against the one before it
    if len(cards) == 2:
        for field, was, now in regressions(cards[1], cards[0]):
            out.append(
                (
                    1,
                    f"{field} fell from {was:.0%} to {now:.0%}",
                    "it was working on the last run — the change since is the place to "
                    "look, not the site",
                )
            )
        if cards[1]["required_ok"] and not cards[0]["required_ok"]:
            out.append(
                (
                    1,
                    "this run failed a gate the last one passed",
                    "compare the two runs before scraping again",
                )
            )

    # 1 — the gate
    if card and not card["required_ok"]:
        for field, share in sorted(card["required_gaps"].items(), key=lambda x: -x[1]):
            # A single product in two hundred rounds to 0%, which reads as "nothing
            # missing" for a finding that only exists because something is.
            n = round(share * card["products"])
            out.append(
                (
                    1,
                    f"{field} missing on {n} of {card['products']} products",
                    "a shop cannot sell without this, so the blank is ours: "
                    + describe(evidence, field),
                )
            )

    # 2 — fields holding the wrong kind of thing
    for field, problem in check_brand_catalogue(rows):
        out.append((2, f"{field} looks wrong", problem))

    # 3 — how the host is answering
    for host in catalog.host_stats():
        if not any(host["host"].endswith(d) for d in (domain, domain.removeprefix("www."))):
            continue
        if host["refused"]:
            out.append(
                (
                    3,
                    f"{host['host']} refused {host['refused']} of {host['requests']} requests",
                    "401/403 is a decision that we are a bot — needs a different "
                    "transport, not better rules",
                )
            )
        elif host["busy"]:
            out.append(
                (
                    3,
                    f"{host['host']} asked us to slow down {host['busy']} times",
                    "raise --gap for this host before adding more workers",
                )
            )

    # 4 and 5 — what the search record says about every blank
    unsearched: list[str] = []
    dead: list[str] = []
    for field in E0005_FIELDS:
        if any(r.get(field) not in (None, "", []) for r in rows):
            continue
        (dead if describe(evidence, field).startswith("absent from") else unsearched).append(field)
    if unsearched:
        out.append(
            (
                4,
                f"{len(unsearched)} fields never looked for on the page",
                "one finder call covers several: "
                + ", ".join(unsearched[:8])
                + ("…" if len(unsearched) > 8 else ""),
            )
        )
    if dead:
        out.append(
            (
                5,
                f"{len(dead)} fields asked for and not found",
                "the page did not show them: "
                + ", ".join(dead)
                + " — clear their evidence rows to try again after the site changes",
            )
        )

    # 2b — rules that only ever worked on the page they came from
    book = catalog.load_recipe_book(domain)
    if book:
        by_field: dict[str, list] = {}
        for r in book.recipes:
            by_field.setdefault(r.field, []).append(r)
        for field, rules in by_field.items():
            total = sum(r.hits for r in rules)
            if total < 20:
                continue  # too few fills to judge one rule against another
            for r in rules:
                if r.hits / total < _NARROW_RULE:
                    out.append(
                        (
                            2,
                            f"{field} rule fires on {r.hits / total:.0%} of its fills",
                            f"{r.kind} {r.expression!r} — learned from one page's "
                            "accident; worth asking for a general one before the next run",
                        )
                    )

    # 6 — what it costs
    if card and card["cost_usd"] > _COST_PER_BRAND:
        out.append(
            (
                6,
                f"${card['cost_usd']:.2f} for this brand",
                "rules are being learned more often than they are being reused",
            )
        )
    return sorted(out, key=lambda x: x[0])


def main(argv: list[str]) -> int:
    catalog = Catalog(object_store())
    try:
        domains = argv or [
            r["domain"] for r in catalog.status_rows() if catalog.current_products(r["domain"])
        ]
        for domain in domains:
            findings = recommend(catalog, domain)
            cards = catalog.scorecards(domain, limit=1)
            head = ""
            if cards:
                c = cards[0]
                head = (
                    f"  {c['products']} products, "
                    f"{'PASS' if c['required_ok'] else 'FAIL'}, "
                    f"{c['fields_filled']:.0%} of 42 fields, "
                    f"{c['images_per_product']} img/product, "
                    f"${c['cost_usd']}, {c['seconds_per_product']}s/product"
                )
            print(f"\n{domain}\n{head}")
            for priority, headline, action in findings:
                print(f"   [{priority}] {headline}\n       {action}")
            if not findings:
                print("   nothing to do")
        return 0
    finally:
        catalog.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
