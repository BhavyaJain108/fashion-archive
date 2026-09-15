import httpx
import pytest

from backend.archive.budget import HostBudget
from backend.archive.transport import HttpxTransport


class Clock:
    """A clock that only moves when something sleeps."""

    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


@pytest.fixture()
def clock():
    return Clock()


@pytest.mark.unit
def test_requests_to_one_host_are_spaced(clock):
    b = HostBudget(gap=0.5, sleep=clock.sleep, clock=clock.now)
    assert b.acquire("kuurth.com") == 0  # the first one goes straight through
    assert b.acquire("kuurth.com") == 0.5
    assert clock.slept == [0.5]


@pytest.mark.unit
def test_a_different_host_is_not_made_to_wait(clock):
    b = HostBudget(gap=0.5, sleep=clock.sleep, clock=clock.now)
    b.acquire("kuurth.com")
    assert b.acquire("staud.clothing") == 0


@pytest.mark.unit
def test_a_retry_after_is_obeyed_exactly(clock):
    b = HostBudget(gap=0.5, sleep=clock.sleep, clock=clock.now)
    b.observe("kuurth.com", 429, retry_after=120)
    assert b.blocked_for("kuurth.com") == 120
    assert b.acquire("kuurth.com") == 120


@pytest.mark.unit
def test_a_refusal_without_a_time_backs_off_and_doubles(clock):
    b = HostBudget(gap=0.5, sleep=clock.sleep, clock=clock.now)
    b.observe("kuurth.com", 429)
    first = b.blocked_for("kuurth.com")
    b.observe("kuurth.com", 429)
    assert b.blocked_for("kuurth.com") == first * 2


@pytest.mark.unit
def test_being_called_a_bot_stands_down_for_longer_than_a_rate_limit(clock):
    """403 is not a rate limit — retrying is how a temporary block becomes permanent."""
    b = HostBudget(gap=0.5, sleep=clock.sleep, clock=clock.now)
    b.observe("outlw.xyz", 403)
    b.observe("kuurth.com", 429)
    assert b.blocked_for("outlw.xyz") > b.blocked_for("kuurth.com")


@pytest.mark.unit
def test_one_success_clears_the_penalty(clock):
    b = HostBudget(gap=0.5, sleep=clock.sleep, clock=clock.now)
    b.observe("kuurth.com", 429)
    b.observe("kuurth.com", 200)
    b.observe("kuurth.com", 429)
    # back to the first stand-down, not the doubled one
    assert b.blocked_for("kuurth.com") == 60.0


@pytest.mark.unit
def test_the_transport_asks_the_budget_before_every_request(clock):
    b = HostBudget(gap=0.5, sleep=clock.sleep, clock=clock.now)
    t = HttpxTransport(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(429, headers={"retry-after": "90"})
            )
        ),
        budget=b,
    )
    t.get("https://kuurth.com/a")
    assert b.blocked_for("kuurth.com") == 90  # learned from the response
    t.get("https://kuurth.com/b")
    assert 90 in clock.slept  # and waited before asking again


@pytest.mark.unit
def test_a_clean_run_speeds_up_to_the_hosts_floor_and_no_further():
    b = HostBudget(sleep=lambda s: None, clock=lambda: 0.0)
    for _ in range(400):
        b.observe("cdn.shopify.com", 200)
        b.observe("kuurth.com", 200)
    assert b.gap_for("cdn.shopify.com") == pytest.approx(1 / 30)  # an image CDN
    assert b.gap_for("kuurth.com") == pytest.approx(1 / 5)  # someone's storefront


@pytest.mark.unit
def test_a_refusal_halves_the_rate_and_it_climbs_back():
    b = HostBudget(sleep=lambda s: None, clock=lambda: 0.0)
    for _ in range(400):
        b.observe("cdn.shopify.com", 200)
    fast = b.gap_for("cdn.shopify.com")

    b.observe("cdn.shopify.com", 429)
    assert b.gap_for("cdn.shopify.com") == pytest.approx(fast * 2)

    for _ in range(400):
        b.observe("cdn.shopify.com", 200)
    assert b.gap_for("cdn.shopify.com") == pytest.approx(fast)


@pytest.mark.unit
def test_a_brands_own_image_host_is_quicker_than_its_shop_but_not_a_cdn():
    b = HostBudget(sleep=lambda s: None, clock=lambda: 0.0)
    assert b.floor("esa.psylos1.com") == pytest.approx(1 / 5)  # unknown: treat as a shop
    b.mark_asset_host("esa.psylos1.com")
    assert b.floor("esa.psylos1.com") == pytest.approx(1 / 15)
    assert b.floor("cdn.shopify.com") == pytest.approx(1 / 30)


@pytest.mark.unit
def test_an_explicit_gap_still_wins():
    b = HostBudget(gap=2.0, sleep=lambda s: None, clock=lambda: 0.0)
    assert b.floor("cdn.shopify.com") == 2.0
