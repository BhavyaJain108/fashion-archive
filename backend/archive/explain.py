"""Watch one learning call, stage by stage.

The finder is the part that writes new extraction code, and it is otherwise a black box
that emits rules. This shows the whole exchange: how much of the page was sent, what the
model proposed, what each proposal actually produces when replayed, and which of the four
checks threw the rest away.

It is the same code path a run uses. Nothing is simulated.

Run: python -m backend.archive.explain <domain> <field> [<field> ...] [--url URL]
"""

import argparse
import sys
from pathlib import Path

from backend.archive import finder_llm as F
from backend.archive.finder import (
    apply_recipes,
    is_plausible,
    verify_recipe,
)
from backend.archive.observe import Spend
from backend.archive.store.catalog import Catalog
from backend.archive.transport import HttpxTransport

_RULE = "─" * 78


def explain(html: str, url: str, domain: str, fields: list[str], context: dict) -> None:
    stripped = F._strip(html)
    sent = stripped[: F._MAX_HTML]
    print(_RULE)
    print("1. THE PAGE")
    print(f"   raw            {len(html):>9,} characters")
    print(f"   stripped       {len(stripped):>9,}  (scripts, styles and comments removed)")
    print(f"   sent           {len(sent):>9,}  cap is {F._MAX_HTML:,}")
    if len(stripped) > F._MAX_HTML:
        print("   NOTE: the page was cut. Anything past the cut, the model cannot see —")
        print("         it then guesses the value and its own rule fails verification.")

    print(_RULE)
    print("2. WHAT IS ASKED")
    print(f"   fields         {', '.join(fields)}")
    print("   the model must answer through a tool schema, so there is no prose to parse:")
    print(f"   tool           {F.RECIPE_TOOL['name']}")
    print(f"   kinds allowed  {', '.join(F.RECIPE_KINDS)}")

    spend = Spend()
    client = F._AnthropicClient(spend=spend)
    prompt = F._PROMPT.format(fields=", ".join(fields), url=url, html=sent)
    proposed = F._to_recipes(client.propose(prompt))

    print(_RULE)
    print(f"3. WHAT CAME BACK — {len(proposed)} proposal(s), "
          f"{spend.input_tokens:,} tokens in, ${spend.usd}")
    if not proposed:
        print("   nothing. The model declines rather than guess, which is what the")
        print("   prompt asks of it — a wrong rule is worse than no rule.")
        return

    for r in proposed:
        got = apply_recipes(html, [r]).get(r.field, "")
        print(f"\n   field       {r.field}")
        print(f"   kind        {r.kind}" + (f"   attribute={r.attribute}" if r.attribute else ""))
        print(f"   expression  {r.expression}")
        print(f"   predicted   {(r.expected or '')[:150]}")
        print(f"   produces    {got[:150] or '(nothing)'}")

        print("   checks:")
        replay = verify_recipe(r, html)
        print(f"     replay    {'pass' if replay else 'FAIL'}"
              "   does the rule reproduce what the model predicted")
        shape = is_plausible(r.field, got) if got else False
        print(f"     shape     {'pass' if shape else 'FAIL'}"
              "   could this text be a value for this field")
        echo = is_plausible(r.field, got, context) if got else False
        print(f"     echo      {'pass' if echo else 'FAIL'}"
              "   is it the product's own title or description in disguise")
        kept = replay and shape and echo and r.field in fields
        print(f"     KEPT      {'yes' if kept else 'no'}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="explain")
    ap.add_argument("domain")
    ap.add_argument("fields", nargs="+")
    ap.add_argument("--url", help="a specific product page; default is one that lacks the field")
    args = ap.parse_args(argv)

    catalog = Catalog(Path("backend/archive/data/catalog.db"))
    try:
        rows = catalog.current_products(args.domain)
        if args.url:
            row = next((r for r in rows if r["itemurl"] == args.url), None) or {}
            url = args.url
        else:
            row = next(
                (r for r in rows if any(r.get(f) in (None, "", []) for f in args.fields)),
                rows[0] if rows else {},
            )
            url = row.get("itemurl")
        if not url:
            print(f"no products stored for {args.domain}")
            return 1
        context = {
            "product_title": row.get("product_title"),
            "description": row.get("description"),
        }
        print(f"\nlearning {', '.join(args.fields)} for {args.domain}")
        print(f"from {url}\n")
        resp = HttpxTransport().get(url)
        if resp.status_code != 200:
            print(f"the page answered HTTP {resp.status_code}")
            return 1
        explain(resp.text, url, args.domain, args.fields, context)
        return 0
    finally:
        catalog.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
