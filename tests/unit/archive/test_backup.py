"""The backup's halves that need no database: the line format, the R2 copies, the
prune, and the once-a-day claim. The Postgres dump and restore are in
tests/db/test_backup.py."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.archive import backup as bk
from backend.archive.store.objects import DirectoryObjectStore, R2ObjectStore, dumps, loads

NOW = datetime(2026, 9, 24, 3, 0, tzinfo=timezone.utc)


@pytest.mark.unit
def test_ndjson_round_trip_keeps_every_value_shape():
    rows = [
        {
            "brand": "bode.com",
            "price": 300.0,
            "in_stock": True,
            "categories": ["MENS", "SHIRTS"],
            "record": {"title": "Shirt — Blue", "images": ["https://x/1.jpg"]},
            "raw": None,
            "updated_at": NOW,
        },
        {"brand": "marrknull.com", "title": "上衣", "categories": [], "record": {}},
    ]
    body = bk.dump_rows(iter(rows))
    assert body[:2] == b"\x1f\x8b"  # gzip
    back = list(bk.load_rows(body))
    assert back[0]["record"] == rows[0]["record"]
    assert back[0]["categories"] == ["MENS", "SHIRTS"] and back[0]["raw"] is None
    assert back[0]["updated_at"] == NOW.isoformat()  # a string; Postgres casts it back
    assert back[1]["title"] == "上衣"


@pytest.mark.unit
def test_dump_streams_rather_than_collects():
    """A generator that counts how far it was read: the dump must pull it to the end
    without ever calling list() on it."""
    seen = []

    def rows():
        for i in range(5000):
            seen.append(i)
            yield {"brand": "x", "i": i}

    body = bk.dump_rows(rows())
    assert len(seen) == 5000
    assert sum(1 for _ in bk.load_rows(body)) == 5000


@pytest.mark.unit
def test_control_plane_copies_only_what_is_named(tmp_path):
    store = DirectoryObjectStore(tmp_path)
    for key in (
        "fleet.json",
        "rules/bode.com.json",
        "plans/bode.com.json",
        "control/schedule/bode.com.json",
        "control/daemon.json",  # not copied: a flag, not state
        "runs/bode.com/r1.json",  # not copied: re-derived by the next pass
        "logs/bode.com/r1.jsonl",  # not copied: history, not state
        "catalogue/bode.com.json",  # not copied: the frozen pre-migration object
    ):
        store.put(key, dumps({"key": key}))
    result = bk.copy_control_plane(store, "2026-09-24")
    assert result == {"copied": 4, "absent": 0}
    copied = store.list("backups/2026-09-24/r2/")
    assert copied == [
        "backups/2026-09-24/r2/control/schedule/bode.com.json",
        "backups/2026-09-24/r2/fleet.json",
        "backups/2026-09-24/r2/plans/bode.com.json",
        "backups/2026-09-24/r2/rules/bode.com.json",
    ]
    assert loads(store.get("backups/2026-09-24/r2/fleet.json")[0]) == {"key": "fleet.json"}


@pytest.mark.unit
def test_r2_copy_is_a_server_side_copy_object():
    """No get, no put: the bytes stay in the bucket."""
    calls = []

    class Client:
        def copy_object(self, **kw):
            calls.append(kw)

        def get_object(self, **kw):
            raise AssertionError("must not download")

        def put_object(self, **kw):
            raise AssertionError("must not upload")

    store = R2ObjectStore("bucket", client=Client(), prefix="archive-store/")
    assert store.copy("rules/a.json", "backups/2026-09-24/r2/rules/a.json") is True
    assert calls == [
        {
            "Bucket": "bucket",
            "CopySource": {"Bucket": "bucket", "Key": "archive-store/rules/a.json"},
            "Key": "archive-store/backups/2026-09-24/r2/rules/a.json",
        }
    ]


@pytest.mark.unit
def test_prune_drops_days_older_than_fourteen(tmp_path):
    store = DirectoryObjectStore(tmp_path)
    for days_ago in (0, 1, 13, 14, 15, 40):
        day = (NOW - timedelta(days=days_ago)).date().isoformat()
        store.put(f"backups/{day}/pg/products.ndjson.gz", b"x")
        store.put(f"backups/{day}/manifest.json", b"{}")
    removed = bk.prune(store, NOW)
    assert removed == ["2026-08-15", "2026-09-09"]  # 40 and 15 days ago
    assert bk.days_held(store) == ["2026-09-10", "2026-09-11", "2026-09-23", "2026-09-24"]
    assert store.list("backups/2026-08-15/") == []


class FakePg:
    """Enough of PgCatalog for the claim: it only has to look like one."""

    def _pg(self):
        raise AssertionError("the fake run never opens a connection")


def _fake_run(calls):
    def run(catalog, store, now):
        calls.append(now.date().isoformat())
        return {
            "day": now.date().isoformat(),
            "rows": 3,
            "bytes": 100,
            "seconds": 0.1,
            "pruned": [],
            "r2": {"copied": 0, "absent": 0},
        }

    return run


@pytest.mark.unit
def test_one_worker_takes_the_day_and_the_others_see_it(tmp_path):
    calls: list[str] = []
    a = DirectoryObjectStore(tmp_path)
    b = DirectoryObjectStore(tmp_path)
    quiet = lambda *_: None  # noqa: E731
    assert bk.daily_backup(a, FakePg(), "w1", NOW, log=quiet, run=_fake_run(calls)) is not None
    assert bk.daily_backup(b, FakePg(), "w2", NOW, log=quiet, run=_fake_run(calls)) is None
    assert bk.daily_backup(a, FakePg(), "w1", NOW, log=quiet, run=_fake_run(calls)) is None
    assert calls == ["2026-09-24"]
    assert bk.status(a)["state"] == "done" and bk.status(a)["worker"] == "w1"
    # the next day is a new claim
    tomorrow = NOW + timedelta(days=1)
    assert bk.daily_backup(b, FakePg(), "w2", tomorrow, log=quiet, run=_fake_run(calls))
    assert calls == ["2026-09-24", "2026-09-25"]


@pytest.mark.unit
def test_a_failed_day_is_retried_and_a_dead_claim_is_retaken(tmp_path):
    store = DirectoryObjectStore(tmp_path)
    quiet = lambda *_: None  # noqa: E731

    def boom(catalog, store, now):
        raise RuntimeError("bucket 503")

    assert bk.daily_backup(store, FakePg(), "w1", NOW, log=quiet, run=boom) is None
    assert bk.status(store)["state"] == "failed" and "503" in bk.status(store)["error"]
    calls: list[str] = []
    assert bk.daily_backup(store, FakePg(), "w2", NOW, log=quiet, run=_fake_run(calls))
    assert calls == ["2026-09-24"]

    # a worker that claimed and died: its claim is stale after STALE_SECONDS
    store.put(
        bk.CONTROL,
        dumps({"day": "2026-09-24", "state": "running", "worker": "w9", "started_at": "old"}),
    )
    assert bk.daily_backup(store, FakePg(), "w2", NOW, log=quiet, run=_fake_run(calls))
    # but a fresh claim is left alone
    store.put(
        bk.CONTROL,
        dumps(
            {
                "day": "2026-09-24",
                "state": "running",
                "worker": "w9",
                "started_at": (NOW - timedelta(minutes=5)).isoformat(),
            }
        ),
    )
    assert bk.daily_backup(store, FakePg(), "w2", NOW, log=quiet, run=_fake_run(calls)) is None
    assert calls == ["2026-09-24", "2026-09-24"]


@pytest.mark.unit
def test_the_r2_backend_has_nothing_to_dump(tmp_path):
    from backend.archive.store.catalog import Catalog

    store = DirectoryObjectStore(tmp_path)
    assert bk.daily_backup(store, Catalog(store), "w1", NOW, log=lambda *_: None) is None
    assert store.get(bk.CONTROL) is None  # not even a claim


@pytest.mark.unit
def test_cli_backup_refuses_without_postgres(tmp_path, monkeypatch, capsys):
    from backend.archive.runner.cli import main

    monkeypatch.delenv("CATALOG_BACKEND", raising=False)
    objects = tmp_path / "objects"
    assert main(["backup", "--objects", str(objects)]) == 2
    assert "CATALOG_BACKEND=pg" in capsys.readouterr().err
    assert main(["backup", "--objects", str(objects), "--status"]) == 0
    assert "days:  none" in capsys.readouterr().out
