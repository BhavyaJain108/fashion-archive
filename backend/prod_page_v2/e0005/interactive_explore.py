"""
Discovery-time interactive exploration.

Goal: feed the discovery LLM the content behind every plausible clickable
trigger on a product page, so it can propose `accordion_read` recipes for
fields like specifications, delivery, size_info that don't live in the
static DOM.

Two capture paths per trigger:

1. **`aria-controls` direct read** — if the trigger declares an
   `aria-controls="X"` target, the controlled element's inner text IS the
   panel content; reading it doesn't require a click. This covers inline
   accordions (e.g. McQueen "View details" / "Product care") whose panel
   markup is already mounted and just visibility-toggled.

2. **Click + aria diff** — for triggers with no aria-controls target,
   snapshot `body.aria_snapshot()` pre-click, click, wait briefly, snapshot
   post-click, return the set-difference. Covers radix-style dialogs (size
   selectors, search, menu) whose panel markup is mounted on click.

Trigger scan is structural patterns (`[aria-expanded]`, `[aria-controls]`,
`[role=tab]`, `details>summary`, `[class*=accordion]`) PLUS a small set of
label-keyword matches (`composition`, `material`, `details`,
`specifications`, `shipping`, `delivery`, `size`, `care`, `fit`,
`returns`, `sustainability`) for accordion buttons that carry neither
aria nor accordion classnames.

Anchor elements (`<a href>`) with hrefs that navigate off the current
page are excluded — they're not accordions, they're page navigations,
and clicking them blows away page state.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .memo import PageMemo


_MAX_TRIGGERS = 30
_PER_CLICK_TIMEOUT_MS = 800
_POST_CLICK_WAIT_MS = 250
_MAX_REVEALED_CHARS = 3000


# Accordion-typical label keywords. Used by the trigger scan as a fallback
# heuristic when structural attributes don't surface a candidate (some sites
# use plain styled buttons without aria-expanded). User explicitly OK'd this
# as a discovery-only heuristic — recipes catalog the resulting selector,
# never the matched text.
_LABEL_KEYWORDS = [
    "composition", "material", "fabric", "details", "description",
    "specifications", "shipping", "delivery", "size", "care", "fit",
    "returns", "sustainability", "size guide", "size & fit", "size chart",
]


# Trigger scan JS. Returns one record per candidate:
#   {selector, label, source, aria_controls_id?}
# - Skips elements with aria-expanded="true" (already open).
# - Skips <a href> with off-page hrefs (those are navigations, not reveals).
# - Builds the most stable unique selector available.
_TRIGGER_SCAN_JS = r"""
(LABELS) => {
  const out = [];
  const seen = new Set();

  const isVisible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;
    const s = window.getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none';
  };

  const isAnchorNavigation = (el) => {
    if (el.tagName.toLowerCase() !== 'a') return false;
    const href = el.getAttribute('href') || '';
    if (!href) return false;
    if (href.startsWith('#')) return false;          // in-page anchor, OK
    if (href.startsWith('javascript:')) return false; // JS handler, OK
    // Anything else is a navigation away from current page → not an accordion.
    return true;
  };

  const buildSelector = (el) => {
    for (const a of ['data-test','data-testid','data-component','data-region']) {
      const v = el.getAttribute(a);
      if (v && document.querySelectorAll(`[${a}="${CSS.escape(v)}"]`).length === 1)
        return `[${a}="${v}"]`;
    }
    if (el.id && document.querySelectorAll(`#${CSS.escape(el.id)}`).length === 1)
      return `#${CSS.escape(el.id)}`;
    const ac = el.getAttribute('aria-controls');
    if (ac && document.querySelectorAll(`[aria-controls="${ac}"]`).length === 1)
      return `[aria-controls="${ac}"]`;
    const path = []; let cur = el;
    while (cur && cur.nodeType === 1 && cur.tagName.toLowerCase() !== 'body') {
      const tag = cur.tagName.toLowerCase();
      const par = cur.parentElement; if (!par) break;
      const sibs = Array.from(par.children).filter(c => c.tagName === cur.tagName);
      path.unshift(`${tag}:nth-of-type(${sibs.indexOf(cur)+1})`);
      cur = par;
    }
    return path.join(' > ');
  };

  const consider = (el, why) => {
    if (!el || !isVisible(el) || seen.has(el)) return;
    if (el.getAttribute('aria-expanded') === 'true') return;
    if (isAnchorNavigation(el)) return;
    seen.add(el);
    const sel = buildSelector(el); if (!sel) return;
    const label = ((el.innerText || el.getAttribute('aria-label') || '').trim() || '').slice(0,80);
    out.push({ selector: sel, label, source: why, aria_controls: el.getAttribute('aria-controls') || null });
  };

  document.querySelectorAll('[aria-expanded]').forEach(e => consider(e,'aria-expanded'));
  document.querySelectorAll('[aria-controls]').forEach(e => consider(e,'aria-controls'));
  document.querySelectorAll('[role="tab"]').forEach(e => consider(e,'role=tab'));
  document.querySelectorAll('details > summary').forEach(e => consider(e,'details-summary'));
  document.querySelectorAll('[class*="accordion" i],[class*="toggle" i],[class*="expander" i]').forEach(e => {
    const tag = e.tagName.toLowerCase();
    if (tag==='button'||e.getAttribute('role')==='button'||e.hasAttribute('aria-expanded')||tag==='summary')
      consider(e,'class-accordion');
  });
  const clickable = document.querySelectorAll('button, summary, [role="button"]');
  clickable.forEach(e => {
    const t = (e.innerText || '').trim().toLowerCase();
    if (!t || t.length > 60) return;
    for (const kw of LABELS) {
      if (t.includes(kw)) { consider(e,'label-kw:'+kw); break; }
    }
  });
  return out;
}
"""


async def _aria_snapshot(page) -> str:
    try:
        return await page.locator("body").aria_snapshot()
    except Exception:
        return ""


def _aria_diff(pre: str, post: str) -> str:
    pre_lines = set(l.strip() for l in pre.split("\n") if l.strip())
    new = [l for l in post.split("\n") if l.strip() and l.strip() not in pre_lines]
    return "\n".join(new)


async def _dismiss(page) -> None:
    """Best-effort soft reset between triggers."""
    for _ in range(2):
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(80)
        except Exception:
            break
    try:
        await page.mouse.click(1, 1)
        await page.wait_for_timeout(80)
    except Exception:
        pass


async def explore_clickables(memo: PageMemo, max_triggers: int = _MAX_TRIGGERS) -> List[Dict[str, Any]]:
    """Click/read every plausible trigger on the rendered page.

    For each trigger, two capture paths are tried in order:
      - If the trigger has `aria-controls="X"`, the controlled element's
        inner text is read directly (no click needed). This is the inline-
        accordion case.
      - Otherwise (or if the aria-controls read returned empty), click the
        trigger and aria-diff pre/post. This is the mount-on-click dialog
        case.

    Revealed content is stored on `memo._accordion_text` keyed by the
    trigger's stable selector, so the discovery prompt's revealed-panels
    section automatically surfaces it. Returns a report list for logging.
    """
    await memo._ensure_rendered()
    page = memo._page
    if page is None:
        return []

    try:
        triggers = await page.evaluate(_TRIGGER_SCAN_JS, _LABEL_KEYWORDS)
    except Exception as e:
        print(f"[explore_clickables] trigger scan failed: {e!r}")
        return []
    if not isinstance(triggers, list):
        return []

    # De-dupe by selector, cap.
    by_sel: Dict[str, Dict[str, Any]] = {}
    for t in triggers:
        if isinstance(t, dict) and t.get("selector") and t["selector"] not in by_sel:
            by_sel[t["selector"]] = t
    unique = list(by_sel.values())[:max_triggers]

    report: List[Dict[str, Any]] = []
    base_url = page.url

    for t in unique:
        sel = t["selector"]
        label = t.get("label", "")
        source = t.get("source", "")
        aria_ctl = t.get("aria_controls")
        revealed = ""
        capture_method = ""

        # Path 1: aria-controls direct read (no click needed for inline panels).
        if aria_ctl:
            try:
                ctl_loc = page.locator(f"#{aria_ctl}").first
                if await ctl_loc.count() > 0:
                    text = (await ctl_loc.inner_text(timeout=1500)).strip()
                    if len(text) >= 30:
                        revealed = text[:_MAX_REVEALED_CHARS]
                        capture_method = "aria-controls"
            except Exception:
                pass

        # Path 2: click + aria diff.
        if not revealed:
            try:
                trig = page.locator(sel).first
                if await trig.count() == 0:
                    continue
                if not await trig.is_visible():
                    continue
                pre = await _aria_snapshot(page)
                try:
                    await trig.scroll_into_view_if_needed(timeout=500)
                except Exception:
                    pass
                await trig.click(timeout=_PER_CLICK_TIMEOUT_MS)
                await page.wait_for_timeout(_POST_CLICK_WAIT_MS)
                try:
                    await page.wait_for_load_state("networkidle", timeout=1500)
                except Exception:
                    pass
                # If the click navigated away, restore and skip.
                if page.url != base_url:
                    try:
                        await page.go_back(timeout=5000, wait_until="domcontentloaded")
                    except Exception:
                        pass
                    continue
                post = await _aria_snapshot(page)
                text = _aria_diff(pre, post)
                if len(text) >= 30:
                    revealed = text[:_MAX_REVEALED_CHARS]
                    capture_method = "click-diff"
            except Exception:
                pass
            finally:
                await _dismiss(page)

        if revealed:
            memo._accordion_text[sel] = revealed
        report.append({
            "selector": sel, "label": label, "source": source,
            "capture": capture_method, "revealed_chars": len(revealed),
        })

    # Refresh DOM once at the end so any post-click DOM mutations are
    # visible to dom_selector proposals. Reset baseline state first.
    await _dismiss(page)
    await memo.refresh_post_interaction()
    return report
