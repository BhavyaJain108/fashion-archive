"""The dev view is owner-only, and closed when nobody is named as an owner."""

import json

import pytest
from flask import Flask

from backend.api.dev_routes import register_dev_routes
from backend.archive.domain.brand import Brand
from backend.archive.domain.run import Coverage
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import DirectoryObjectStore


class FakeUser:
    def __init__(self, email):
        self.email = email


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = DirectoryObjectStore(tmp_path)
    cat = Catalog(store)
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    from backend.archive.scheduler import Scheduler

    Scheduler(store).add("kuurth.com", cadence_seconds=3600)
    run = cat.open_run("kuurth.com", "full")
    cat.finalize_run(run, 0, Coverage(extracted=0, coverage_pct=1.0, verdict="ok"))
    cat.close()

    monkeypatch.setenv("ARCHIVE_OBJECTS", str(tmp_path))
    # The overview is cached for ten seconds per process; each test has its own
    # store, so none may inherit the previous test's answer.
    import backend.api.dev_routes as dr
    import backend.api.providers as pv

    dr._forget_overview()
    pv._cache.clear()  # provider answers are cached ten minutes per process too
    from backend.archive import roster

    roster.forget_added()  # and the roster's additions are cached a minute
    app = Flask(__name__)
    register_dev_routes(app)
    return app.test_client(), monkeypatch


def _as(monkeypatch, email):
    monkeypatch.setattr(
        "backend.auth.middleware.current_user", lambda: FakeUser(email) if email else None
    )


@pytest.mark.unit
def test_an_empty_owner_list_denies_everyone(client, monkeypatch):
    c, mp = client
    mp.delenv("ADMIN_EMAILS", raising=False)
    _as(mp, "bhavyajain62@gmail.com")
    assert c.get("/api/dev/overview").status_code == 403


@pytest.mark.unit
def test_a_signed_in_stranger_is_refused(client):
    c, mp = client
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "someone@else.com")
    r = c.get("/api/dev/overview")
    assert r.status_code == 403
    assert json.loads(r.data)["code"] == "NOT_OWNER"


@pytest.mark.unit
def test_the_owner_sees_the_brands_and_the_schedule(client):
    c, mp = client
    mp.setenv("ADMIN_EMAILS", "Owner@Example.com")  # matched case-insensitively
    _as(mp, "owner@example.com")
    body = json.loads(c.get("/api/dev/overview").data)
    assert body["success"] is True
    assert body["totals"]["brands"] == 1
    brand = body["brands"][0]
    assert brand["domain"] == "kuurth.com"
    assert brand["next_due"] and brand["enabled"] is True
    assert brand["claimed_by"] is None and brand["worker_alive"] is None


@pytest.mark.unit
def test_run_now_brings_the_next_turn_forward(client, tmp_path):
    from datetime import datetime, timezone

    from backend.archive.scheduler import Scheduler

    c, mp = client
    Scheduler(DirectoryObjectStore(tmp_path)).set_cadence("kuurth.com", 86400)
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")

    assert c.post("/api/dev/brands/kuurth.com/run").status_code == 200
    row = Scheduler(DirectoryObjectStore(tmp_path)).rows()[0]
    assert row["next_due"] <= datetime.now(timezone.utc).isoformat()
    assert c.post("/api/dev/brands/nobody.example/run").status_code == 404


@pytest.mark.unit
def test_run_now_is_refused_while_a_worker_holds_the_brand(client, tmp_path):
    from backend.archive.scheduler import Scheduler

    c, mp = client
    assert Scheduler(DirectoryObjectStore(tmp_path), worker_id="w").claim_next() is not None
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    r = c.post("/api/dev/brands/kuurth.com/run")
    assert r.status_code == 409 and json.loads(r.data)["code"] == "HELD"

    # Once the worker has stopped beating, the answer is to release, not to queue.
    from datetime import datetime, timedelta, timezone

    dead = datetime.now(timezone.utc) - timedelta(minutes=13)
    Scheduler(DirectoryObjectStore(tmp_path))._amend("kuurth.com", claimed_at=dead.isoformat())
    r = c.post("/api/dev/brands/kuurth.com/run")
    assert r.status_code == 409 and json.loads(r.data)["code"] == "DEAD"
    assert json.loads(c.post("/api/dev/brands/kuurth.com/release").data)["released"] is True
    assert json.loads(c.post("/api/dev/brands/kuurth.com/run").data)["outcome"] == "queued"


