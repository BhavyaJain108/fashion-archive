"""The lifecycle: scope → plan → calibrate → promote → monitor (spec §4.3b, §4.6)."""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.archive.connectors import get_connector
from backend.archive.connectors.base import ChannelBlocked, ChannelBusy, SkipProduct
from backend.archive.domain.brand import Brand, PlanAttempt, TransportLevel
from backend.archive.domain.product import (
    E0005_FIELDS,
    ProductRecord,
    ProductRef,
    is_worth_chasing,
)
from backend.archive.domain.recipe import RecipeBook
from backend.archive.evidence import SearchLog
from backend.archive.finder import apply_recipes
from backend.archive.fingerprint import probe
from backend.archive.planner import compose_plan
from backend.archive.store.catalog import Catalog
from backend.archive.verify import assess, field_fill_rates
from backend.archive.version import extraction_version

_EXIT = {"ok": 0, "degraded": 1, "failed": 2}


def select_delta(refs: list[ProductRef], hints: dict[str, str]) -> list[ProductRef]:
    return [
        r
        for r in refs
        if r.url not in hints or r.change_hint is None or r.change_hint != hints[r.url]
    ]


def run_brand(
    brand: Brand,
    catalog: Catalog,
    transport,
    mode: str = "delta",
    sample_size: int = 5,
    locks_dir: Path = Path("locks"),
    log_dir: Path = Path("logs/runs"),
    prober=probe,
    composer=compose_plan,
    connector_factory=get_connector,
    image_store=None,
    image_product_budget: int | None = None,
    browser: bool = False,
    browser_transport_factory=None,
    field_finder=None,
    max_products: int | None = None,
    learn_budget: int = 10,
    version=extraction_version,
    time_budget: float | None = None,
    clock=time.monotonic,
) -> int:
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock = locks_dir / f"{brand.domain}.lock"
    if not _take_lock(lock):
        return 0  # a live run holds it; overlap is a skip, not an alarm (spec §4.6)

    work_transport = transport  # may be swapped for a browser transport below; closed in finally

    run_id = catalog.open_run(brand.domain, mode)
    log_path = log_dir / brand.domain / f"{run_id}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(event: str, **kw) -> None:
        with log_path.open("a") as f:
            f.write(
                json.dumps({"t": datetime.now(timezone.utc).isoformat(), "event": event, **kw})
                + "\n"
            )

    def fail_plan(plan, reason: str) -> int:
        plan.tried.append(
            PlanAttempt(
                composition=plan.composition,
                failed_at=datetime.now(timezone.utc).isoformat(),
                reason=reason,
            )
        )
        plan.stale = True
        catalog.save_plan(plan)
        catalog.set_brand_state(brand.domain, "needs_attention")
        catalog.finalize_run(run_id, 1, None)
        log("plan-failed", reason=reason, composition=plan.composition)
        return 1

    try:
        plan = catalog.load_plan(brand.domain)
        # needs_attention and gated verdicts are never trusted from cache: the site may
        # open up, or the system may have grown a new lane since the plan was written.
        if plan is None or plan.stale or plan.status in ("needs_attention", "skip_gated"):
            cap = prober(brand.domain, transport)
            plan = composer(cap, tried=plan.tried if plan else [], browser=browser)
            catalog.save_plan(plan)
            catalog.set_brand_state(brand.domain, "scoped")
            log("planned", composition=plan.composition, status=plan.status)

        if plan.status == "skip_gated":
            catalog.set_brand_state(brand.domain, "gated")
            catalog.finalize_run(run_id, 0, None)
            log("skipped-gated")
            return 0
        if plan.status == "needs_attention":
            catalog.set_brand_state(brand.domain, "needs_attention")
            catalog.finalize_run(run_id, 1, None)
            log("needs-attention", tried=[a.composition for a in plan.tried])
            return 1

        # Fingerprinting always uses cheap HTTP; the actual scrape uses the plan's transport —
        # a browser only when the plan escalated to T2 (and a factory was provided).
        if plan.transport == TransportLevel.T2:
            if browser_transport_factory is None:
                return fail_plan(plan, "plan needs browser transport but none available")
            work_transport = browser_transport_factory()
            # The cheap HTTP probe skips its deep steps on a blocked site, so a T2 plan
            # arrives without the facts those steps produce. Ask again through the
            # browser, which can actually read the pages. outlw.xyz keeps its 140
            # products under /assets/, and without that prefix discovery found none.
            if plan.product_url_prefix is None:
                cap = prober(brand.domain, work_transport)
                if cap.product_url_prefix:
                    plan.product_url_prefix = cap.product_url_prefix
                    plan.sitemap_url = cap.sitemap_url or plan.sitemap_url
                    catalog.save_plan(plan)
                    log("relearned-through-browser", prefix=cap.product_url_prefix)

        # The cap reaches discovery too: The Outnet's sitemap index fans out to
        # 80,048 URLs and walking all of it timed the run out before it started.
        connector = connector_factory(plan, limit=max_products)
        try:
            refs = connector.discover(brand, work_transport)
        except ChannelBusy as e:
            # Rate limiting says nothing about the brand, so the plan is left alone.
            catalog.finalize_run(run_id, 1, None)
            log("channel-busy", reason=str(e))
            return 1
        except ChannelBlocked as e:
            return fail_plan(plan, f"discover blocked: {e}")
        log("discovered", refs=len(refs))
        # A cap keeps a 80,000-product catalogue from turning a health check into a
        # week-long run. It scopes the whole run, so change detection stays consistent.
        if max_products is not None and len(refs) > max_products:
            log("capped", found=len(refs), kept=max_products)
            refs = refs[:max_products]

        calibrating = catalog.get_brand_state(brand.domain) != "active"
        # The sample tells the finder which fields this channel never provides. An
        # already-active brand with no rules yet still pays for one, or a brand
        # promoted before the finder existed could never learn any (xsai.vision).
        wants_finder = field_finder is not None and catalog.load_recipe_book(brand.domain) is None
        sample_records = []
        if calibrating or wants_finder:
            if calibrating:
                catalog.set_brand_state(brand.domain, "calibrating")
            sample = refs[:sample_size]
            try:
                sample_records = [connector.fetch(r, work_transport) for r in sample]
            except Exception as e:  # calibration failure is cheap information, not damage
                return fail_plan(plan, f"calibration fetch failed: {e}")
            if calibrating:
                if sample and not all(r.product_title for r in sample_records):
                    return fail_plan(plan, "calibration: empty product_title in sample")
                catalog.set_brand_state(brand.domain, "active")
                log("calibrated", sample=len(sample))

        # A delta run leaves untouched products as they were, which is right when only
        # the shop has changed and wrong when we have: the Woo mapper stopped calling an
        # unpurchasable zero a price, and the rows it was written for kept their 0.00
        # because nothing on the shop's side had moved.
        current_version = version()
        last_version = catalog.extraction_version_for(brand.domain)
        if last_version and last_version != current_version and mode != "full":
            log("extraction-changed", was=last_version, now=current_version)
            mode = "full"

        hints = catalog.get_change_hints(brand.domain)
        first_run = not hints
        to_fetch = refs if (mode == "full" or first_run) else select_delta(refs, hints)
        log("selected", mode=mode, to_fetch=len(to_fetch), total=len(refs))

        book = catalog.load_recipe_book(brand.domain)
        recipes = book.recipes if book else []
        # Rules verified on a rendered page match nothing in static HTML, so a book
        # that needs rendering escalates this run's transport — the requirement was
        # measured during learning, not configured per brand.
        if recipes and book.rendered and plan.transport != TransportLevel.T2:
            if browser_transport_factory is None:
                recipes = []
                log("recipes-need-rendering", hint="re-run with --browser")
            else:
                if work_transport is not transport and hasattr(work_transport, "close"):
                    work_transport.close()
                work_transport = browser_transport_factory()
                log("escalated-to-rendered", fields=sorted(book.fields()))

        deadline = clock() + time_budget if time_budget else None
        unreached = 0
        records, errors = [], 0
        imaged_products = 0
        learned_this_run = 0
        finder_failures: list[str] = []
        # What this run actually looked at, so an empty field can be believed.
        search = SearchLog()
        # Which rule actually produced each value, so a narrow one shows up.
        rule_hits: dict[tuple[str, str], int] = {}
        # Worth chasing on a product page: a field the channel never provides, and any
        # field this brand already has a rule for — if that rule found nothing here,
        # this page lays the field out some other way and is worth a new strategy.
        learnable = (
            set(_missing_fields(sample_records)) | {r.field for r in recipes} | set(_ALWAYS_CHASE)
        )
        # The search record is not only a report: a field the model has already been
        # given a page for, and found nothing, is not worth paying for again every run.
        # Clearing this brand's field_evidence rows is what forces a fresh attempt.
        prior = catalog.load_evidence(brand.domain)
        exhausted = set()
        for f in learnable:
            asked, found = prior.get((f, "page_llm"), (0, 0))
            if asked and not found:
                exhausted.add(f)
        if exhausted:
            log("already-searched", fields=sorted(exhausted))
        learnable -= exhausted
        # Three failed attempts at a field ends the chase for this run: some products
        # genuinely have no material listed, and every attempt costs an API call.
        strikes: dict[str, int] = {}
        for index, r in enumerate(to_fetch):
            # One slow site must not hold up the fleet. Stopping early is reported as
            # missing coverage, not as a clean run over a smaller catalogue.
            if deadline is not None and clock() > deadline:
                unreached = len(to_fetch) - index
                log("time-budget-spent", budget=time_budget, unreached=unreached)
                break
            try:
                rec = connector.fetch(r, work_transport)
            except SkipProduct as e:
                log("skip-product", url=r.url, reason=str(e))
                continue
            except Exception as e:
                errors += 1
                log("fetch-error", url=r.url, error=str(e))
                continue
            search.searched(
                "channel", E0005_FIELDS, _filled_fields(rec)
            )  # the mapper read the whole payload, whatever it yielded
            html = None
            if recipes:
                before = _filled_fields(rec)
                html = _page_html(connector, r, work_transport)
                _fill_from_recipes(rec, html, recipes, rule_hits)
                covered = {x.field for x in recipes}
                search.searched("page_rules", covered, _filled_fields(rec) - before)
            # Keep learning. One rule per field is not enough: a storefront lays the
            # same field out differently across its catalogue, and the page the first
            # rule came from may simply not have had the others. Every product whose
            # gaps the existing strategies cannot fill is a chance to learn another
            # one, until the budget for this run runs out.
            gaps = [
                f
                for f in sorted(learnable)
                if _is_gap(rec, f) and strikes.get(f, 0) < _FIELD_STRIKES
            ]
            if gaps and field_finder is not None and learned_this_run < learn_budget:
                learned_this_run += 1
                failures_before = len(finder_failures)
                extra = _learn_book(
                    field_finder,
                    brand,
                    r.url,
                    gaps,
                    work_transport,
                    browser_transport_factory if plan.transport != TransportLevel.T2 else None,
                    log,
                    finder_failures,
                )
                fresh = [x for x in (extra.recipes if extra else []) if x.field in gaps]
                won = {x.field for x in fresh}
                # A call that never reached the model is not a search. Recording one
                # as evidence would turn an outage into "the brand does not publish
                # this" — the exact false confidence this record exists to prevent.
                if len(finder_failures) == failures_before:
                    search.searched("page_llm", gaps, won)
                    if extra is not None and extra.rendered:
                        search.searched("page_rendered", gaps, won)
                for f in gaps:
                    if f not in won:
                        strikes[f] = strikes.get(f, 0) + 1
                if fresh:
                    recipes = recipes + fresh
                    book = book or RecipeBook(
                        domain=brand.domain,
                        learned_at=datetime.now(timezone.utc).isoformat(),
                        learned_from_url=r.url,
                    )
                    book.recipes = recipes
                    if extra is not None and extra.rendered:
                        book.rendered = True
                    catalog.save_recipe_book(book)
                    log("finder-added", url=r.url, fields=sorted({x.field for x in fresh}))
                    _fill_from_recipes(
                        rec, html or _page_html(connector, r, work_transport), fresh, rule_hits
                    )
            # The channel does not always name the brand, but we always know it: it is
            # the site we chose to scrape. wiacollections stored 190 products with an
            # empty brand while the answer was in the brand list all along.
            if not rec.brand:
                rec.brand = brand.display_name or brand.domain
            _align_sizes(rec, log)
            records.append(rec)
            appended = catalog.record_product(brand.domain, run_id, rec, r.change_hint)
            within_budget = image_product_budget is None or imaged_products < image_product_budget
            images = rec.image_list()
            if appended and image_store is not None and images and within_budget:
                pid = catalog.product_id_for(brand.domain, rec.itemurl)
                n = image_store.archive(work_transport, catalog, pid, brand.domain, images)
                imaged_products += 1
                if n:
                    log("images-archived", url=rec.itemurl, count=n)

        # Some faults are only visible across a whole catalogue: staud.clothing fills
        # Shopify's vendor field with 41 campaign names, thesupermade with one SKU per
        # product. Neither is a brand, and neither can be spotted from a single row.
        from backend.archive.validate import brand_name_for, check_brand

        brand_names = [str(r.brand) for r in records if r.brand]
        problem = check_brand(brand_names) if brand_names else None
        if problem:
            correct = brand_name_for(brand.domain, brand_names, brand.display_name)
            n = catalog.rewrite_field(brand.domain, "brand", correct)
            log("brand-field-repaired", reason=problem, name=correct, applied_to=n)

        # untouched (unchanged) products still count as seen this run
        touched = {r.itemurl for r in records}
        catalog.mark_seen(
            brand.domain, run_id, [r.url for r in refs if r.url not in touched and r.url in hints]
        )

        if field_finder is not None and learned_this_run >= learn_budget:
            log("learn-budget-spent", budget=learn_budget)
        # A field finder that could not run is a silent quality collapse: the run
        # stores every product with the same fields empty and still exits 0. Live on
        # 2026-08-30, every psylos1 call returned "credit balance is too low" and its
        # size fill went from 98% to nothing without a word.
        rules_added = bool(recipes) and learned_this_run > 0
        if finder_failures and not rules_added:
            log("finder-unavailable", attempts=len(finder_failures), last=finder_failures[-1])

        if rule_hits and book is not None:
            for recipe in book.recipes:
                recipe.hits = rule_hits.get((recipe.field, recipe.expression), 0)
            catalog.save_recipe_book(book)

        catalog.set_extraction_version(brand.domain, current_version)
        catalog.record_evidence(brand.domain, run_id, search.rows())
        log("evidence-recorded", entries=len(search))

        coverage = assess(
            len(refs) - unreached, {connector.kind: len(refs)}, field_fill_rates(records)
        )
        if finder_failures and not rules_added and coverage.verdict == "ok":
            coverage.verdict = "degraded"
            coverage.reasons.append(f"field finder unavailable: {finder_failures[-1][:120]}")
        exit_status = _EXIT[coverage.verdict]
        catalog.set_brand_state(brand.domain, "active" if exit_status == 0 else "degraded")
        catalog.finalize_run(run_id, exit_status, coverage)
        log("finalized", verdict=coverage.verdict, errors=errors, extracted=len(records))
        return exit_status
    except Exception as e:  # containment: one hostile site must never kill the fleet
        catalog.set_brand_state(brand.domain, "unreachable")
        catalog.finalize_run(run_id, 2, None)
        log("run-crashed", error=f"{type(e).__name__}: {e}")
        return 2
    finally:
        if work_transport is not transport and hasattr(work_transport, "close"):
            work_transport.close()  # tear down a browser we launched for this brand
        lock.unlink(missing_ok=True)


