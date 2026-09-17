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