@pytest.mark.unit
def test_run_now_on_a_paused_brand_is_one_run_and_the_deck_says_so(client, tmp_path):
    from backend.archive.scheduler import Scheduler

    c, mp = client
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    assert c.post("/api/dev/brands/kuurth.com/pause").status_code == 200
    body = json.loads(c.post("/api/dev/brands/kuurth.com/run").data)
    assert body["outcome"] == "queued_once"
    brand = json.loads(c.get("/api/dev/overview").data)["brands"][0]
    assert brand["enabled"] is False and brand["run_once"] is True
    assert Scheduler(DirectoryObjectStore(tmp_path), worker_id="w").claim_next() is not None
    import backend.api.dev_routes as dr

    dr._forget_overview()  # the claim came from a worker, not through the API's cache
    brand = json.loads(c.get("/api/dev/overview").data)["brands"][0]
    assert brand["run_once"] is False and brand["claimed_by"] == "w"


@pytest.mark.unit
def test_pausing_a_held_brand_says_it_takes_effect_after_the_run(client, tmp_path):
    from backend.archive.scheduler import Scheduler

    c, mp = client
    assert Scheduler(DirectoryObjectStore(tmp_path), worker_id="w").claim_next() is not None
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    body = json.loads(c.post("/api/dev/brands/kuurth.com/pause").data)
    assert body["enabled"] is False and body["after_run"] is True
    assert Scheduler(DirectoryObjectStore(tmp_path)).row("kuurth.com")["claimed_by"] == "w"


@pytest.mark.unit
def test_pause_and_resume_flip_the_schedule(client, tmp_path):
    from backend.archive.scheduler import Scheduler

    c, mp = client
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    assert c.post("/api/dev/brands/kuurth.com/pause").status_code == 200
    assert Scheduler(DirectoryObjectStore(tmp_path)).rows()[0]["enabled"] == 0
    assert c.post("/api/dev/brands/kuurth.com/resume").status_code == 200
    assert Scheduler(DirectoryObjectStore(tmp_path)).rows()[0]["enabled"] == 1


@pytest.mark.unit
def test_the_brand_page_lists_every_field_with_its_class_and_evidence(client):
    c, mp = client
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    body = json.loads(c.get("/api/dev/brands/kuurth.com").data)
    assert body["success"] is True and body["brand"]["domain"] == "kuurth.com"
    names = [f["name"] for f in body["fields"]]
    assert "product_title" in names and "size_info" in names and len(names) >= 40
    title = next(f for f in body["fields"] if f["name"] == "product_title")
    assert title["class"] == "A" and title["evidence"] == "never searched"
    assert c.get("/api/dev/brands/nobody.example").status_code == 404


@pytest.mark.unit
def test_hosts_are_their_own_request_and_only_this_brands(client, tmp_path):
    from datetime import datetime, timezone

    c, mp = client
    cat = Catalog(DirectoryObjectStore(tmp_path))
    now = datetime.now(timezone.utc).isoformat()
    cat.record_requests(
        [("kuurth.com", 200, 80, None, now), ("cdn.elsewhere.net", 200, 5, None, now)]
    )
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    body = json.loads(c.get("/api/dev/brands/kuurth.com/hosts").data)
    assert [h["host"] for h in body["hosts"]] == ["kuurth.com"]
    assert "hosts" not in json.loads(c.get("/api/dev/brands/kuurth.com").data)


