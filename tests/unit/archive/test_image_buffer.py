"""The image index is buffered, not rewritten once per photograph."""

import pytest

from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import DirectoryObjectStore


class CountingStore(DirectoryObjectStore):
    def __init__(self, root):
        super().__init__(root)
        self.writes = []

    def put(self, key, body, *, if_match=None, if_none_match=False):
        self.writes.append(key)
        return super().put(key, body, if_match=if_match, if_none_match=if_none_match)


@pytest.mark.unit
def test_recording_many_photographs_does_not_rewrite_the_index_each_time(tmp_path):
    store = CountingStore(tmp_path)
    cat = Catalog(store)
    for i in range(50):
        cat.record_image("k.com", f"https://k.com/p/{i}", f"https://cdn/{i}.jpg", f"h{i}")
    assert store.writes.count("images/k.com.json") == 0, "wrote before the buffer filled"
    cat.close()
    assert store.writes.count("images/k.com.json") == 1

    fresh = Catalog(DirectoryObjectStore(tmp_path))
    assert len(fresh.archived_images("k.com")) == 0  # no stored_url given
    assert fresh.known_image_urls("k.com", "https://k.com/p/7") == {"https://cdn/7.jpg"}


@pytest.mark.unit
def test_stored_photographs_survive_the_round_trip(tmp_path):
    store = DirectoryObjectStore(tmp_path)
    cat = Catalog(store)
    cat.record_image(
        "k.com", "https://k.com/p/a", "https://cdn/a.jpg", "h", stored_url="https://img/a.jpg"
    )
    cat.close()
    fresh = Catalog(DirectoryObjectStore(tmp_path))
    assert fresh.archived_images("k.com") == {"https://k.com/p/a": ["https://img/a.jpg"]}
    assert fresh.stored_image_count("k.com") == 1
