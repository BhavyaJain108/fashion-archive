import os
import pytest

from backend.archive.connectors.base import ChannelBlocked
from backend.archive.domain.brand import Brand, Capability, TransportLevel
from backend.archive.domain.product import ProductRecord, ProductRef
from backend.archive.planner import compose_plan
from backend.archive.runner.run import run_brand, select_delta
from backend.archive.store.catalog import Catalog

BRAND = Brand(domain="kuurth.com", homepage_url="https://kuurth.com")
OPEN_CAP = Capability(
    domain="kuurth.com", platform="shopify", transport=TransportLevel.T0, bulk_json=True
)


def ref(n: str, hint: str) -> ProductRef:
    return ProductRef(
        url=f"https://kuurth.com/products/{n}",
        change_hint=hint,
        payload={"handle": n, "title": n.title(), "variants": [], "images": [], "tags": []},
    )


class FakeConnector:
    kind = "shopify"

    def __init__(self, refs):
        self.refs = refs
        self.fetched: list[str] = []

    def discover(self, brand, transport):
        return self.refs

    def fetch(self, r, transport):
        self.fetched.append(r.url)
        return ProductRecord(itemurl=r.url, product_title=r.payload["title"])


@pytest.mark.unit
def test_select_delta_keeps_new_and_changed_only():
    refs = [ref("a", "h1"), ref("b", "h2"), ref("c", "h3")]
    hints = {refs[0].url: "h1", refs[1].url: "OLD"}
    assert [r.url for r in select_delta(refs, hints)] == [refs[1].url, refs[2].url]


@pytest.fixture()
def env(tmp_path):
    cat = Catalog(tmp_path / "catalog.db")
    cat.upsert_brand(BRAND)
    return cat, tmp_path / "locks", tmp_path / "logs"


@pytest.mark.unit
def test_first_run_calibrates_promotes_and_verifies(env):
    cat, locks, logs = env
    conn = FakeConnector([ref("a", "h1"), ref("b", "h2")])
    code = run_brand(
        BRAND,
        cat,
        transport=None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: conn,
    )
    assert code == 0
    assert cat.get_brand_state("kuurth.com") == "active"
    assert cat.latest_run("kuurth.com")["exit_status"] == 0
    assert len(cat.current_products("kuurth.com")) == 2


@pytest.mark.unit
def test_delta_run_fetches_only_changed(env):
    cat, locks, logs = env
    conn = FakeConnector([ref("a", "h1"), ref("b", "h2")])
    kwargs = dict(
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: conn,
    )
    run_brand(BRAND, cat, None, mode="full", **kwargs)
    conn.fetched.clear()
    conn.refs = [ref("a", "h1"), ref("b", "h2-NEW")]
    code = run_brand(BRAND, cat, None, mode="delta", **kwargs)
    assert code == 0
    assert conn.fetched == ["https://kuurth.com/products/b"]  # unchanged 'a' untouched


@pytest.mark.unit
def test_blocked_channel_records_attempt_and_marks_stale(env):
    cat, locks, logs = env

    class Blocked(FakeConnector):
        def discover(self, brand, transport):
            raise ChannelBlocked("429")

    code = run_brand(
        BRAND,
        cat,
        None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: Blocked([]),
    )
    assert code == 1
    plan = cat.load_plan("kuurth.com")
    assert plan.stale is True and len(plan.tried) == 1
    assert cat.get_brand_state("kuurth.com") == "needs_attention"


@pytest.mark.unit
def test_image_product_budget_caps_archived_products(env):
    """Sample policy: only the first N products per run get their photos archived."""
    cat, locks, logs = env

    class ImagedConnector(FakeConnector):
        def fetch(self, r, transport):
            rec = super().fetch(r, transport)
            rec.all_images = f'["{r.url}/img.jpg"]'
            return rec

    class CountingStore:
        calls = 0

        def archive(self, transport, catalog, pid, domain, urls):
            CountingStore.calls += 1
            return 0

    code = run_brand(
        BRAND,
        cat,
        None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: ImagedConnector(
            [ref("a", "h1"), ref("b", "h2"), ref("c", "h3")]
        ),
        image_store=CountingStore(),
        image_product_budget=2,
    )
    assert code == 0 and CountingStore.calls == 2


