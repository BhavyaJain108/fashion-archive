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
from urllib.parse import urlparse

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
    outstanding: int | None = 0  # named by a product and still not stored; None if unknown
    failed: int = 0

    @property
    def errored(self) -> bool:
        return self.failed == -1

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
    workers: int = 16,
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

        # Every photograph is independent of every other, so the only thing that has
        # to be in order is how fast each host is asked — which the budget owns, not
        # this loop. One at a time was never a requirement, only how it was written.
        jobs = [
            (itemurl, url)
            for itemurl, urls in catalog.images_awaiting_archive(domain)
            for url in urls
        ]
        if budgeted is not None:
            jobs = jobs[:budgeted]
        # The queue is decided; the catalogue that decided it is not needed to fetch
        # anything. Holding psylos1's parsed 35 MB for the length of its pass is most
        # of the machine's 512 MB, and the worker died in that pass rather than
        # fetching a single photograph.
        catalog.release_products(domain)

        # Anything serving this brand's photographs from somewhere other than its own
        # storefront is an asset host, and may be asked faster than a shop.
        shop = {domain.lower(), f"www.{domain.lower()}".removeprefix("www.www.")}
        for host in {urlparse(url).netloc.lower() for _, url in jobs}:
            if host and host not in shop and not host.endswith(f"//{domain}"):
                budget.mark_asset_host(host)
        # In batches rather than one submission of everything: 25,781 pending futures
        # is memory spent before any photograph has been fetched.
        pool_size = max(1, workers)
        with ThreadPoolExecutor(max_workers=pool_size) as pool:
            for start in range(0, len(jobs), pool_size * 8):
                batch = jobs[start : start + pool_size * 8]
                futures = [
                    pool.submit(images.archive_one, transport, catalog, itemurl, domain, url)
                    for itemurl, url in batch
                ]
                for future in as_completed(futures):
                    if future.result():
                        out.fetched += 1
                    else:
                        out.failed += 1

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
                # outstanding is unknown, not zero. Defaulting it to zero let an
                # overnight run where eighteen brands lost the network print
                # "855 stored, 0 still outstanding", which read as finished.
                outcome = Outcome(domain, failed=-1, outstanding=None)
                print(f"{domain}: {error}")
            results.append(outcome)
            if on_done:
                on_done(outcome)
    return results


def summarise(results: list[Outcome]) -> tuple[int, int | None, int]:
    """(stored, outstanding, brands that errored).

    Outstanding is None when any brand failed, because then the backlog is genuinely
    unknown rather than empty — an overnight run that lost the network on eighteen
    brands printed "855 stored, 0 still outstanding", which read as finished.
    """
    errored = sum(1 for r in results if r.errored)
    stored = sum(r.fetched for r in results)
    outstanding = None if errored else sum(r.outstanding or 0 for r in results)
    return stored, outstanding, errored
