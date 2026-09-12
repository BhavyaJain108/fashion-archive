"""The image pass: fetch every photograph a brand's products name, and keep the bytes.

Separate from scraping on purpose. A scrape reads a catalogue and should finish in
minutes; fetching 30,000 photographs takes hours and wants a different pace, so making
one wait on the other would mean either slow scrapes or a thin archive. The two meet in
the store: a scrape records the image URLs, and this walks what is recorded.

Re-runnable at any point. The unit of work is "images this brand's live products name
that we have not stored", computed fresh each time, so a pass that is killed halfway
loses nothing but the request in flight.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from backend.archive.budget import HostBudget
from backend.archive.images import ImageStore
from backend.archive.observe import RequestLog
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import ObjectStore
from backend.archive.transport import HttpxTransport
from backend.storage.images import ImageStore as Sink


@dataclass
class Outcome:
    domain: str
    fetched: int = 0  # asked the shop for
    outstanding: int = 0  # named by a product and still not stored
    failed: int = 0

    @property
    def stored(self) -> int:
        return self.fetched


def outstanding(catalog: Catalog, domain: str) -> int:
    return sum(len(urls) for _, urls in catalog.images_awaiting_archive(domain))


def archive_brand(
    domain: str,
    store: ObjectStore,
    sink: Sink,
    budget: HostBudget,
    *,
    limit: int = 0,
    width: int | None = None,
) -> Outcome:
    """One brand's outstanding images, into the sink.

    Its own catalogue handle, so this is safe to run for several brands at once; the
    host budget is shared, which is the part that has to be, or two Shopify stores
    would double the rate on one CDN.
    """
    catalog = Catalog(store)
    try:
        out = Outcome(domain)
        images = ImageStore(sink, width=width)
        requests = RequestLog(catalog)
        transport = HttpxTransport(sink=requests, budget=budget)
        budgeted = limit or None

        for itemurl, urls in catalog.images_awaiting_archive(domain):
            if budgeted is not None and out.stored >= budgeted:
                break
            if budgeted is not None:
                urls = urls[: budgeted - out.stored]
            stored = images.archive(transport, catalog, itemurl, domain, urls)
            out.fetched += stored
            out.failed += len(urls) - stored

        requests.flush()
        out.outstanding = outstanding(catalog, domain)
        return out
    finally:
        catalog.close()


def archive_all(
    domains: list[str],
    store: ObjectStore,
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
                archive_brand, domain, store, sink, budget, limit=limit, width=width
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