@pytest.mark.unit
def test_needs_attention_plans_are_reprobed_every_run(env):
    """A needs_attention verdict must never be cached: the site may open up OR the
    system may grow a new lane (exactly what happened when M2a shipped)."""
    from backend.archive.domain.brand import (
        ChangeSignal,
        DiscoveryChannel,
        FetchChannel,
        ScrapePlan,
    )

    cat, locks, logs = env
    stuck = ScrapePlan(
        domain="kuurth.com",
        transport=TransportLevel.T0,
        discovery=DiscoveryChannel.BULK_JSON,
        fetch=FetchChannel.PLATFORM_JSON,
        change_signal=ChangeSignal.NONE,
        status="needs_attention",
        fingerprinted_at="2026-08-28T00:00:00+00:00",
    )
    cat.save_plan(stuck)
    conn = FakeConnector([ref("a", "h1")])
    code = run_brand(
        BRAND,
        cat,
        None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,  # the world changed: brand is open now
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: conn,
    )
    assert code == 0
    assert cat.load_plan("kuurth.com").status == "ready"


@pytest.mark.unit
def test_network_error_during_probe_is_contained(env):
    """Regression: vancleefarpels.com read-timeout crashed the whole fleet run (2026-08-29).

    Any uncaught exception inside a brand's run must finalize THAT run as failed
    and return — never propagate and kill the remaining brands.
    """

    def timing_out_prober(domain, transport):
        raise TimeoutError("The read operation timed out")

    cat, locks, logs = env
    code = run_brand(
        BRAND,
        cat,
        None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=timing_out_prober,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector([]),
    )
    assert code == 2
    assert cat.get_brand_state("kuurth.com") == "unreachable"
    run = cat.latest_run("kuurth.com")
    assert run["exit_status"] == 2 and run["finished_at"] is not None
    assert not (locks / "kuurth.com.lock").exists()  # lock released for the next run


@pytest.mark.unit
def test_t2_plan_uses_browser_transport_factory_and_closes_it(env):
    """A T2 plan routes discover/fetch through the browser transport, then closes it."""
    from backend.archive.domain.brand import Capability

    cat, locks, logs = env
    challenged_cap = Capability(
        domain="kuurth.com",
        platform="shopify",
        transport=TransportLevel.T2,
        challenged=True,
        sitemap_url="https://kuurth.com/sitemap.xml",
    )
    used = {}

    class FakeBrowser:
        closed = False

        def close(self):
            FakeBrowser.closed = True

    def factory():
        used["built"] = True
        return FakeBrowser()

    class RecordingConnector(FakeConnector):
        def discover(self, brand, transport):
            used["discover_transport"] = transport
            return self.refs

    code = run_brand(
        BRAND,
        cat,
        transport="HTTP-SENTINEL",
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: challenged_cap,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: RecordingConnector([ref("a", "h1")]),
        browser=True,
        browser_transport_factory=factory,
    )
    assert code == 0
    assert used["built"] is True
    assert isinstance(used["discover_transport"], FakeBrowser)  # not the HTTP sentinel
    assert FakeBrowser.closed is True


@pytest.mark.unit
def test_t2_plan_without_factory_fails_gracefully(env):
    from backend.archive.domain.brand import Capability

    cat, locks, logs = env
    challenged_cap = Capability(
        domain="kuurth.com", platform="shopify", transport=TransportLevel.T2, challenged=True
    )
    code = run_brand(
        BRAND,
        cat,
        transport=None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: challenged_cap,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector([]),
        browser=True,
        browser_transport_factory=None,
    )
    assert code == 1  # fail_plan, not a crash
    assert cat.get_brand_state("kuurth.com") == "needs_attention"


@pytest.mark.unit
def test_held_lock_skips_without_a_run_row(env):
    cat, locks, logs = env
    locks.mkdir(parents=True)
    (locks / "kuurth.com.lock").write_text(str(os.getpid()))  # a live owner
    code = run_brand(
        BRAND,
        cat,
        None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector([]),
    )
    assert code == 0 and cat.latest_run("kuurth.com") is None


