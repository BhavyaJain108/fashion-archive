"""A product journal: what we stored, next to the page it came from.

Percentages say a field is filled. They cannot say it is right, and every wrong value
found this week — a size that read "Sold out", a brand that was a campaign name, a
material that was the whole short description — was found by a person looking at one
product. This makes that cheap: the photographs we recorded, every field we hold, where
each value came from, and a link to the live page to check it against.

Written as a plain file so the images load and the page prints to PDF.

Run: python -m backend.archive.journal <domain> [--limit N] [--out FILE]
"""

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.archive.domain.product import E0005_FIELDS, ProductRecord
from backend.archive.score import REQUIRED, score
from backend.archive.store.catalog import Catalog

_CSS = """
:root { color-scheme: light }
* { box-sizing: border-box }
body { margin: 0; padding: 32px; font: 14px/1.5 -apple-system, BlinkMacSystemFont, sans-serif;
       color: #1a1a1a; background: #fff; max-width: 1100px }
h1 { font-size: 22px; margin: 0 0 4px }
.sub { color: #666; margin-bottom: 24px }
.summary { border: 1px solid #ddd; padding: 16px; margin-bottom: 28px; background: #fafafa }
.summary b { font-weight: 600 }
.pass { color: #1a7f37; font-weight: 600 }
.fail { color: #b42318; font-weight: 600 }
.product { border-top: 2px solid #1a1a1a; padding: 20px 0 28px; page-break-inside: avoid }
.title { font-size: 17px; font-weight: 600; margin: 0 0 2px }
.url { font-size: 12px; margin-bottom: 12px }
.url a { color: #0969da }
.shots { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px }
.shots img { height: 190px; width: auto; border: 1px solid #e5e5e5; background: #f6f6f6;
             object-fit: cover }
table { border-collapse: collapse; width: 100%; font-size: 13px }
td { padding: 4px 10px 4px 0; vertical-align: top; border-bottom: 1px solid #f0f0f0 }
td.k { width: 170px; color: #555; white-space: nowrap }
td.v { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-word }
td.src { width: 210px; color: #888; font-size: 11px }
.req { font-weight: 600 }
.missing { color: #b42318 }
.blank { margin-top: 10px; color: #888; font-size: 12px }
@media print { body { padding: 0 } .product { border-top-width: 1px } }
"""


def _shots(row: dict, limit: int = 5) -> list[str]:
    try:
        return json.loads(row.get("all_images") or "[]")[:limit]
    except (json.JSONDecodeError, TypeError):
        return []


def render(catalog: Catalog, domain: str, limit: int, offset: int = 0) -> str:
    rows = catalog.current_products(domain)
    if not rows:
        return f"<p>nothing stored for {html.escape(domain)}</p>"
    book = catalog.load_recipe_book(domain)
    learned = {r.field: r for r in (book.recipes if book else [])}
    plan = catalog.load_plan(domain)
    card = score([ProductRecord(**r) for r in rows])
    shown = rows[offset : offset + limit]

    parts = [
        "<!doctype html><meta charset='utf-8'>",
        f"<title>{html.escape(domain)} — product journal</title>",
        f"<style>{_CSS}</style>",
        f"<h1>{html.escape(domain)}</h1>",
        f"<div class='sub'>{len(rows)} products stored &middot; "
        f"showing {len(shown)} from #{offset + 1} &middot; "
        f"generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</div>",
        "<div class='summary'>",
        f"<b>lane</b> {html.escape(plan.composition) if plan else '—'}<br>",
        f"<b>gate</b> <span class='{'pass' if card.required_ok else 'fail'}'>"
        f"{'PASS' if card.required_ok else 'FAIL — ' + ', '.join(card.required_gaps)}"
        f"</span><br>",
        f"<b>fields</b> {card.fields_filled:.0%} of 42 &nbsp; "
        f"<b>images</b> {card.images_per_product} per product<br>",
        f"<b>learned rules</b> {len(learned)}: "
        + html.escape(", ".join(sorted(learned)) or "none")
        + "<br><br>",
        "Each value below says where it came from. Click the product link and check the "
        "page against what we stored — a value can be filled, stable and still wrong.",
        "</div>",
    ]

    for row in shown:
        parts.append("<div class='product'>")
        parts.append(f"<p class='title'>{html.escape(row.get('product_title') or '—')}</p>")
        url = row.get("itemurl") or ""
        parts.append(
            f"<div class='url'><a href='{html.escape(url)}' target='_blank' "
            f"rel='noreferrer'>{html.escape(url)}</a></div>"
        )
        shots = _shots(row)
        if shots:
            parts.append("<div class='shots'>")
            for src in shots:
                parts.append(
                    f"<a href='{html.escape(src)}' target='_blank' rel='noreferrer'>"
                    f"<img src='{html.escape(src)}' loading='lazy' alt=''></a>"
                )
            parts.append("</div>")

        parts.append("<table>")
        for field in E0005_FIELDS:
            value = row.get(field)
            if value in (None, "", []) or field in ("itemurl", "product_title"):
                continue
            if field == "all_images":
                value = f"{len(_shots(row, 999))} URLs"
            rule = learned.get(field)
            source = f"learned: {rule.kind} {rule.expression[:34]}" if rule else "from the channel"
            css = "k req" if field in REQUIRED else "k"
            parts.append(
                f"<tr><td class='{css}'>{field}</td>"
                f"<td class='v'>{html.escape(str(value)[:400])}</td>"
                f"<td class='src'>{html.escape(source)}</td></tr>"
            )
        parts.append("</table>")

        blank = [f for f in E0005_FIELDS if row.get(f) in (None, "", [])]
        missing_required = [f for f in REQUIRED if row.get(f) in (None, "", [])]
        if missing_required:
            parts.append(
                "<p class='blank missing'>required and missing: "
                + ", ".join(missing_required)
                + "</p>"
            )
        parts.append(f"<p class='blank'>{len(blank)} fields blank: " + ", ".join(blank) + "</p>")
        parts.append("</div>")
    return "\n".join(parts)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="journal")
    ap.add_argument("domain")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    catalog = Catalog(Path("backend/archive/data/catalog.db"))
    try:
        page = render(catalog, args.domain, args.limit, args.offset)
    finally:
        catalog.close()
    out = args.out or Path(f"backend/archive/data/journal-{args.domain}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