# Failed attempts at one field before a run stops asking about it.
_FIELD_STRIKES = 3


def _learn_book(field_finder, brand, url, missing, transport, browser_factory, log, failures=None):
    """Ask for rules for one product page: static first, then rendered.

    A page can serve a complete-looking record over HTTP and still keep the missing
    field in a client-side store — theoutnet.com renders its sizes from a Remix
    payload with numeric keys — so a page that yields nothing static is worth one
    rendered attempt before moving on to the next product.
    """
    book = _learn(field_finder, brand, url, missing, transport, log, failures)
    if book is not None and book.recipes:
        return book
    if browser_factory is None:
        return book
    rendered = browser_factory()
    try:
        log("finder-retry-rendered", url=url)
        second = _learn(field_finder, brand, url, missing, rendered, log, failures)
    finally:
        if hasattr(rendered, "close"):
            rendered.close()
    if second is not None and second.recipes:
        second.rendered = True
        return second
    return book or second


def _learn(field_finder, brand, url, missing, transport, log, failures=None):
    """One finder call, contained: a failure here must never end the run."""
    try:
        return field_finder(brand.domain, url, missing, transport)
    except Exception as e:
        log("finder-failed", error=f"{type(e).__name__}: {e}")
        if failures is not None:
            failures.append(f"{type(e).__name__}: {e}")
        return None