@pytest.mark.unit
def test_finder_learns_once_then_every_product_uses_the_saved_rules(env):
    """One LLM call per brand; all later products are filled for free."""
    from backend.archive.domain.recipe import Recipe, RecipeBook

    cat, locks, logs = env
    calls = {"n": 0}
    PAGE = '<html><body><ul class="sz"><li>EU 39</li><li>EU 40</li></ul></body></html>'

    class PageConnector(FakeConnector):
        last_html = PAGE  # the page it just fetched

    def finder(domain, url, missing, page_transport=None):
        calls["n"] += 1
        assert "size_info" in missing  # only asked about fields the channel left empty
        return RecipeBook(
            domain=domain,
            learned_at="2026-08-30T00:00:00+00:00",
            learned_from_url=url,
            recipes=[Recipe(field="size_info", kind="css_all_text", expression="ul.sz li")],
        )

    kwargs = dict(
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: PageConnector(
            [ref("a", "h1"), ref("b", "h2")]
        ),
        field_finder=finder,
    )
    assert run_brand(BRAND, cat, None, mode="full", **kwargs) == 0
    prods = cat.current_products("kuurth.com")
    assert all(p["size_info"] == "EU 39, EU 40" for p in prods)
    first_run_calls = calls["n"]

    # a second run reuses the saved rules: no product needs a size rule learned again
    run_brand(BRAND, cat, None, mode="full", **kwargs)
    assert calls["n"] == first_run_calls


@pytest.mark.unit
def test_finder_is_never_called_when_the_channel_fills_everything(env):
    cat, locks, logs = env

    class Complete(FakeConnector):
        def fetch(self, r, transport):
            rec = super().fetch(r, transport)
            rec.size_info, rec.color_info, rec.material_info = "S, M", "Black", "Wool"
            rec.description, rec.price, rec.product_code = "d", 10.0, "c"
            rec.size_availability = "true, false"
            rec.main_image_url = "https://cdn.x/a.jpg"
            rec.all_images = '["https://cdn.x/a.jpg", "https://cdn.x/b.jpg"]'
            return rec

    def boom(domain, url, missing, page_transport=None):
        raise AssertionError("finder must not run when nothing is missing")

    assert (
        run_brand(
            BRAND,
            cat,
            None,
            mode="full",
            locks_dir=locks,
            log_dir=logs,
            prober=lambda d, t: OPEN_CAP,
            composer=compose_plan,
            connector_factory=lambda plan, sitemap_url=None, limit=None: Complete([ref("a", "h1")]),
            field_finder=boom,
        )
        == 0
    )


@pytest.mark.unit
def test_a_finder_that_cannot_run_degrades_the_run_but_still_stores_products(env):
    """Live on 2026-08-30 every psylos1 call returned "credit balance is too low":
    its size fill went from 98% to nothing and the run still exited 0."""
    cat, locks, logs = env

    def broken(domain, url, missing, page_transport=None):
        raise RuntimeError("credit balance is too low")

    code = run_brand(
        BRAND,
        cat,
        None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector(
            [ref("a", "h1")]
        ),
        field_finder=broken,
    )
    assert code == 1  # degraded, not failed — the products are still there
    assert len(cat.current_products("kuurth.com")) == 1
    reasons = cat.latest_run("kuurth.com")
    assert reasons["exit_status"] == 1
    log_files = list((logs / "kuurth.com").glob("*.jsonl"))
    assert any("finder-unavailable" in f.read_text() for f in log_files)


@pytest.mark.unit
def test_max_products_caps_the_run(env):
    cat, locks, logs = env
    conn = FakeConnector([ref(x, f"h{x}") for x in "abcdefg"])
    code = run_brand(
        BRAND,
        cat,
        transport=None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: conn,
        max_products=3,
    )
    assert code == 0
    assert set(conn.fetched) == {ref(x, "").url for x in "abc"}
    assert len(cat.current_products("kuurth.com")) == 3


@pytest.mark.unit
def test_a_lock_left_by_a_dead_run_is_broken(env):
    cat, locks, logs = env
    locks.mkdir(parents=True, exist_ok=True)
    (locks / "kuurth.com.lock").write_text("999999")  # pid that cannot be running
    conn = FakeConnector([ref("a", "h1")])
    code = run_brand(
        BRAND,
        cat,
        transport=None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: conn,
    )
    assert code == 0
    assert len(cat.current_products("kuurth.com")) == 1