@pytest.mark.unit
def test_a_command_from_another_site_is_refused(client):
    c, mp = client
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    r = c.post("/api/dev/brands/kuurth.com/run", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and json.loads(r.data)["code"] == "BAD_ORIGIN"
    r = c.post("/api/dev/brands/kuurth.com/pause", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


@pytest.mark.unit
def test_a_brand_id_that_is_not_a_domain_never_reaches_the_store(client):
    c, mp = client
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    for bad in ("..", "..%2Fx", "kuurth.com%2F..%2Fsecret", "UPPER.COM", "-x.com"):
        for path in (f"/api/dev/brands/{bad}", f"/api/dev/brands/{bad}/products"):
            assert c.get(path).status_code in (400, 404), path
        assert c.post(f"/api/dev/brands/{bad}/run").status_code in (400, 404)


@pytest.mark.unit
def test_a_runs_log_is_kept_with_the_run_and_served_as_events(client, tmp_path):
    c, mp = client
    cat = Catalog(DirectoryObjectStore(tmp_path))
    run_id = cat.run_ids("kuurth.com")[-1]
    cat.save_run_log(
        "kuurth.com",
        run_id,
        '{"t": "2026-09-22T05:00:00+00:00", "event": "planned", "composition": "t0×bulk_json"}\n'
        '{"t": "2026-09-22T05:00:01+00:00", "event": "discovered", "refs": 332}\n'
        "not json\n",
    )
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    body = json.loads(c.get(f"/api/dev/brands/kuurth.com/runs/{run_id}/log").data)
    assert [e["event"] for e in body["events"]] == ["planned", "discovered", "unparseable"]
    assert body["events"][1]["refs"] == 332
    assert c.get("/api/dev/brands/kuurth.com/runs/nope/log").status_code == 404
    # And the brand page lists the run itself, scored or not.
    page = json.loads(c.get("/api/dev/brands/kuurth.com").data)
    assert page["runs"][0]["id"] == run_id and page["runs"][0]["card"] is None


@pytest.mark.unit
def test_an_unchanged_answer_is_a_304_and_a_command_makes_it_new_again(client, monkeypatch):
    import backend.api.dev_routes as dr

    dr._forget_overview()
    c, mp = client
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    first = c.get("/api/dev/overview")
    tag = first.headers["ETag"]
    assert first.status_code == 200 and tag
    again = c.get("/api/dev/overview", headers={"If-None-Match": tag})
    assert again.status_code == 304 and not again.data
    # Pausing changes the schedule, which the overview shows: the tag must move.
    assert c.post("/api/dev/brands/kuurth.com/pause").status_code == 200
    changed = c.get("/api/dev/overview", headers={"If-None-Match": tag})
    assert changed.status_code == 200 and changed.headers["ETag"] != tag
    assert json.loads(changed.data)["brands"][0]["enabled"] is False
    # The brand page and costs carry a tag too.
    assert c.get("/api/dev/brands/kuurth.com").headers.get("ETag")
    assert c.get("/api/dev/costs").headers.get("ETag")


@pytest.mark.unit
def test_a_held_brand_shows_where_its_scrape_is(client, tmp_path):
    from backend.archive.scheduler import Scheduler

    c, mp = client
    store = DirectoryObjectStore(tmp_path)
    assert Scheduler(store, worker_id="w1").claim_next() is not None
    Catalog(store).report_progress("kuurth.com", "fetching", 120, 332, force=True)
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    b = json.loads(c.get("/api/dev/overview").data)["brands"][0]
    assert b["claimed_by"] == "w1"
    assert b["progress"]["phase"] == "fetching" and b["progress"]["done"] == 120
    assert b["progress"]["total"] == 332


@pytest.mark.unit
def test_a_brand_added_from_the_deck_is_on_the_roster_the_schedule_and_the_overview(
    client, tmp_path
):
    from backend.archive import roster
    from backend.archive.scheduler import Scheduler

    c, mp = client
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    r = c.post(
        "/api/dev/brands",
        json={
            "domain": "https://New-Shop.com/collections",
            "display_name": "New Shop",
            "show": False,
        },
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert (
        body["domain"] == "new-shop.com" and body["name"] == "New Shop" and body["shown"] is False
    )
    store = DirectoryObjectStore(tmp_path)
    added = {e.domain: e for e in roster.added_entries(store, fresh=True)}
    assert (
        added["new-shop.com"].size == "large" and added["new-shop.com"].display_name == "New Shop"
    )
    assert any(x["domain"] == "new-shop.com" for x in Scheduler(store).rows())
    names = {b["domain"]: b["name"] for b in json.loads(c.get("/api/dev/overview").data)["brands"]}
    assert names["new-shop.com"] == "New Shop"
    assert c.post("/api/dev/brands", json={"domain": "not a domain"}).status_code == 400


@pytest.mark.unit
def test_the_last_run_is_told_in_sentences():
    from backend.api.dev_routes import _narrate

    lines = _narrate(
        [
            {
                "t": "2026-09-22T05:00:00+00:00",
                "event": "planned",
                "composition": "t1×sitemap×structured_data×per_item",
                "status": "ready",
            },
            {"t": "2026-09-22T05:00:02+00:00", "event": "discovered", "refs": 1299},
            {
                "t": "2026-09-22T05:00:02+00:00",
                "event": "selected",
                "mode": "delta",
                "to_fetch": 40,
                "total": 1299,
            },
            {
                "t": "2026-09-22T05:00:03+00:00",
                "event": "already-searched",
                "fields": ["ppu", "unit_type"],
            },
            {"t": "2026-09-22T05:01:00+00:00", "event": "fetch-error", "url": "x", "error": "boom"},
            {"t": "2026-09-22T05:01:00+00:00", "event": "fetch-error", "url": "y", "error": "boom"},
            {
                "t": "2026-09-22T05:02:00+00:00",
                "event": "finder-added",
                "url": "u",
                "fields": ["size_info"],
            },
            {"t": "2026-09-22T05:03:00+00:00", "event": "images-archived", "url": "u", "count": 4},
            {
                "t": "2026-09-22T05:09:00+00:00",
                "event": "finalized",
                "verdict": "ok",
                "errors": 2,
                "extracted": 38,
            },
        ]
    )
    texts = [x["text"] for x in lines]
    assert (
        texts[0].startswith("Decided how to get in: t1×sitemap")
        and "browser's handshake" in texts[0]
    )
    assert "Found 1,299 product links" in texts
    assert "40 of 1,299 products looked new or changed; reading those" in texts
    assert any(t.startswith("Skipped 2 fields") for t in texts)
    assert "Learned a rule for size_info from one product page" in texts
    assert "Finished — the run went well: 38 products stored, 2 errors" in texts
    assert "2 product pages failed to load" in texts
    assert "Archived photographs for 1 products" in texts


@pytest.mark.unit
def test_the_brand_page_carries_last_actions_when_a_log_exists(client, tmp_path):
    c, mp = client
    cat = Catalog(DirectoryObjectStore(tmp_path))
    run_id = cat.run_ids("kuurth.com")[-1]
    cat.save_run_log(
        "kuurth.com",
        run_id,
        '{"t": "2026-09-22T05:00:00+00:00", "event": "discovered", "refs": 3}\n',
    )
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    body = json.loads(c.get("/api/dev/brands/kuurth.com").data)
    assert body["last_actions"]["run_id"] == run_id
    assert body["last_actions"]["lines"][0]["text"] == "Found 3 product links"


@pytest.mark.unit
def test_the_catalogue_can_show_what_has_gone_and_what_each_run_changed(client, tmp_path):
    from backend.archive.domain.product import ProductRecord

    c, mp = client
    cat = Catalog(DirectoryObjectStore(tmp_path))
    cov = Coverage(extracted=1, coverage_pct=1.0, verdict="ok")
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product(
        "kuurth.com", r1, ProductRecord(itemurl="https://kuurth.com/p/a", product_title="A"), None
    )
    cat.record_product(
        "kuurth.com", r1, ProductRecord(itemurl="https://kuurth.com/p/b", product_title="B"), None
    )
    cat.finalize_run(r1, 0, cov)
    r2 = cat.open_run("kuurth.com", "delta")
    cat.mark_seen("kuurth.com", r2, ["https://kuurth.com/p/a"])
    cat.finalize_run(r2, 0, cov)
    cat.close()

    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    live = json.loads(c.get("/api/dev/brands/kuurth.com/products").data)
    assert [p["product_title"] for p in live["products"]] == ["A"]
    assert live["products"][0]["live"] is True and live["products"][0]["first_seen"]
    gone = json.loads(c.get("/api/dev/brands/kuurth.com/products?status=gone").data)
    assert [p["product_title"] for p in gone["products"]] == ["B"]
    assert gone["products"][0]["live"] is False and gone["products"][0]["last_on_site"]
    assert json.loads(c.get("/api/dev/brands/kuurth.com/products?status=all").data)["total"] == 2
    changes = json.loads(c.get("/api/dev/brands/kuurth.com/changes").data)["changes"]
    assert changes[0]["removed"] == 1 and changes[0]["removed_names"] == ["B"]
    assert changes[1]["added"] == 2
    # As of the first run, both were present; as of the second, B had gone.
    from urllib.parse import quote

    first = json.loads(c.get(f"/api/dev/brands/kuurth.com/products?run={quote(r1)}").data)
    assert sorted(p["product_title"] for p in first["products"]) == ["A", "B"]
    assert [r["id"] for r in first["runs"]][:2] == [r2, r1]
    second = json.loads(
        c.get(f"/api/dev/brands/kuurth.com/products?run={quote(r2)}&status=gone").data
    )
    assert [p["product_title"] for p in second["products"]] == ["B"]
    assert c.get("/api/dev/brands/kuurth.com/products?status=added").status_code == 400


@pytest.mark.unit
def test_notes_are_kept_ticked_and_removed(client):
    c, mp = client
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    assert c.post("/api/dev/notes", json={"text": "  "}).status_code == 400
    note = json.loads(c.post("/api/dev/notes", json={"text": "sort by cost"}).data)["note"]
    assert note["done"] is False
    notes = json.loads(c.get("/api/dev/notes").data)["notes"]
    assert [n["text"] for n in notes] == ["sort by cost"]
    r = json.loads(c.post(f"/api/dev/notes/{note['id']}", json={"done": True}).data)
    assert r["notes"][0]["done"] is True and r["notes"][0]["done_at"]
    r = json.loads(c.post(f"/api/dev/notes/{note['id']}", json={"delete": True}).data)
    assert r["notes"] == []
    assert c.post("/api/dev/notes/nope", json={"done": True}).status_code == 400
    assert (
        c.post(
            "/api/dev/notes", json={"text": "x"}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


@pytest.mark.unit
def test_a_batch_answers_for_every_brand_on_its_own(client, tmp_path):
    from backend.archive.scheduler import Scheduler

    c, mp = client
    store = DirectoryObjectStore(tmp_path)
    Scheduler(store).add("other.com", cadence_seconds=3600)
    assert Scheduler(store, worker_id="w").claim_next() is not None  # kuurth is now held
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")

    r = c.post(
        "/api/dev/batch",
        json={"action": "run", "domains": ["kuurth.com", "other.com", "nobody.example", ".."]},
    )
    assert r.status_code == 200
    results = json.loads(r.data)["results"]
    assert results["kuurth.com"] == "already being scraped"
    assert results["other.com"] == "queued"
    assert results["nobody.example"] == "not on the schedule"
    assert results[".."] == "not a domain"

    r = c.post("/api/dev/batch", json={"action": "pause", "domains": ["other.com"]})
    assert json.loads(r.data)["results"]["other.com"] == "paused"
    assert next(x for x in Scheduler(store).rows() if x["domain"] == "other.com")["enabled"] == 0
    assert c.post("/api/dev/batch", json={"action": "explode", "domains": []}).status_code == 400
    assert (
        c.post(
            "/api/dev/batch",
            json={"action": "run", "domains": ["x.com"]},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )


@pytest.mark.unit
def test_products_are_paged_and_the_catalogue_is_released(client):
    c, mp = client
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    body = json.loads(c.get("/api/dev/brands/kuurth.com/products?limit=10").data)
    assert body["success"] is True and body["total"] == 0 and body["products"] == []


@pytest.mark.unit
def test_costs_answer_without_any_provider_key(client):
    c, mp = client
    for k in ("ANTHROPIC_ADMIN_KEY", "CLOUDFLARE_API_TOKEN", "RENDER_API_KEY"):
        mp.delenv(k, raising=False)
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    body = json.loads(c.get("/api/dev/costs").data)
    assert body["success"] is True
    assert body["finder"]["cap_usd"] == 0.0
    for name in ("anthropic", "cloudflare", "render"):
        p = body["providers"][name]
        assert p["ok"] is False and "not set" in p["error"]


@pytest.mark.unit
def test_a_dead_workers_claim_can_be_released_but_a_live_ones_cannot(client, tmp_path):
    from datetime import datetime, timedelta, timezone

    from backend.archive.scheduler import Scheduler

    c, mp = client
    store = DirectoryObjectStore(tmp_path)
    sched = Scheduler(store, worker_id="worker-2")
    assert sched.claim_next() is not None
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")

    r = c.post("/api/dev/brands/kuurth.com/release")
    assert r.status_code == 409 and json.loads(r.data)["code"] == "ALIVE"

    sched._amend(
        "kuurth.com", claimed_at=(datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    )
    r = c.post("/api/dev/brands/kuurth.com/release")
    assert r.status_code == 200 and json.loads(r.data)["released"] is True
    assert Scheduler(store).rows()[0]["claimed_by"] is None
    # Nothing held: a second release is a no-op, not an error.
    assert json.loads(c.post("/api/dev/brands/kuurth.com/release").data)["released"] is False


@pytest.mark.unit
def test_a_claim_whose_heartbeat_stopped_reads_as_stalled_not_running(client, tmp_path):
    """The distinction the page exists for. psylos1 sat claimed for 24 minutes with a
    dead worker behind it, and nothing in the app could tell that from working."""
    from datetime import datetime, timedelta, timezone

    from backend.archive.scheduler import Scheduler

    c, mp = client
    store = DirectoryObjectStore(tmp_path)
    sched = Scheduler(store, worker_id="worker-2")
    due = sched.claim_next()
    assert due is not None
    sched._amend(
        "kuurth.com",
        claimed_at=(datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat(),
    )

    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    body = json.loads(c.get("/api/dev/overview").data)

    assert body["workers"]["stalled"] == ["kuurth.com"]
    assert body["workers"]["running"] == []
    brand = body["brands"][0]
    assert brand["claimed_by"] == "worker-2"
    assert brand["worker_alive"] is False
    assert brand["heartbeat_minutes"] >= 39


@pytest.mark.unit
def test_a_learn_run_is_queued_from_the_deck_and_refused_while_held(client, tmp_path):
    from backend.archive.scheduler import Scheduler

    c, mp = client
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    body = json.loads(
        c.post("/api/dev/brands/kuurth.com/learn", json={"retry_searched": True}).data
    )
    assert body["outcome"] == "queued" and body["mode"] == "learn"
    row = Scheduler(DirectoryObjectStore(tmp_path)).row("kuurth.com")
    assert row["next_mode"] == "learn" and row["retry_searched"] == 1
    brand = json.loads(c.get("/api/dev/overview").data)["brands"][0]
    assert brand["next_mode"] == "learn"

    assert Scheduler(DirectoryObjectStore(tmp_path), worker_id="w").claim_next().mode == "learn"
    r = c.post("/api/dev/brands/kuurth.com/learn")
    assert r.status_code == 409 and json.loads(r.data)["code"] == "HELD"
    assert c.post("/api/dev/brands/nobody.example/learn").status_code == 404


@pytest.mark.unit
def test_the_catalogue_filters_by_what_the_brand_offers(client, tmp_path):
    from backend.archive.domain.product import ProductRecord

    c, mp = client
    cat = Catalog(DirectoryObjectStore(tmp_path))
    r1 = cat.open_run("kuurth.com", "full")
    for i, (colour, sizes, avail, price) in enumerate(
        [
            ("Black", "S, M", "in_stock, out_of_stock", 120.0),
            ("Black", "M, L", "in_stock, in_stock", 80.0),
            ("Red", "38, 40", "out_of_stock, in_stock", 200.0),
        ]
    ):
        cat.record_product(
            "kuurth.com",
            r1,
            ProductRecord(
                itemurl=f"https://kuurth.com/p/{i}",
                product_title=f"P{i}",
                color_info=colour,
                size_info=sizes,
                size_availability=avail,
                price=price,
                category1="Women",
                in_stock=True,
            ),
            None,
        )
    cat.finalize_run(r1, 0, Coverage(extracted=3, coverage_pct=1.0, verdict="ok"))
    cat.close()
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")

    body = json.loads(c.get("/api/dev/brands/kuurth.com/products").data)
    assert body["total"] == 3
    assert {i["value"]: i["count"] for i in body["facets"]["colour"]} == {"Black": 2, "Red": 1}
    assert body["price_range"] == {"min": 80.0, "max": 200.0}

    body = json.loads(c.get("/api/dev/brands/kuurth.com/products?colour=black&size=M").data)
    assert body["total"] == 2 and body["selected"] == {"colour": ["black"], "size": ["M"]}
    body = json.loads(
        c.get("/api/dev/brands/kuurth.com/products?colour=black&size=M&sized_in_stock=1").data
    )
    assert body["total"] == 1  # M is offered on both, in stock on one
    body = json.loads(c.get("/api/dev/brands/kuurth.com/products?size=S&sized_in_stock=1").data)
    assert body["total"] == 1
    body = json.loads(c.get("/api/dev/brands/kuurth.com/products?price_min=100").data)
    assert body["total"] == 2 and body["price_min"] == 100.0
    assert c.get("/api/dev/brands/kuurth.com/products?price_min=abc").status_code == 400


@pytest.mark.unit
def test_a_sweep_is_queued_from_the_deck_with_the_same_refusals_as_run(client, tmp_path):
    from backend.archive.scheduler import Scheduler

    c, mp = client
    mp.setenv("ADMIN_EMAILS", "owner@example.com")
    _as(mp, "owner@example.com")
    r = c.post("/api/dev/brands/kuurth.com/sweep_seconds", json={"seconds": 900})
    assert r.status_code == 200 and json.loads(r.data)["sweep_seconds"] == 900
    bad = "/api/dev/brands/kuurth.com/sweep_seconds"
    assert c.post(bad, json={"seconds": -1}).status_code == 400
    assert c.post(bad, json={}).status_code == 400
    assert (
        c.post("/api/dev/brands/nobody.example/sweep_seconds", json={"seconds": 1}).status_code
        == 404
    )

    body = json.loads(c.post("/api/dev/brands/kuurth.com/sweep").data)
    assert body["outcome"] == "queued" and body["mode"] == "sweep"
    brand = json.loads(c.get("/api/dev/overview").data)["brands"][0]
    assert brand["sweep_seconds"] == 900 and brand["sweep_queued"] is True
    assert brand["last_sweep"] is None

    sched = Scheduler(DirectoryObjectStore(tmp_path), worker_id="w")
    # The fixture added the brand due now, so its delta turn comes first and the
    # queued sweep waits for the turn to pass.
    assert sched.claim_next().mode == "delta"
    r = c.post("/api/dev/brands/kuurth.com/sweep")
    assert r.status_code == 409 and json.loads(r.data)["code"] == "HELD"
    assert c.post("/api/dev/brands/nobody.example/sweep").status_code == 404
    r = c.post("/api/dev/brands/kuurth.com/sweep", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    sched.release("kuurth.com", 3600)
    assert sched.claim_next().mode == "sweep"  # the queued sweep, once the turn is past
    sched.release_after_sweep("kuurth.com")
    import backend.api.dev_routes as dr

    dr._forget_overview()  # the release came from a worker, not through the API's cache
    brand = json.loads(c.get("/api/dev/overview").data)["brands"][0]
    assert brand["last_sweep"] and brand["sweep_queued"] is False
