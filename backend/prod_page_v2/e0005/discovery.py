"""
Discovery — learn the cheapest reproducible method for each E0005 field on
a new brand.

Pipeline:
  1. Run LLM ground-truth extraction (`extract_ground_truth`) on a seed
     product URL. Produces an "answer key" ProductFields covering as many
     of the 38 fields as the page actually has.
  2. Generate candidate cheap methods for every field (enumerate known
     LD+JSON paths, OG meta names, microdata properties, accordion
     selectors from Phase A hideaways, etc.).
  3. Run each candidate on the same PageMemo. Compare result to the LLM
     ground-truth value via field-typed equality.
  4. Persist a SiteCatalog with one or more rows per field, ordered by
     confidence. Methods that produced a matching value go in the
     catalog; the rest are discarded.

The catalog is then used by the FieldOrchestrator at production time —
zero LLM calls, runs only the saved methods.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .catalog import CatalogRow, SiteCatalog
from .ground_truth import GroundTruthResult, Hideaway, extract_ground_truth
from .llm_propose import propose_methods_for_uncovered_fields
from .memo import PageMemo
from .methods.accordion_read import AccordionReadMethod
from .methods.dom_selector import DomSelectorMethod
from .methods.ld_images import LdJsonImagesMethod, NetworkImagesMethod
from .methods.ld_json import LdJsonPathMethod
from .methods.ld_offers import LdJsonOffersAvailabilityMethod
from .methods.nav_tree import NavTreeMethod
from .methods.og_meta import OgMetaMethod
from .methods.shopify_json import ShopifyProductJsonMethod
from .schema import EXTRACTABLE_FIELDS, ProductFields
from .selector_finder import find_selectors_for_value


# Shopify /products/<slug>.json paths per E0005 field. When the endpoint
# responds, these are the highest-confidence cheap methods available.
SHOPIFY_CANDIDATES: Dict[str, List[Tuple[str, Optional[str], str]]] = {
    "product_title":  [("product.title", None, "first")],
    "product_code":   [("product.variants[].sku:first", None, "first")],
    "brand":          [("product.vendor", None, "first")],
    "description":    [("product.body_html", "html_strip", "first")],
    "category1":      [("product.product_type", None, "first")],
    "price":          [("product.variants[].price:first", "shopify_price_cents", "first")],
    "full_price":     [
        ("product.variants[].compare_at_price:first", "shopify_price_cents", "first"),
        # Fallback: when no compare_at_price (not on sale), full_price = price.
        ("product.variants[].price:first", "shopify_price_cents", "first"),
    ],
    "size_info":      [("product.variants[].option1:dedupe_join_comma", None, "first")],
    "color_info":     [("product.variants[].option2:dedupe_join_comma", None, "first")],
    "material_info":  [("product.variants[].option3:dedupe_join_comma", None, "first")],
    "in_stock":       [("product.variants[].available:any_truthy", None, "first")],
    "additional_tags": [("product.tags", None, "first")],
    "main_image_url": [("product.images[0].src", None, "first")],
    "all_images":     [("product.images[].src:json", None, "first")],
}


# Candidate LD+JSON paths to try per field. Source: schema.org Product spec.
LD_JSON_CANDIDATES: Dict[str, List[Tuple[str, Optional[str]]]] = {
    "product_title":   [("$.name", None), ("$.title", None)],
    "product_code":    [("$.sku", None), ("$.mpn", None), ("$.productID", None)],
    "additional_code_1": [("$.gtin13", None), ("$.gtin", None), ("$.gtin12", None)],
    "brand":           [("$.brand.name", None), ("$.brand", None)],
    "description":     [("$.description", None)],
    "color_info":      [("$.color", None)],
    "price":           [("$.offers.price", "to_float"), ("$.offers.lowPrice", "to_float")],
    "full_price":      [("$.offers.highPrice", "to_float")],
    "category1":       [("$.category", None)],
    "main_image_url":  [("$.image", None), ("$.image[0]", None)],
}

# OG/Twitter/product meta candidates per field.
OG_META_CANDIDATES: Dict[str, List[Tuple[str, Optional[str]]]] = {
    "product_title":  [("og:title", "html_unescape"), ("twitter:title", "html_unescape")],
    "description":    [("og:description", "html_unescape"), ("description", "html_unescape")],
    "main_image_url": [("og:image", None), ("twitter:image", None)],
    "price":          [("product:price:amount", "to_float"), ("og:price:amount", "to_float")],
    "brand":          [("og:brand", None), ("product:brand", None)],
}

# Mapping from hideaway label keywords → which E0005 field they likely fill.
HIDEAWAY_LABEL_TO_FIELD = [
    ("composition", "material_info"),
    ("material",    "material_info"),
    ("fabric",      "material_info"),
    ("care",        "material_info"),  # often combined with composition
    ("details",     "specifications"),
    ("specification", "specifications"),
    ("description", "description"),
    ("view details", "specifications"),
    ("show more",   "description"),
    ("shipping",    "delivery"),
    ("delivery",    "delivery"),
    ("returns",     "delivery"),
]


# ---------------------------------------------------------------------------
# Field-aware comparison
# ---------------------------------------------------------------------------

def _norm_str(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


_UNKNOWN_SENTINELS = {"<unknown>", "unknown", "n/a", "not visible", "not found", ""}
_PLACEHOLDER_URL_RE = re.compile(r"^https?://(image|placeholder|url|example|test)\d*$", re.IGNORECASE)


def _is_unknown(truth: Any) -> bool:
    """Detect when the LLM ground-truth value is a placeholder or sentinel
    that we should ignore in favor of cheap-method outputs.

    Vision LLMs hallucinate image URLs (they can SEE images but not their
    href) — emitting things like "https://image1", "https://placeholder.jpg"
    which we must reject as truth values.
    """
    if truth is None:
        return True
    if isinstance(truth, str):
        ns = _norm_str(truth)
        if ns in _UNKNOWN_SENTINELS:
            return True
        if _PLACEHOLDER_URL_RE.match(truth.strip()):
            return True
    if isinstance(truth, list):
        if len(truth) == 0:
            return True
        # All-placeholder list: treat as unknown.
        if all(isinstance(u, str) and _PLACEHOLDER_URL_RE.match(u.strip()) for u in truth):
            return True
    return False


def _values_match(field: str, candidate: Any, truth: Any) -> bool:
    """Decide whether a method's output reproduces the LLM ground truth
    closely enough to be cataloged."""
    if candidate is None:
        return False
    # For image fields, also detect placeholder URLs inside a JSON-encoded list
    # so we don't try to match against hallucinated values.
    truth_unknown = _is_unknown(truth)
    if not truth_unknown and field == "all_images" and isinstance(truth, str):
        try:
            parsed = json.loads(truth)
            if isinstance(parsed, list) and _is_unknown(parsed):
                truth_unknown = True
        except Exception:
            pass
    if truth_unknown and field in ("main_image_url", "all_images"):
        if field == "main_image_url" and isinstance(candidate, str) and candidate.startswith("http"):
            return True
        if field == "all_images":
            try:
                arr = json.loads(candidate) if isinstance(candidate, str) else candidate
                return isinstance(arr, list) and len(arr) >= 1
            except Exception:
                return False
    if truth is None:
        return False
    # Numeric fields: ~1% tolerance
    if field in ("price", "full_price", "ppu"):
        try:
            return abs(float(candidate) - float(truth)) / max(1.0, float(truth)) < 0.01
        except (ValueError, TypeError):
            return False
    if field in ("in_stock", "quantity"):
        try:
            return int(candidate) == int(truth)
        except (ValueError, TypeError):
            return False
    # Codes: require exact equality (prefix-tolerant for trailing variant codes).
    # Otherwise "SKU: 5632385-200" would substring-match "5632385-200" and
    # produce a brittle catalog row on a selector that returns the prefixed form.
    if field in ("product_code", "additional_code_1", "additional_code_2", "additional_code_3"):
        return _norm_str(candidate) == _norm_str(truth)
    if field == "all_images":
        # Each is JSON-encoded list of URLs. Match if:
        #   (a) ≥80% of truth URLs are in candidate (URL-set overlap), OR
        #   (b) candidate is a plausible list of CDN URLs and contains the SKU
        #       segment that appears in the truth URLs (covers Shopify
        #       multi-shop-ID quirk where same product has different shop IDs).
        try:
            ct = json.loads(candidate) if isinstance(candidate, str) else candidate
            tr = json.loads(truth) if isinstance(truth, str) else truth
            if not isinstance(ct, list) or len(ct) == 0:
                return False
            if not isinstance(tr, list) or len(tr) == 0:
                # When truth is unknown but candidate is a non-empty URL list, accept.
                return all(isinstance(u, str) and u.startswith("http") for u in ct)
            tr_set = {u.split("?")[0] for u in tr}
            ct_set = {u.split("?")[0] for u in ct}
            overlap = len(tr_set & ct_set) / len(tr_set)
            if overlap >= 0.8:
                return True
            # Cross-shop-ID acceptance: extract SKU-like alphanumeric tokens
            # from URLs and check overlap.
            def _tokens(urls):
                out = set()
                for u in urls:
                    # Pull alphanumeric runs of length 6+ that contain a digit.
                    for tok in re.findall(r"[A-Za-z0-9]{6,}", u):
                        if any(ch.isdigit() for ch in tok):
                            out.add(tok)
                return out
            common = _tokens(tr) & _tokens(ct)
            if common and abs(len(ct) - len(tr)) <= max(2, len(tr) // 2):
                return True
            # Last resort: both are valid CDN URL lists, same provider, comparable count.
            from urllib.parse import urlparse as _up
            tr_netlocs = {_up(u).netloc for u in tr}
            ct_netlocs = {_up(u).netloc for u in ct}
            if tr_netlocs == ct_netlocs and abs(len(ct) - len(tr)) <= max(2, len(tr) // 2):
                return True
            return False
        except Exception:
            return False
    if field == "main_image_url":
        # Same exact URL (minus querystring), OR both from same product CDN.
        c = _norm_str(str(candidate).split("?")[0])
        t = _norm_str(str(truth).split("?")[0])
        if c == t:
            return True
        # Same Shopify shop + same SKU/handle stem accepted as a match
        # (Shopify often has multiple images for one product — GHOST/LOOK/etc).
        from urllib.parse import urlparse as _up
        cu, tu = _up(c), _up(t)
        if cu.netloc == tu.netloc and cu.netloc.endswith("shopify.com"):
            # If both URLs share at least one common path segment (the product SKU/slug), accept.
            cseg = set(p for p in cu.path.split("/") if len(p) > 3)
            tseg = set(p for p in tu.path.split("/") if len(p) > 3)
            if cseg & tseg:
                return True
        return False
    if field.startswith("category"):
        return _norm_str(candidate) == _norm_str(truth)

    # Default: text fields — accept if one contains the other (LLM may add
    # context like prefixes or label words).
    nc, nt = _norm_str(candidate), _norm_str(truth)
    if nc == nt:
        return True
    # Comma-separated lists: compare as sets after stripping spaces.
    if "," in nc or "," in nt:
        c_set = {p.strip() for p in re.split(r"[,;]", nc) if p.strip()}
        t_set = {p.strip() for p in re.split(r"[,;]", nt) if p.strip()}
        if c_set and t_set:
            # Case-insensitive: if one set ⊆ the other or they share ≥80% items.
            if c_set == t_set:
                return True
            overlap = len(c_set & t_set) / max(len(c_set), len(t_set))
            if overlap >= 0.8:
                return True
    # Strong substring containment in either direction, ≥50% length ratio.
    if nt and nc and (nt in nc or nc in nt):
        shorter, longer = sorted([nt, nc], key=len)
        return len(shorter) / len(longer) >= 0.5
    return False


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

async def _try_method(method, memo: PageMemo, field: str) -> Any:
    try:
        result = await method.produce(memo, field)
        return result.value
    except Exception:
        return None


async def discover_for_brand(
    seed_url: str,
    brand_label: Optional[str] = None,
    nav_json_path: Optional[str] = None,
) -> Tuple[SiteCatalog, GroundTruthResult, Dict[str, List[Tuple[str, Any, bool]]]]:
    """Run discovery on one seed URL. Returns (catalog, ground_truth, method_results).

    method_results: dict mapping field_name → list of (method_kind_label, value, matched).
    Used by the Gate 2 report.
    """
    domain = urlparse(seed_url).netloc.replace("www.", "")
    memo = PageMemo(seed_url)
    try:
        # Phase 1: LLM ground truth (also leaves memo with renderered + revealed state).
        gt_result = await extract_ground_truth(memo)
        gt = gt_result.product_fields

        # Phase 2: enumerate + try candidate methods.
        method_results: Dict[str, List[Tuple[str, Any, bool]]] = {}
        catalog_rows: List[CatalogRow] = []

        # 2-shopify. Try /products/<slug>.json first — when the brand is on
        # Shopify, this one endpoint produces structured data for ~12 fields
        # in a single HTTP call.
        shopify_blob = None
        try:
            shopify_blob = await ShopifyProductJsonMethod._get_blob(memo)
        except Exception:
            shopify_blob = None
        def _already_covered(f: str) -> bool:
            return any(r.field == f for r in catalog_rows)

        if shopify_blob is not None:
            for field, candidates in SHOPIFY_CANDIDATES.items():
                if _already_covered(field):
                    continue
                truth_val = getattr(gt, field, None)
                # For image fields we also accept the <UNKNOWN> sentinel
                if truth_val is None and not _is_unknown(truth_val):
                    continue
                if gt.is_field_blank(field) and field not in ("main_image_url", "all_images"):
                    continue
                for path, transform, mode in candidates:
                    method = ShopifyProductJsonMethod(field_path=path, transform=transform, mode=mode)
                    value = await _try_method(method, memo, field)
                    matched = _values_match(field, value, truth_val)
                    method_results.setdefault(field, []).append(
                        (f"shopify_product_json[{path}]", value, matched)
                    )
                    if matched:
                        catalog_rows.append(CatalogRow(
                            field=field, method=method, confidence=1.0,
                            notes=f"shopify product.json; truth={truth_val!r}",
                        ))
                        break

        # 2a. LD+JSON path candidates
        for field, candidates in LD_JSON_CANDIDATES.items():
            if _already_covered(field):
                continue
            truth_val = getattr(gt, field, None)
            if truth_val is None:
                continue
            for path, transform in candidates:
                method = LdJsonPathMethod(path=path, transform=transform)
                value = await _try_method(method, memo, field)
                matched = _values_match(field, value, truth_val)
                method_results.setdefault(field, []).append(
                    (f"ld_json_path[{path}]", value, matched)
                )
                if matched:
                    catalog_rows.append(CatalogRow(
                        field=field, method=method, confidence=1.0,
                        notes=f"verified at discovery against truth={truth_val!r}",
                    ))
                    break  # first match wins for this field

        # 2b. LdJsonImagesMethod for main_image_url / all_images
        for field in ("main_image_url", "all_images"):
            truth_val = getattr(gt, field, None)
            if truth_val is None:
                continue
            method = LdJsonImagesMethod()
            value = await _try_method(method, memo, field)
            matched = _values_match(field, value, truth_val)
            method_results.setdefault(field, []).append(
                ("ld_json_images", value, matched)
            )
            if matched and not any(r.field == field for r in catalog_rows):
                catalog_rows.append(CatalogRow(
                    field=field, method=method, confidence=1.0,
                    notes="LD+JSON image array",
                ))
            elif not matched:
                # Try network images as a fallback.
                sku_hint = (gt.product_code or "")[:11]  # first 11 chars of SKU
                nm = NetworkImagesMethod(sku_hint=sku_hint, path_pattern="")
                value = await _try_method(nm, memo, field)
                matched = _values_match(field, value, truth_val)
                method_results.setdefault(field, []).append(
                    (f"network_images[sku_hint={sku_hint!r}]", value, matched)
                )
                if matched and not _already_covered(field):
                    catalog_rows.append(CatalogRow(
                        field=field, method=nm, confidence=0.9,
                        notes="network-captured CDN URLs matching SKU",
                    ))

        # 2c. ld_json_offers_availability for in_stock
        if getattr(gt, "in_stock", None) is not None:
            method = LdJsonOffersAvailabilityMethod()
            value = await _try_method(method, memo, "in_stock")
            matched = _values_match("in_stock", value, gt.in_stock)
            method_results.setdefault("in_stock", []).append(
                ("ld_json_offers_availability", value, matched)
            )
            if matched:
                catalog_rows.append(CatalogRow(
                    field="in_stock", method=method, confidence=0.95,
                ))

        # 2d. OG meta candidates
        for field, candidates in OG_META_CANDIDATES.items():
            truth_val = getattr(gt, field, None)
            if truth_val is None:
                continue
            if any(r.field == field for r in catalog_rows):
                continue  # already covered by a cheaper method
            for name, transform in candidates:
                method = OgMetaMethod(name=name, transform=transform)
                value = await _try_method(method, memo, field)
                matched = _values_match(field, value, truth_val)
                method_results.setdefault(field, []).append(
                    (f"og_meta[{name}]", value, matched)
                )
                if matched:
                    catalog_rows.append(CatalogRow(
                        field=field, method=method, confidence=0.95,
                    ))
                    break

        # 2e. Accordion methods for revealed hideaways
        for h in gt_result.hideaways:
            if not h.panel_text:
                continue
            # Map label keyword → likely field
            label_lower = h.label.lower()
            field_target = None
            for kw, fld in HIDEAWAY_LABEL_TO_FIELD:
                if kw in label_lower:
                    field_target = fld
                    break
            if field_target is None:
                continue
            truth_val = getattr(gt, field_target, None)
            if truth_val is None:
                continue
            if any(r.field == field_target for r in catalog_rows):
                continue
            method = AccordionReadMethod(
                trigger_selector=h.trigger_selector,
                panel_selector=h.panel_selector,
            )
            value = await _try_method(method, memo, field_target)
            matched = _values_match(field_target, value, truth_val)
            method_results.setdefault(field_target, []).append(
                (f"accordion_read[{h.label}]", value, matched)
            )
            if matched:
                catalog_rows.append(CatalogRow(
                    field=field_target, method=method, confidence=0.85,
                    notes=f"revealed via hideaway {h.label!r}",
                ))

        # 2e1. LLM-proposed DOM methods for any field the LLM filled but no
        # cheap method matched. This is the per-brand adaptive step:
        # one LLM call enumerates selectors for whatever's left.
        already_covered = {r.field for r in catalog_rows}
        # itemurl is set by the orchestrator directly; categories handled later.
        skip_fields = already_covered | {"itemurl"} | {f"category{i}" for i in range(1, 11)}
        uncovered = [
            f for f in EXTRACTABLE_FIELDS
            if f not in skip_fields and not gt.is_field_blank(f)
        ]
        if uncovered:
            proposals, propose_usage = await propose_methods_for_uncovered_fields(
                memo, gt, uncovered,
            )
            gt_result.llm_calls += 1
            gt_result.llm_input_tokens += propose_usage["input_tokens"]
            gt_result.llm_output_tokens += propose_usage["output_tokens"]
            # Re-cost
            _icost = (gt_result.llm_input_tokens / 1_000_000) * 3.0
            _ocost = (gt_result.llm_output_tokens / 1_000_000) * 15.0
            gt_result.llm_cost_usd = round(_icost + _ocost, 4)
            gt_result.notes.append(f"Phase D: proposed {len(proposals)} DOM methods")

            print(f"[Discovery] LLM proposed {len(proposals)} method(s):")
            for field, method in proposals:
                print(f"  - {field} -> {method.kind} {method._config_dict()}")
                truth_val = getattr(gt, field, None)
                value = await _try_method(method, memo, field)
                matched = _values_match(field, value, truth_val)
                tag = "✓" if matched else "✗"
                preview = (str(value)[:80] + "…") if value and len(str(value)) > 80 else value
                print(f"    {tag} got={preview!r}  truth={(str(truth_val)[:80])!r}")
                method_results.setdefault(field, []).append(
                    (f"{method.kind}[llm-proposed]", value, matched)
                )
                if matched:
                    catalog_rows.append(CatalogRow(
                        field=field, method=method, confidence=0.85,
                        notes=f"LLM-proposed; verified against truth={truth_val!r}",
                    ))

        # 2e2. DOM-walker selector finder for any field still uncovered.
        # Pure-Python: search rendered HTML for the truth value, walk up to a
        # stable selector, validate. No additional LLM cost.
        still_uncovered = [
            f for f in EXTRACTABLE_FIELDS
            if f not in ({r.field for r in catalog_rows} | {"itemurl"})
            and f not in (f"category{i}" for i in range(1, 11))
            and not gt.is_field_blank(f)
        ]
        if still_uncovered:
            rendered_html = await memo.rendered_html()
            print(f"[Discovery] DOM-walker trying {len(still_uncovered)} field(s):")
            for field in still_uncovered:
                truth_val = getattr(gt, field, None)
                if not isinstance(truth_val, str):
                    continue
                cands = find_selectors_for_value(rendered_html, truth_val, field, max_candidates=4)
                if not cands:
                    print(f"  - {field}: no selector candidates from DOM walk")
                    continue
                for cand in cands:
                    method = DomSelectorMethod(
                        selector=cand.selector,
                        mode=cand.mode,
                        transform="strip" if cand.mode == "first" else None,
                        separator=", " if cand.mode == "all_join" else ", ",
                    )
                    value = await _try_method(method, memo, field)
                    matched = _values_match(field, value, truth_val)
                    tag = "✓" if matched else "✗"
                    preview = (str(value)[:80] + "…") if value and len(str(value)) > 80 else value
                    print(f"  - {field} -> {cand.mode} {cand.selector!r}  {tag} got={preview!r}")
                    method_results.setdefault(field, []).append(
                        (f"dom_selector[walker:{cand.selector}]", value, matched)
                    )
                    if matched:
                        catalog_rows.append(CatalogRow(
                            field=field, method=method, confidence=0.8,
                            notes=f"DOM-walker; verified against truth={truth_val!r}",
                        ))
                        break  # first match wins for this field

        # 2f. NavTreeMethod for category1..category10 (when nav.json present)
        if nav_json_path and Path(nav_json_path).exists():
            method = NavTreeMethod(nav_json_path=nav_json_path)
            for level in range(1, 11):
                field = f"category{level}"
                truth_val = getattr(gt, field, None)
                if truth_val is None:
                    continue
                value = await _try_method(method, memo, field)
                matched = _values_match(field, value, truth_val)
                method_results.setdefault(field, []).append(
                    ("nav_tree", value, matched)
                )
                if matched:
                    catalog_rows.append(CatalogRow(
                        field=field, method=NavTreeMethod(nav_json_path=nav_json_path),
                        confidence=0.95,
                    ))

        # Phase 3: persist catalog
        catalog = SiteCatalog(
            domain=domain,
            discovered_at=datetime.now(),
            discovery_url=seed_url,
            rows=catalog_rows,
            site_meta={
                "brand_label": brand_label or domain,
                "ground_truth_fill": sum(
                    1 for f in EXTRACTABLE_FIELDS
                    if not gt.is_field_blank(f)
                ),
                "catalog_fields_covered": sorted({r.field for r in catalog_rows}),
            },
        )
        return catalog, gt_result, method_results
    finally:
        await memo.close()


def save_catalog(catalog: SiteCatalog, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{catalog.domain.replace('.', '_')}_catalog.json"
    path.write_text(json.dumps(catalog.to_dict(), indent=2, ensure_ascii=False))
    return path
