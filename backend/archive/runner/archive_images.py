"""The image pass: fetch every photograph a brand's products name, and keep the bytes.

Separate from scraping on purpose. A scrape reads a catalogue and should finish in
minutes; fetching 40,000 photographs takes hours and wants a different pace, so making
one wait on the other would mean either slow scrapes or a thin archive. The two meet in
the catalogue: a scrape records the image URLs, and this walks what is recorded.

Re-runnable at any point. The unit of work is "images this brand's live products name
that we have not stored", computed fresh each time, so a pass that is killed halfway
loses nothing but the request in flight.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from backend.archive.budget import HostBudget
from backend.archive.images import ImageStore
from backend.archive.observe import RequestLog
from backend.archive.store.catalog import Catalog
from backend.archive.transport import HttpxTransport
from backend.storage.images import ImageStore as Sink


def _resolve(path: str, db_path: Path) -> Path:
    """An image path recorded by an earlier run.

    Those were written relative to whatever working directory that run had, which in
    practice means the checkout holding the data. Resolve them against the catalogue's
    own location rather than the current directory or the code's: the photographs sit
    beside the database that indexes them, and that stays true wherever the command is
    run from. Getting this wrong is silent — adoption just fails, and 667 photographs we
    already hold get downloaded from the shops a second time.
    """
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    # <root>/backend/archive/data/catalog.db -> <root>
    return db_path.resolve().parents[3] / candidate


@dataclass
class Outcome:
    domain: str
    adopted: int = 0  # already on disk from an earlier run, moved into the store
    fetched: int = 0  # asked the shop for
    outstanding: int = 0  # named by a product and still not stored
    failed: int = 0

    @property
    def stored(self) -> int:
        return self.adopted + self.fetched


def outstanding(catalog: Catalog, domain: str) -> int:
    return sum(len(urls) for _, _, urls in catalog.images_awaiting_archive(domain))


def archive_brand(
    domain: str,
    db_path: Path,
    sink: Sink,
    budget: HostBudget,
    *,
    limit: int = 0,
    width: int | None = None,
) -> Outcome:
    """One brand's outstanding images, into the sink. Its own DB connection, so this is
    safe to run for several brands at once; the host budget is shared, which is the part
    that has to be, or two Shopify stores would double the rate on one CDN."""
    catalog = Catalog(db_path)
    try:
        out = Outcome(domain)
        store = ImageStore(sink, width=width)
        requests = RequestLog(catalog)
        transport = HttpxTransport(sink=requests, budget=budget)
        budgeted = limit or None

        # Bytes we already hold cost nothing and do not touch the shop, so they go first.
        # A file that has since been deleted is not a failure: the fetch loop below still
        # has the URL and will ask for it.
        for product_id, url, path in catalog.local_image_files(domain):
            if budgeted is not None and out.stored >= budgeted:
                break
            if store.adopt(catalog, product_id, domain, url, _resolve(path, db_path)):
                out.adopted += 1

        for product_id, _itemurl, urls in catalog.images_awaiting_archive(domain):
            if budgeted is not None and out.stored >= budgeted:
                break
            if budgeted is not None:
                urls = urls[: budgeted - out.stored]
            stored = store.archive(transport, catalog, product_id, domain, urls)
            out.fetched += stored
            out.failed += len(urls) - stored

        requests.flush()
        out.outstanding = outstanding(catalog, domain)
        return out
    finally:
        catalog.close()


def archive_all(
    domains: list[str],
    db_path: Path,
    sink: Sink,
    *,
    workers: int = 4,
    gap: float = 0.5,
    limit: int = 0,
    width: int | None = None,
    on_done=None,
) -> list[Outcome]:
    budget = HostBudget(gap=gap)
    results: list[Outcome] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                archive_brand, domain, db_path, sink, budget, limit=limit, width=width
            ): domain
            for domain in domains
        }
        for future in as_completed(futures):
            domain = futures[future]
            try:
                outcome = future.result()
            except Exception as error:  # one brand's CDN must not end the pass
                outcome = Outcome(domain, failed=-1)
                print(f"{domain}: {error}")
            results.append(outcome)
            if on_done:
                on_done(outcome)
    return results