def _take_lock(lock: Path) -> bool:
    """Claim the brand's lock, breaking one whose owner process is gone.

    A killed run used to leave a lock behind forever, and every later run of that
    brand exited 0 with no run row and no message — the brand just stopped updating
    and nothing said so. The lock now names its owner so a dead one can be cleared.
    """
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            if not _owner_alive(lock):
                lock.unlink(missing_ok=True)
                continue
            return False
    return False


def _owner_alive(lock: Path) -> bool:
    try:
        pid = int(lock.read_text().strip())
    except (OSError, ValueError):
        return False  # pre-pid or unreadable lock: treat as abandoned
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # someone else's process, but alive
    return True


# E0005 fields worth learning a rule for when the free channels leave them empty.
_LEARNABLE = (
    "size_info",
    "size_availability",
    "color_info",
    "material_info",
    "description",
    "price",
    "product_code",
    # A shop always shows the clothes, so an empty image field is never the brand's
    # choice. psylos1.com publishes "image": null in its JSON-LD while its page carries
    # a full gallery, and 70 of 300 products were stored with no image at all.
    "main_image_url",
    "all_images",
)


# A field only becomes learnable when the channel provides it on NO sampled product,
# which is right for a field the channel never carries and wrong for one it carries
# unreliably. psylos1 publishes images for 77% of its products, so the sample always had
# some and the 70 products with none were never chased. A shop always shows the clothes,
# so a blank here is our bug whatever the rest of the catalogue looks like.
_ALWAYS_CHASE = ("main_image_url", "all_images")


