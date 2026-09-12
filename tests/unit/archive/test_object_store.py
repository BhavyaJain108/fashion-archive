"""The object store, and the conditional writes the whole design rests on."""

import io

import pytest

from backend.archive.store.objects import (
    Conflict,
    DirectoryObjectStore,
    R2ObjectStore,
    _etag,
    dumps,
    loads,
)


@pytest.fixture()
def store(tmp_path):
    return DirectoryObjectStore(tmp_path)


@pytest.mark.unit
def test_put_then_get_round_trips(store):
    etag = store.put("a/b.json", b'{"x":1}')
    assert store.get("a/b.json") == (b'{"x":1}', etag)


@pytest.mark.unit
def test_get_missing_is_none_not_an_error(store):
    assert store.get("nope.json") is None


@pytest.mark.unit
def test_create_if_absent_refuses_the_second_writer(store):
    """This is what makes claiming a brand safe with no database behind it."""
    store.put("claim.json", b"first", if_none_match=True)
    with pytest.raises(Conflict):
        store.put("claim.json", b"second", if_none_match=True)
    assert store.get("claim.json")[0] == b"first"


@pytest.mark.unit
def test_replace_needs_the_current_etag(store):
    etag = store.put("row.json", b"one")
    store.put("row.json", b"two", if_match=etag)
    with pytest.raises(Conflict):
        store.put("row.json", b"three", if_match=etag)  # stale: someone wrote "two"
    assert store.get("row.json")[0] == b"two"


@pytest.mark.unit
def test_replace_of_a_missing_key_is_refused(store):
    with pytest.raises(Conflict):
        store.put("gone.json", b"x", if_match="whatever")


@pytest.mark.unit
def test_list_returns_keys_under_a_prefix_only(store):
    store.put("runs/a/1.json", b"{}")
    store.put("runs/a/2.json", b"{}")
    store.put("runs/b/1.json", b"{}")
    assert store.list("runs/a/") == ["runs/a/1.json", "runs/a/2.json"]


@pytest.mark.unit
def test_delete_is_idempotent(store):
    store.put("x.json", b"{}")
    store.delete("x.json")
    store.delete("x.json")
    assert store.get("x.json") is None


@pytest.mark.unit
def test_a_key_cannot_escape_the_root(store):
    # Keys are built from domains, which come from a file a human edits.
    with pytest.raises(ValueError):
        store.put("../outside.json", b"{}")


@pytest.mark.unit
def test_encoding_is_stable_so_an_etag_means_something(store):
    a = dumps({"b": 1, "a": [2, 3]})
    b = dumps({"a": [2, 3], "b": 1})
    assert a == b
    assert loads(a) == {"a": [2, 3], "b": 1}


class FakeS3:
    """Just enough S3 to enforce the two preconditions, refusing the way R2 does.

    The codes come from the live probe against the bucket, not from the documentation:
    a stale If-Match and a second If-None-Match both answered PreconditionFailed.
    """

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, ContentType=None, IfMatch=None, IfNoneMatch=None):
        from botocore.exceptions import ClientError

        current = self.objects.get(Key)
        refused = (IfNoneMatch == "*" and current is not None) or (
            IfMatch is not None and (current is None or _etag(current) != IfMatch)
        )
        if refused:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[Key] = Body
        return {"ETag": f'"{_etag(Body)}"'}

    def get_object(self, Bucket, Key):
        from botocore.exceptions import ClientError

        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key]), "ETag": f'"{_etag(self.objects[Key])}"'}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def get_paginator(self, _name):
        outer = self

        class Pager:
            def paginate(self, Bucket, Prefix=""):
                contents = [{"Key": k} for k in sorted(outer.objects) if k.startswith(Prefix)]
                return [{"Contents": contents}]

        return Pager()


@pytest.fixture()
def r2():
    return R2ObjectStore("bucket", client=FakeS3(), prefix="archive-store/")


@pytest.mark.unit
def test_r2_maps_preconditions_onto_conflict(r2):
    etag = r2.put("k.json", b"one")
    with pytest.raises(Conflict):
        r2.put("k.json", b"two", if_none_match=True)
    r2.put("k.json", b"two", if_match=etag)
    with pytest.raises(Conflict):
        r2.put("k.json", b"three", if_match=etag)
    assert r2.get("k.json")[0] == b"two"


@pytest.mark.unit
def test_r2_missing_key_is_none(r2):
    assert r2.get("absent.json") is None


@pytest.mark.unit
def test_r2_hides_its_prefix_from_callers(r2):
    """The bucket also holds the photographs, so the store lives under a prefix —
    but a caller asking for `runs/` must not have to know that."""
    r2.put("runs/a/1.json", b"{}")
    r2.put("runs/b/1.json", b"{}")
    assert r2.list("runs/") == ["runs/a/1.json", "runs/b/1.json"]


@pytest.mark.unit
def test_r2_delete_then_get_is_none(r2):
    r2.put("x.json", b"{}")
    r2.delete("x.json")
    assert r2.get("x.json") is None


@pytest.mark.unit
def test_a_conditional_write_is_one_operation_not_two(tmp_path):
    """Four threads racing to create the same key: exactly one may win.

    The first version checked the etag and then wrote as separate steps, so two
    threads both passed the check and both wrote. It looked correct single-threaded
    and claimed a brand twice as soon as the daemon had workers.
    """
    import threading

    winners: list[bool] = []
    barrier = threading.Barrier(4)

    def race():
        store = DirectoryObjectStore(tmp_path)  # a fresh instance, as a worker builds
        barrier.wait()
        try:
            store.put("claim.json", b"mine", if_none_match=True)
            winners.append(True)
        except Conflict:
            pass

    threads = [threading.Thread(target=race) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert winners == [True]


@pytest.mark.unit
def test_an_explicit_path_beats_a_configured_bucket(tmp_path, monkeypatch):
    """R2 used to win whenever it was configured, so a caller asking for a temporary
    directory got the production bucket — and the end-to-end tests wrote 41 objects of
    fixture data into it. An explicit path is an instruction."""
    from backend.archive.store.objects import object_store
    from config.config import config

    monkeypatch.setattr(config, "R2_ACCOUNT_ID", "acct", raising=False)
    monkeypatch.setattr(config, "R2_ACCESS_KEY_ID", "key", raising=False)
    monkeypatch.setattr(config, "R2_SECRET_ACCESS_KEY", "secret", raising=False)
    monkeypatch.setattr(config, "R2_BUCKET", "bucket", raising=False)

    assert isinstance(object_store(tmp_path), DirectoryObjectStore)
    # Naming the store must not build a client: this ran green locally, where
    # config/.env has real credentials, and failed on CI with
    # PartialCredentialsError. The client is lazy now, and this asserts the choice
    # rather than the connection.
    assert type(object_store()).__name__ == "R2ObjectStore"
