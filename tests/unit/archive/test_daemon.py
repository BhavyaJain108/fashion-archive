import threading
import time

import pytest

from backend.archive.connectors.base import ChannelBusy
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord
from backend.archive.runner.daemon import run_once
from backend.archive.scheduler import Scheduler
from backend.archive.store.catalog import Catalog


def rec(url="https://kuurth.com/products/a") -> ProductRecord:
    return ProductRecord(
        itemurl=url,
        product_title="Tee",
        price=40.0,
        in_stock=True,
        main_image_url="https://cdn.x/a.jpg",
        all_images='["https://cdn.x/a.jpg", "https://cdn.x/b.jpg"]',
    )


@pytest.fixture()
def env(tmp_path):
    cat = Catalog(tmp_path / "c.db")
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    sched = Scheduler(cat)
    sched.add("kuurth.com", cadence_seconds=3600)
    return cat, sched


@pytest.mark.unit
def test_nothing_due_is_not_an_error(tmp_path):
    cat = Catalog(tmp_path / "c.db")
    assert run_once(cat, Scheduler(cat), lambda b: ([], 0.0), log=lambda *a: None) is False


@pytest.mark.unit
def test_one_brand_is_scraped_scored_and_handed_back(env):
    cat, sched = env
    run = cat.open_run("kuurth.com", "full")
    cat.finalize_run(run, 0, None)
    assert run_once(cat, sched, lambda b: ([rec()], 0.25), log=lambda *a: None) is True

    card = cat.scorecards("kuurth.com")[0]
    assert card["products"] == 1 and card["required_ok"] is True and card["cost_usd"] == 0.25
    assert sched.rows()[0]["claimed_by"] is None  # handed back for its next turn


@pytest.mark.unit
def test_a_busy_host_defers_the_brand_without_using_its_turn(env):
    cat, sched = env

    def busy(brand):
        raise ChannelBusy("429")

    assert run_once(cat, sched, busy, log=lambda *a: None) is True
    row = sched.rows()[0]
    assert row["claimed_by"] is None
    assert cat.scorecards("kuurth.com") == []  # nothing was measured, nothing recorded


@pytest.mark.unit
def test_a_crashing_brand_does_not_stop_the_loop(env):
    cat, sched = env

    def boom(brand):
        raise RuntimeError("hostile site")

    assert run_once(cat, sched, boom, log=lambda *a: None) is True
    assert sched.rows()[0]["claimed_by"] is None


@pytest.mark.unit
def test_parallel_workers_share_the_schedule_without_collisions(tmp_path):
    """Claiming is atomic, so workers need no coordination beyond the database."""
    cat = Catalog(tmp_path / "c.db")
    domains = [f"brand{i}.test" for i in range(12)]
    for d in domains:
        cat.upsert_brand(Brand(domain=d, homepage_url=f"https://{d}"))
        Scheduler(cat).add(d, cadence_seconds=3600)

    done: list[str] = []
    lock = threading.Lock()

    def drain(worker_id):
        c = Catalog(tmp_path / "c.db")
        s = Scheduler(c, worker_id=worker_id)
        while True:
            due = s.claim_next()
            if due is None:
                break
            with lock:
                done.append(due.domain)
            time.sleep(0.001)
            s.release(due.domain, due.cadence_seconds)
        c.close()

    threads = [threading.Thread(target=drain, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(done) == sorted(domains)  # each brand taken exactly once