def _missing_fields(records) -> list[str]:
    """Fields that are empty on every sampled product — i.e. the channel never provides them."""
    if not records:
        return []
    return [f for f in _LEARNABLE if all(not getattr(r, f, None) for r in records)]


def _is_gap(rec, field: str) -> bool:
    """Worth asking about on this product?"""
    return is_worth_chasing(rec, field)


def _filled_fields(rec) -> set[str]:
    return {f for f in E0005_FIELDS if getattr(rec, f, None) not in (None, "", [])}


def _align_sizes(rec, log) -> None:
    """E0005 stores size_availability as a list parallel to size_info.

    A learned availability rule that returns a different number of entries is
    describing something other than these sizes, so it is dropped rather than stored
    against the wrong ones.
    """
    if not rec.size_availability or not rec.size_info:
        return
    sizes = len([t for t in rec.size_info.split(",") if t.strip()])
    flags = len([t for t in rec.size_availability.split(",") if t.strip()])
    if sizes != flags:
        log("dropped-misaligned-sizes", url=rec.itemurl, sizes=sizes, flags=flags)
        rec.size_availability = None


def _fill_from_recipes(rec, html, recipes, hits: dict | None = None) -> None:
    """Run the brand's saved rules against this product page and fill blanks only.

    The record itself is the context: a value that is really the product's own title
    or description means the rule grabbed the wrong element (finder._echoes).
    """
    if not html:
        return
    context = {"product_title": rec.product_title, "description": rec.description}
    values = apply_recipes(html, recipes, context, hits)
    # Two fields reading one element is one of them being wrong. wiacollections.com
    # learned both a description rule and a material rule pointing at the same short
    # description, and the echo check could not see it: description was still empty
    # when the values were read, so there was nothing yet to echo.
    prose = values.get("description") or rec.description or ""
    for field, value in values.items():
        # A list field keeps the longer list. theoutnet.com's channel gives one image
        # per product; the learned gallery rule finds six, and skipping it because the
        # field was "already filled" left the rule learned and never applied.
        if field == "all_images" and rec.all_images:
            better = _coerce(field, value)
            if better and len(json.loads(better)) > len(rec.image_list()):
                rec.all_images = better
            continue
        # A short factual extract from the description is fine — "100%CO" is a real
        # material even though it appears there. A long span of it is the rule
        # having grabbed the description itself.
        if field != "description" and prose and value.strip() in prose and len(value) > 60:
            continue
        if getattr(rec, field, None):
            continue
        coerced = _coerce(field, value)
        if coerced is not None:
            setattr(rec, field, coerced)


_NUMBER = re.compile(r"\d[\d\s,]*(?:\.\d+)?")


def _coerce(field: str, value: str):
    if field == "all_images":
        urls = [u.strip() for u in value.split(",") if u.strip().startswith("http")]
        return json.dumps(urls) if len(urls) > 1 else None

    """A rule always returns page text; the field may not be text.

    xsai.vision's price sits in one element as "3 907 RUB 3 990 RUB" (sale, then
    original). Writing that string into a float field produced a record that looked
    fine and serialised to nonsense, so a value that will not convert is dropped.
    """
    annotation = str(ProductRecord.model_fields[field].annotation)
    if "float" in annotation:
        m = _NUMBER.search(value)
        if not m:
            return None
        try:
            return float(m.group().replace(" ", "").replace(",", ""))
        except ValueError:
            return None
    if "bool" in annotation:
        return None  # no honest reading of arbitrary text as a stock flag
    return value


def _page_html(connector, ref, transport) -> str | None:
    """Reuse the page the connector already fetched where possible; else fetch once."""
    cached = getattr(connector, "last_html", None)
    if cached:
        return cached
    try:
        resp = transport.get(ref.url)
        return resp.text if resp.status_code == 200 else None
    except Exception:
        return None
