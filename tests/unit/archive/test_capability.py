import httpx
import pytest

from backend.archive.capability import (
    CapabilityReport,
    classify,
    format_matrix,
    probe_brand,
)
from backend.archive.domain.brand import Brand, Capability, TransportLevel
from backend.archive.domain.product import ProductRecord, ProductRef, pack_images, pack_sizes
from backend.archive.planner import compose_plan
from backend.archive.transport import HttpxTransport

BRAND = Brand(domain="kuurth.com", homepage_url="https://kuurth.com")
OPEN = Capability(
    domain="kuurth.com", platform="shopify", transport=TransportLevel.T0, bulk_json=True
)
GATED = Capability(domain="x.com", transport=TransportLevel.T4, password_gated=True)


def _t() -> HttpxTransport:
    return HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="{}")))
    )


class Conn:
    kind = "shopify"

    def __init__(self, n=10, sizes=True, title=True):
        self.n, self.sizes, self.title = n, sizes, title

    def discover(self, brand, transport):
        return [ProductRef(url=f"https://kuurth.com/products/p{i}") for i in range(self.n)]

    def fetch(self, ref, transport):
        return ProductRecord(
            itemurl=ref.url,
            product_title="Ring" if self.title else "",
            price=10.0,
            in_stock=True,
            **pack_images(["a.jpg"]),
            **pack_sizes([{"size": "M"}] if self.sizes else []),
        )


@pytest.mark.unit
def test_classify_thresholds():
    core = {"product_title": 1.0, "price": 1.0, "in_stock": 1.0, "all_images": 1.0}
    assert classify({**core, "size_info": 1.0}) == "full"
    assert classify({**core, "size_info": 0.0}) == "partial"  # the structured-lane signature
    assert classify({**core, "price": 0.07, "size_info": 0.0}) == "poor"  # xsai signature
    assert classify({}) == "poor"


@pytest.mark.unit
def test_probe_reports_full_capability_and_samples_only_n():
    rep = probe_brand(
        BRAND,
        _t(),
        sample=3,
        prober=lambda d, t: OPEN,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: Conn(n=500),
    )
    assert rep.verdict == "full"
    assert rep.sampled == 3 and rep.catalog_size == 500  # sees the catalog, fetches 3
    assert rep.lane == "t0×bulk_json×platform_json×per_item"


@pytest.mark.unit
def test_probe_reports_partial_when_sizes_missing():
    rep = probe_brand(
        BRAND,
        _t(),
        sample=3,
        prober=lambda d, t: OPEN,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: Conn(sizes=False),
    )
    assert rep.verdict == "partial" and rep.fill["size_info"] == 0.0


@pytest.mark.unit
def test_probe_reports_blocked_on_channel_block():
    from backend.archive.connectors.base import ChannelBlocked

    class Blocked(Conn):
        def discover(self, brand, transport):
            raise ChannelBlocked("403")

    rep = probe_brand(
        BRAND,
        _t(),
        prober=lambda d, t: OPEN,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: Blocked(),
    )
    assert rep.verdict == "blocked" and "403" in rep.note


@pytest.mark.unit
def test_probe_reports_gated_without_fetching():
    rep = probe_brand(BRAND, _t(), prober=lambda d, t: GATED, composer=compose_plan)
    assert rep.verdict == "gated" and rep.sampled == 0


@pytest.mark.unit
def test_probe_never_raises_on_unexpected_errors():
    def boom(domain, transport):
        raise TimeoutError("hung")

    rep = probe_brand(BRAND, _t(), prober=boom)
    assert rep.verdict == "unreachable" and "hung" in rep.note


@pytest.mark.unit
def test_matrix_renders_and_orders_worst_last():
    reps = [
        CapabilityReport(domain="blocked.com", verdict="blocked"),
        CapabilityReport(domain="good.com", verdict="full", fill={"price": 1.0}, catalog_size=9),
    ]
    out = format_matrix(reps)
    assert out.index("good.com") < out.index("blocked.com")
    assert "full=1" in out and "blocked=1" in out


@pytest.mark.unit
def test_gated_brands_are_collapsed_to_a_footnote_by_default():
    reps = [
        CapabilityReport(domain="good.com", verdict="full"),
        CapabilityReport(domain="locked.com", verdict="gated"),
        CapabilityReport(domain="alsolocked.com", verdict="gated"),
    ]
    out = format_matrix(reps)
    table = out.split("gated (watched")[0]
    assert "locked.com" not in table  # no rows for gated stores
    assert "gated (watched, nothing to measure yet): alsolocked.com, locked.com" in out
    assert "gated=2" in out  # still counted honestly

    full = format_matrix(reps, show_gated=True)
    assert "locked.com" in full.split("full=")[0]  # rows restored on request