@pytest.mark.unit
def test_a_price_rule_returning_text_is_parsed_or_dropped():
    from backend.archive.runner.run import _coerce

    assert _coerce("price", "3 907 RUB 3 990 RUB") == 3907.0
    assert _coerce("price", "$1,299.50") == 1299.50
    assert _coerce("price", "sold out") is None
    assert _coerce("in_stock", "Add to cart") is None
    assert _coerce("size_info", "S, M, L") == "S, M, L"


@pytest.mark.unit
def test_an_already_active_brand_with_no_rules_still_learns_them(env):
    """A brand promoted before the finder existed must not be locked out of it."""
    from backend.archive.domain.recipe import Recipe, RecipeBook

    cat, locks, logs = env
    cat.set_brand_state("kuurth.com", "active")
    calls = []

    def finder(domain, url, missing, page_transport=None):
        calls.append((domain, missing))
        return RecipeBook(
            domain=domain,
            learned_at="2026-08-30T00:00:00+00:00",
            learned_from_url=url,
            recipes=[Recipe(field="size_info", kind="css_all_text", expression=".sz")],
        )

    run_brand(
        BRAND,
        cat,
        transport=None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector(
            [ref("a", "h1"), ref("b", "h2")]
        ),
        field_finder=finder,
    )
    assert calls  # already active, and it still learned
    assert "size_info" in calls[0][1]
    assert cat.load_recipe_book("kuurth.com") is not None


@pytest.mark.unit
def test_a_browser_run_reprobes_for_facts_the_http_probe_could_not_get(env):
    """outlw.xyz blocks plain HTTP, so its /assets/ product prefix is only visible
    once the browser is up. Discovery found 0 of 140 products without it."""
    from backend.archive.domain.brand import Capability

    cat, locks, logs = env
    blocked = Capability(
        domain="kuurth.com",
        transport=TransportLevel.T2,
        challenged=True,
        sitemap_url="https://kuurth.com/sitemap.xml",
    )
    through_browser = blocked.model_copy(update={"product_url_prefix": "/assets/"})
    probes: list[str] = []

    class FakeBrowser:
        def close(self):
            pass

    def prober(domain, transport):
        probes.append("browser" if isinstance(transport, FakeBrowser) else "http")
        return through_browser if isinstance(transport, FakeBrowser) else blocked

    run_brand(
        BRAND,
        cat,
        transport="HTTP-SENTINEL",
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=prober,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector(
            [ref("a", "h1")]
        ),
        browser=True,
        browser_transport_factory=FakeBrowser,
    )
    assert probes == ["http", "browser"]
    assert cat.load_plan("kuurth.com").product_url_prefix == "/assets/"


@pytest.mark.unit
def test_the_finder_reads_the_page_through_the_run_s_transport(env):
    """On a browser run the unrendered HTML holds nothing selectable."""
    from backend.archive.domain.brand import Capability

    cat, locks, logs = env
    seen = {}

    class FakeBrowser:
        def close(self):
            pass

    def finder(domain, url, missing, page_transport):
        seen["transport"] = page_transport
        return None

    run_brand(
        BRAND,
        cat,
        transport="HTTP-SENTINEL",
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: Capability(
            domain="kuurth.com",
            transport=TransportLevel.T2,
            challenged=True,
            product_url_prefix="/products/",
            sitemap_url="https://kuurth.com/sitemap.xml",
        ),
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector(
            [ref("a", "h1")]
        ),
        browser=True,
        browser_transport_factory=FakeBrowser,
        field_finder=finder,
    )
    assert isinstance(seen["transport"], FakeBrowser)


