import httpx
import pytest

from backend.archive.observe import RequestLog, Spend
from backend.archive.store.catalog import Catalog
from backend.archive.transport import HttpxTransport


@pytest.mark.unit
def test_every_response_is_recorded_with_what_the_host_said(tmp_path):
    cat = Catalog(tmp_path / "c.db")
    log = RequestLog(cat, batch=2)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/busy":
            return httpx.Response(429, headers={"retry-after": "120"})
        return httpx.Response(200, text="ok")

    t = HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)), sink=log)
    t.get("https://kuurth.com/a")
    t.get("https://kuurth.com/busy")
    log.flush()

    stats = cat.host_stats()
    assert len(stats) == 1
    row = stats[0]
    assert row["host"] == "kuurth.com"
    assert (row["requests"], row["ok"], row["busy"]) == (2, 1, 1)
    assert row["max_retry_after"] == 120  # the host told us how long to wait
    cat.close()


@pytest.mark.unit
def test_a_refused_request_is_distinguished_from_a_rate_limit(tmp_path):
    """403 is a WAF calling us a bot; 429 is a shop asking us to slow down."""
    cat = Catalog(tmp_path / "c.db")
    log = RequestLog(cat, batch=1)
    t = HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))),
        sink=log,
    )
    t.get("https://outlw.xyz/a")
    log.flush()
    row = cat.host_stats()[0]
    assert (row["refused"], row["busy"]) == (1, 0)
    cat.close()


@pytest.mark.unit
def test_a_connection_failure_is_recorded_too(tmp_path):
    cat = Catalog(tmp_path / "c.db")
    log = RequestLog(cat, batch=1)

    def boom(request):
        raise httpx.ConnectTimeout("timed out")

    t = HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(boom)), sink=log)
    with pytest.raises(httpx.ConnectTimeout):
        t.get("https://vancleefarpels.com/a")
    log.flush()
    assert cat.host_stats()[0]["errored"] == 1
    cat.close()


@pytest.mark.unit
def test_spend_adds_up_what_the_api_reported():
    s = Spend(input_rate=3.0, output_rate=15.0)
    s.add(55_000, 400)
    s.add(30_000, 200)
    assert s.calls == 2 and s.input_tokens == 85_000
    # 0.085M x $3 + 0.0006M x $15
    assert s.usd == pytest.approx(0.264, abs=0.001)
    assert s.as_dict()["output_tokens"] == 600
