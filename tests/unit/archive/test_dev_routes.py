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