@pytest.mark.unit
def test_the_finder_retries_through_a_browser_when_static_html_yields_nothing(env):
    """theoutnet.com serves a complete-looking record over HTTP but renders its sizes
    from a client-side store, so nothing fails and the plan never escalates."""
    from backend.archive.domain.recipe import Recipe, RecipeBook

    cat, locks, logs = env
    transports = []

    class FakeBrowser:
        closed = False

        def close(self):
            FakeBrowser.closed = True

    def finder(domain, url, missing, page_transport):
        transports.append(page_transport)
        if not isinstance(page_transport, FakeBrowser):
            return RecipeBook(
                domain=domain,
                learned_at="2026-08-30T00:00:00+00:00",
                learned_from_url=url,
                recipes=[],  # verified nothing on the static page
            )
        return RecipeBook(
            domain=domain,
            learned_at="2026-08-30T00:00:00+00:00",
            learned_from_url=url,
            recipes=[Recipe(field="size_info", kind="css_all_text", expression="button.size")],
        )

    run_brand(
        BRAND,
        cat,
        transport="HTTP-SENTINEL",
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector(
            [ref("a", "h1")]
        ),
        field_finder=finder,
        browser_transport_factory=FakeBrowser,
    )
    assert len(transports) == 2  # static first, rendered second
    assert isinstance(transports[1], FakeBrowser)
    assert FakeBrowser.closed is True
    assert sorted(cat.load_recipe_book("kuurth.com").fields()) == ["size_info"]


@pytest.mark.unit
def test_a_rendered_recipe_book_escalates_the_run_to_a_browser(env):
    from backend.archive.domain.recipe import Recipe, RecipeBook

    cat, locks, logs = env
    cat.save_recipe_book(
        RecipeBook(
            domain="kuurth.com",
            learned_at="2026-08-30T00:00:00+00:00",
            learned_from_url="https://kuurth.com/products/a",
            recipes=[Recipe(field="size_info", kind="css_all_text", expression="button.size")],
            rendered=True,
        )
    )
    seen = {}

    class FakeBrowser:
        def get(self, url):
            raise AssertionError("not reached in this test")

        def close(self):
            seen["closed"] = True

    class RecordingConnector(FakeConnector):
        def fetch(self, r, transport):
            seen.setdefault("fetch_transports", []).append(transport)
            return super().fetch(r, transport)

    run_brand(
        BRAND,
        cat,
        transport="HTTP-SENTINEL",
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: RecordingConnector(
            [ref("a", "h1")]
        ),
        browser_transport_factory=FakeBrowser,
    )
    assert isinstance(seen["fetch_transports"][-1], FakeBrowser)
    assert seen["closed"] is True


@pytest.mark.unit
def test_rendered_rules_are_skipped_when_no_browser_is_available(env):
    """Applying them to static HTML would silently produce empty fields."""
    from backend.archive.domain.recipe import Recipe, RecipeBook

    cat, locks, logs = env
    cat.save_recipe_book(
        RecipeBook(
            domain="kuurth.com",
            learned_at="2026-08-30T00:00:00+00:00",
            learned_from_url="https://kuurth.com/products/a",
            recipes=[Recipe(field="size_info", kind="css_all_text", expression="button.size")],
            rendered=True,
        )
    )
    code = run_brand(
        BRAND,
        cat,
        transport="HTTP-SENTINEL",
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector(
            [ref("a", "h1")]
        ),
    )
    assert code == 0  # the run still delivers what the free channel gives
    log_text = (logs / "kuurth.com").glob("*.jsonl")
    assert any("recipes-need-rendering" in f.read_text() for f in log_text)


@pytest.mark.unit
def test_learning_continues_product_by_product_until_a_rule_holds(env):
    """One page is not enough: theoutnet.com's first product is a scarf, which has no
    sizes on it at all, and different products lay the same field out differently."""
    from backend.archive.domain.recipe import Recipe, RecipeBook

    cat, locks, logs = env
    tried: list[str] = []
    PAGE = '<html><body><ul class="sz"><li>S</li><li>M</li></ul></body></html>'

    class PageConnector(FakeConnector):
        last_html = PAGE

    def finder(domain, url, missing, page_transport=None):
        tried.append(url)
        recipes = (
            [Recipe(field="size_info", kind="css_all_text", expression="ul.sz li")]
            if url.endswith("/c")  # only the third product's page shows its sizes
            else []
        )
        return RecipeBook(
            domain=domain,
            learned_at="2026-08-30T00:00:00+00:00",
            learned_from_url=url,
            recipes=recipes,
        )

    run_brand(
        BRAND,
        cat,
        transport=None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: PageConnector(
            [ref(x, f"h{x}") for x in "abcde"]
        ),
        field_finder=finder,
    )
    assert [u[-1] for u in tried][:3] == ["a", "b", "c"]
    assert sorted(cat.load_recipe_book("kuurth.com").fields()) == ["size_info"]
    filled = [p for p in cat.current_products("kuurth.com") if p["size_info"]]
    assert len(filled) == 3  # c, d and e — a and b were stored before the rule existed



@pytest.mark.unit
def test_size_availability_is_dropped_when_it_does_not_match_the_sizes():
    """E0005 stores the two as parallel lists; a different length describes something
    other than these sizes."""
    from backend.archive.runner.run import _align_sizes

    logged = []
    rec = ProductRecord(
        itemurl="https://x.test/p",
        product_title="Tee",
        size_info="S, M, L",
        size_availability="In stock, Sold out",
    )
    _align_sizes(rec, lambda event, **kw: logged.append(event))
    assert rec.size_availability is None
    assert logged == ["dropped-misaligned-sizes"]

    aligned = ProductRecord(
        itemurl="https://x.test/p",
        product_title="Tee",
        size_info="S, M, L",
        size_availability="true, false, true",
    )
    _align_sizes(aligned, lambda event, **kw: logged.append(event))
    assert aligned.size_availability == "true, false, true"


@pytest.mark.unit
def test_a_field_that_is_just_the_description_again_is_not_filled():
    """wiacollections.com learned a description rule and a material rule pointing at
    the same element, so every product's material was its whole short description."""
    from backend.archive.domain.recipe import Recipe
    from backend.archive.runner.run import _fill_from_recipes

    html = (
        '<html><body><div class="short">Pink heavyweight T-shirt. Soft single jersey '
        "with a print on the front and back, made in Spain. Hand wash cold. "
        "Measurements: total long 76cm, chest 60cm.</div></body></html>"
    )
    rec = ProductRecord(itemurl="https://x.test/p", product_title="Pink heavyweight T-shirt")
    _fill_from_recipes(
        rec,
        html,
        [
            Recipe(field="description", kind="css_text", expression="div.short"),
            Recipe(field="material_info", kind="css_text", expression="div.short"),
        ],
    )
    assert rec.description  # the description rule is right
    assert rec.material_info is None  # the material rule is the same text again


@pytest.mark.unit
def test_a_slow_brand_stops_at_its_time_budget_and_says_so(env):
    """A fleet run must not be one hung site away from stalling."""
    cat, locks, logs = env
    ticks = iter([0, 1, 2, 100, 200, 300, 400])  # the clock jumps past the budget

    code = run_brand(
        BRAND,
        cat,
        transport=None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector(
            [ref(x, f"h{x}") for x in "abcdefghij"]
        ),
        time_budget=60,
        clock=lambda: next(ticks),
    )
    stored = cat.current_products("kuurth.com", live_only=False)
    assert 0 < len(stored) < 10  # the products it reached are kept
    # 2 of 10 is not a catalogue: the run reports the shortfall rather than
    # presenting a truncated scrape as a clean one
    assert code == 2
    assert cat.current_products("kuurth.com") == []
    log_files = list((logs / "kuurth.com").glob("*.jsonl"))
    assert any("time-budget-spent" in f.read_text() for f in log_files)


@pytest.mark.unit
def test_the_brand_is_filled_from_the_brand_we_chose_to_scrape(env):
    """A channel that never names the brand does not make the brand unknown."""
    cat, locks, logs = env
    run_brand(
        BRAND,
        cat,
        transport=None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector(
            [ref("a", "h1")]
        ),
    )
    assert cat.current_products("kuurth.com")[0]["brand"] == "kuurth.com"


@pytest.mark.unit
def test_a_busy_channel_does_not_rewrite_the_plan(env):
    """Rate limiting says nothing about a brand's shape."""
    from backend.archive.connectors.base import ChannelBusy

    cat, locks, logs = env

    class Busy(FakeConnector):
        def discover(self, brand, transport):
            raise ChannelBusy("429")

    kwargs = dict(
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: Busy([]),
    )
    run_brand(BRAND, cat, None, mode="full", **kwargs)  # establishes the plan, then 429s
    plan = cat.load_plan("kuurth.com")
    assert plan.stale is False
    assert plan.tried == []
    assert cat.get_brand_state("kuurth.com") != "needs_attention"


@pytest.mark.unit
def test_a_brand_field_full_of_campaign_names_is_repaired_after_the_run(env):
    """staud.clothing fills Shopify's vendor field with 41 campaign names. That is only
    visible across the whole catalogue, so the repair happens once the run is in."""
    cat, locks, logs = env

    class Campaigns(FakeConnector):
        def fetch(self, r, transport):
            rec = super().fetch(r, transport)
            rec.brand = f"KUURTH {'FALL' if r.url.endswith('a') else 'SUMMER'} 2026 SALE"
            return rec

    run_brand(
        BRAND,
        cat,
        transport=None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: Campaigns(
            [ref(x, f"h{x}") for x in "ab"]
        ),
    )
    # the campaign strings carry the shop's own spelling of its name
    assert {p["brand"] for p in cat.current_products("kuurth.com")} == {"KUURTH"}
    log_files = list((logs / "kuurth.com").glob("*.jsonl"))
    assert any("brand-field-repaired" in f.read_text() for f in log_files)


@pytest.mark.unit
def test_a_run_records_what_it_searched_for_each_field(env):
    """A blank must carry its search history, or it cannot be told apart from a gap."""
    cat, locks, logs = env
    run_brand(
        BRAND,
        cat,
        transport=None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector(
            [ref(x, f"h{x}") for x in "ab"]
        ),
    )
    ev = cat.load_evidence("kuurth.com")
    # the mapper read the payload for every field, on both products
    assert ev[("product_title", "channel")] == (2, 2)
    assert ev[("material_info", "channel")] == (2, 0)
    # nothing looked at the page, so the page sources have no entries at all
    assert ("material_info", "page_llm") not in ev

    from backend.archive.evidence import describe

    assert describe(ev, "material_info").startswith("channel only")


@pytest.mark.unit
def test_a_learned_gallery_rule_is_stored_as_a_json_array():
    """all_images is a JSON array on the record but a rule returns comma-joined text."""
    from backend.archive.runner.run import _coerce

    assert _coerce("all_images", "https://cdn.x/a.jpg, https://cdn.x/b.jpg") == (
        '["https://cdn.x/a.jpg", "https://cdn.x/b.jpg"]'
    )
    assert _coerce("all_images", "https://cdn.x/only.jpg") is None  # one is not a gallery
    assert _coerce("all_images", "photo 1, photo 2") is None


@pytest.mark.unit
def test_a_failed_finder_call_is_not_recorded_as_having_searched(env):
    """An outage must not become "the brand does not publish this"."""
    cat, locks, logs = env

    def broken(domain, url, missing, page_transport=None):
        raise RuntimeError("credit balance is too low")

    run_brand(
        BRAND,
        cat,
        transport=None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector(
            [ref("a", "h1")]
        ),
        field_finder=broken,
    )
    ev = cat.load_evidence("kuurth.com")
    assert ("material_info", "channel") in ev  # the channel really was read
    assert ("material_info", "page_llm") not in ev  # the model never saw the page

    from backend.archive.evidence import describe

    assert describe(ev, "material_info").startswith("channel only")


@pytest.mark.unit
def test_a_product_with_no_image_is_chased_even_when_the_brand_mostly_has_them(env):
    """A field is normally learnable only when the channel provides it on no sampled
    product. psylos1 has images on 77% of products, so its 70 blanks were never chased."""
    cat, locks, logs = env
    asked: list[list[str]] = []

    class MostlyImaged(FakeConnector):
        def fetch(self, r, transport):
            rec = super().fetch(r, transport)
            if not r.url.endswith("/c"):  # every product but one has its images
                rec.main_image_url = "https://cdn.x/a.jpg"
                rec.all_images = '["https://cdn.x/a.jpg", "https://cdn.x/b.jpg"]'
            return rec

    def finder(domain, url, missing, page_transport=None):
        asked.append(sorted(missing))
        return None

    run_brand(
        BRAND,
        cat,
        transport=None,
        mode="full",
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: MostlyImaged(
            [ref(x, f"h{x}") for x in "abc"]
        ),
        field_finder=finder,
    )
    assert any("all_images" in a and "main_image_url" in a for a in asked)


@pytest.mark.unit
def test_a_field_the_model_already_failed_to_find_is_not_paid_for_again(env):
    """The search record is not only a report — it stops the same fruitless call
    being made on every run."""
    cat, locks, logs = env
    calls: list[str] = []

    def finder(domain, url, missing, page_transport=None):
        calls.extend(missing)
        return None  # the model read the page and found nothing

    kwargs = dict(
        locks_dir=locks,
        log_dir=logs,
        prober=lambda d, t: OPEN_CAP,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector(
            [ref("a", "h1")]
        ),
        field_finder=finder,
    )
    run_brand(BRAND, cat, None, mode="full", **kwargs)
    assert "material_info" in calls
    after_first = len(calls)

    run_brand(BRAND, cat, None, mode="full", **kwargs)
    assert len(calls) == after_first  # nothing asked a second time


@pytest.mark.unit
def test_a_gallery_of_one_counts_as_a_gap():
    """theoutnet.com stores exactly one image for all 300 products while its pages show
    six. The field was technically filled, so nothing ever looked."""
    from backend.archive.runner.run import _is_gap

    one = ProductRecord(
        itemurl="https://x.test/p", product_title="Tee",
        all_images='["https://cdn.x/a.jpg"]', main_image_url="https://cdn.x/a.jpg",
    )
    assert _is_gap(one, "all_images") is True
    assert _is_gap(one, "main_image_url") is False  # a hero image is one by definition

    gallery = one.model_copy(
        update={"all_images": '["https://cdn.x/a.jpg", "https://cdn.x/b.jpg"]'}
    )
    assert _is_gap(gallery, "all_images") is False


@pytest.mark.unit
def test_a_learned_gallery_replaces_a_shorter_one_from_the_channel():
    from backend.archive.domain.recipe import Recipe
    from backend.archive.runner.run import _fill_from_recipes

    html = (
        "<html><body><div class='slider'>"
        "<img src='https://cdn.x/a.jpg'><img src='https://cdn.x/b.jpg'>"
        "<img src='https://cdn.x/c.jpg'></div></body></html>"
    )
    rec = ProductRecord(
        itemurl="https://x.test/p", product_title="Tee",
        all_images='["https://cdn.x/a.jpg"]',  # the channel gave one
    )
    _fill_from_recipes(
        rec,
        html,
        [Recipe(field="all_images", kind="css_all_attr",
                expression=".slider img", attribute="src")],
    )
    assert len(rec.image_list()) == 3


@pytest.mark.unit
def test_a_mapper_change_forces_a_full_run(env):
    """A delta leaves untouched products as they were. That is right when only the shop
    changed and wrong when we did: the Woo mapper stopped calling an unpurchasable zero
    a price, and the rows it was written for kept their 0.00."""
    cat, locks, logs = env
    refs = [ref(x, f"h{x}") for x in "abc"]
    fetched: list[list[str]] = []

    class Counting(FakeConnector):
        def fetch(self, r, transport):
            fetched[-1].append(r.url)
            return super().fetch(r, transport)

    def go(mode, version):
        fetched.append([])
        run_brand(
            BRAND, cat, None, mode=mode, locks_dir=locks, log_dir=logs,
            prober=lambda d, t: OPEN_CAP, composer=compose_plan,
            connector_factory=lambda plan, sitemap_url=None, limit=None: Counting(refs),
            version=lambda: version,
        )

    go("full", "code-v1")
    go("delta", "code-v1")
    assert fetched[-1] == []  # nothing on the shop moved, so a delta fetches nothing

    go("delta", "code-v2")  # same shop, new extraction code
    assert len(fetched[-1]) == len(refs)  # every product re-read under the new code
    log_text = "".join(f.read_text() for f in (logs / "kuurth.com").glob("*.jsonl"))
    assert "extraction-changed" in log_text


@pytest.mark.unit
def test_the_first_run_of_a_brand_is_not_treated_as_a_change(env):
    """There is nothing to re-derive when nothing was derived before."""
    cat, locks, logs = env
    run_brand(
        BRAND, cat, None, mode="delta", locks_dir=locks, log_dir=logs,
        prober=lambda d, t: OPEN_CAP, composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: FakeConnector(
            [ref("a", "h1")]
        ),
        version=lambda: "code-v1",
    )
    log_text = "".join(f.read_text() for f in (logs / "kuurth.com").glob("*.jsonl"))
    assert "extraction-changed" not in log_text
