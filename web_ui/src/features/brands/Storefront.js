import React, { useEffect, useMemo, useRef, useState } from 'react';
import TopBar from '../../shared/ui/TopBar';
import ArchiveAPI from '../../shared/api/brands';
import { columnsFor, count, fallbackOnError, formatPrice, pageRows, sized } from './shop';
import WindowedGrid from './WindowedGrid';
import { CURRENCIES, useMoney } from '../../shared/money';
import './storefront.css';

// My Brands, laid out like a shop: every designer in one grid, a thin column of
// filters on the left, sort on the right, and the page scrolls. All of the state
// that changes what the grid shows lives in the URL (route.shop and route.brandId),
// so a filtered view is a link and the back button works.

const PAGE = 60;

// What the grid last showed, so coming back from a product lands where you
// left: same tiles, same scroll offset. One entry; a different view replaces it.
let remembered = null;
// Who the shop is being browsed for. A section of the shop rather than a filter chip,
// which is where every shop this page is modelled on puts it. A product whose brand
// sells to everyone appears under both.
const GENDERS = [
  ['women', 'Women'],
  ['men', 'Men'],
];
const SORTS = [
  ['type', 'Type'],
  ['colour', 'Colour'],
  ['latest', 'Latest arrivals'],
  ['price-asc', 'Price: low to high'],
  ['price-desc', 'Price: high to low'],
  ['discount', 'Discount: high to low'],
];

function Storefront({ currentPage, onPageSwitch, currentUser, onLogout, navigate, route }) {
  const shop = route.shop || {};
  const brandId = route.brandId || '';
  const money = useMoney(); // prices in the visitor's currency; re-renders on change
  const [data, setData] = useState(null);      // last answer from the server
  const [tiles, setTiles] = useState([]);      // accumulated across "load more"
  const [state, setState] = useState('loading'); // loading | ready | warming | error
  const [loadingMore, setLoadingMore] = useState(false);
  const heightsRef = useRef({}); // measured row heights, kept across pages and remembered with the grid
  const [designerQuery, setDesignerQuery] = useState('');
  // the price band is typed, so it is only applied on submit — a keystroke is not a query
  const [draftMin, setDraftMin] = useState(shop.price_min || '');
  const [draftMax, setDraftMax] = useState(shop.price_max || '');
  // Rows are formed from same-shaped photographs; the column count is the only
  // thing the browser adds, and it changes only on resize.
  const [columns, setColumns] = useState(() => columnsFor(typeof window === 'undefined' ? 1200 : window.innerWidth));
  useEffect(() => {
    const onResize = () => setColumns(columnsFor(window.innerWidth));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  const [draftQ, setDraftQ] = useState(shop.q || '');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const scrollRef = useRef(null);
  const requestId = useRef(0);

  const key = JSON.stringify([shop, brandId]);

  // Remember the grid on the way out so Back can restore it.
  useEffect(() => {
    const el = scrollRef.current;
    return () => {
      if (data && tiles.length) remembered = { key, data, tiles, heights: heightsRef.current, scrollTop: el ? el.scrollTop : 0 };
    };
  }, [key, data, tiles]);

  // A change of view starts from the top; "load more" appends; the same view,
  // revisited, comes back from memory.
  useEffect(() => {
    let cancelled = false;
    const id = ++requestId.current;
    setDraftQ(shop.q || '');
    setFiltersOpen(false);
    if (remembered && remembered.key === key) {
      setData(remembered.data); setTiles(remembered.tiles); setState('ready');
      heightsRef.current = remembered.heights || {};
      const top = remembered.scrollTop;
      requestAnimationFrame(() => { if (scrollRef.current) scrollRef.current.scrollTop = top; });
      return undefined;
    }
    setState('loading');
    heightsRef.current = {};
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
    const load = async () => {
      try {
        const res = await ArchiveAPI.storefront({ ...shop, brand: brandId, offset: 0, limit: PAGE });
        if (cancelled || id !== requestId.current) return;
        if (res.warming) { setState('warming'); setTimeout(load, 8000); return; }
        setData(res); setTiles(res.products); setState('ready');
      } catch (e) {
        if (!cancelled) setState('error');
      }
    };
    load();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // The next page, asked for by the grid as its last loaded row comes near.
  const loadMore = async () => {
    if (!data || loadingMore) return;
    setLoadingMore(true);
    try {
      const res = await ArchiveAPI.storefront({ ...shop, brand: brandId, offset: tiles.length, limit: PAGE });
      if (res.warming) return;
      setTiles((t) => [...t, ...res.products]); setData(res);
    } catch (e) {
      // the status line stays at "showing n of total"; the next scroll asks again
    } finally {
      setLoadingMore(false);
    }
  };

  const go = (patch, nextBrand = brandId) => {
    const next = { ...shop, ...patch };
    for (const k of Object.keys(next)) if (!next[k]) delete next[k];
    navigate({ page: 'brands', brandId: nextBrand || null, shop: next });
  };
  const openProduct = (t) => navigate({ page: 'product', brandId: t.brand_id, productHandle: t.handle });

  const facets = data?.facets || {
    categories: [], designers: [], colours: [], sale: 0, genders: [], sizes: [], in_stock: 0, price: null,
  };
  const genderCount = (value) => facets.genders.find((g) => g.gender === value)?.count;
  const chosenSizes = (shop.size || '').split(',').filter(Boolean);
  const toggleSize = (size) => {
    const next = chosenSizes.includes(size)
      ? chosenSizes.filter((s) => s !== size)
      : [...chosenSizes, size];
    go({ size: next.join(',') });
  };
  const brandName = brandId ? (facets.designers.find((d) => d.brand_id === brandId)?.name || brandId) : '';
  const designers = designerQuery
    ? facets.designers.filter((d) => d.name.toLowerCase().includes(designerQuery.toLowerCase()))
    : facets.designers;

  const rows = useMemo(() => pageRows(tiles, columns, PAGE), [tiles, columns]);
  // a row's likely height before it is drawn: a 4:5 photograph in the column plus three text lines
  const rowEstimate = Math.round(columnWidth() / 0.8) + 90;
  const heading = brandName || shop.bucket || shop.group || (shop.sale ? 'Sale' : shop.q ? `“${shop.q}”` : 'Everything');
  const total = data ? data.total : 0;

  return (
    <div className="ar-page">
      <TopBar currentPage={currentPage} onPageSwitch={onPageSwitch} currentUser={currentUser} onLogout={onLogout} />
      <div className="shop ar-scroll" ref={scrollRef}>
        {/* the row under the top bar: the shop's own modes */}
        <div className="shop-subnav">
          <div className="shop-modes">
            <button type="button" className={`shop-mode ${!shop.sale && !shop.q && shop.sort !== 'latest' ? 'on' : ''}`} onClick={() => navigate({ page: 'brands', shop: {} })}>Everything</button>
            <button type="button" className={`shop-mode ${shop.sort === 'latest' && !shop.sale ? 'on' : ''}`} onClick={() => go({ sort: 'latest', sale: '' })}>New in</button>
            <button type="button" className={`shop-mode ${shop.sale ? 'on' : ''}`} onClick={() => go({ sale: shop.sale ? '' : '1' })}>Sale</button>
            <span className="shop-modes-split" aria-hidden="true" />
            {GENDERS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`shop-mode ${shop.gender === value ? 'on' : ''}`}
                title={genderCount(value) === undefined ? undefined : `${count(genderCount(value))} pieces`}
                onClick={() => go({ gender: shop.gender === value ? '' : value })}
              >
                {label}
              </button>
            ))}
          </div>
          <form className="shop-searchform" onSubmit={(e) => { e.preventDefault(); go({ q: draftQ.trim() }); }}>
            <input className="ar-input shop-search" placeholder="Search" value={draftQ} onChange={(e) => setDraftQ(e.target.value)} />
          </form>
          <button type="button" className={`shop-mode shop-filters-toggle ${filtersOpen ? 'on' : ''}`} onClick={() => setFiltersOpen((o) => !o)} aria-expanded={filtersOpen}>
            Filters {filtersOpen ? '▴' : '▾'}
          </button>
        </div>

        <div className={`shop-body ${filtersOpen ? 'filters-open' : ''}`}>
          {/* left column */}
          <aside className="shop-left">
            <button type="button" className={`shop-check ${shop.sale ? 'on' : ''}`} onClick={() => go({ sale: shop.sale ? '' : '1' })}>
              <span className="shop-box" aria-hidden="true">{shop.sale ? '■' : '□'}</span> Sale <span className="shop-count">{count(facets.sale)}</span>
            </button>
            <button type="button" className={`shop-check ${shop.in_stock ? 'on' : ''}`} onClick={() => go({ in_stock: shop.in_stock ? '' : '1' })}>
              <span className="shop-box" aria-hidden="true">{shop.in_stock ? '■' : '□'}</span> In stock <span className="shop-count">{count(facets.in_stock)}</span>
            </button>

            {facets.sizes.length > 0 && (
              <div>
                <div className="shop-h">Size</div>
                <div className="shop-sizes">
                  {facets.sizes.map((s) => (
                    <button
                      key={s.size}
                      type="button"
                      title={`${count(s.count)} to buy in ${s.size}`}
                      className={`shop-size ${chosenSizes.includes(s.size) ? 'on' : ''}`}
                      onClick={() => toggleSize(s.size)}
                    >
                      {s.size}
                    </button>
                  ))}
                </div>
                {chosenSizes.length > 0 && (
                  <button type="button" className="shop-link" onClick={() => go({ size: '' })}>Any size</button>
                )}
              </div>
            )}

            {facets.price && (
              <div>
                <div className="shop-h">Price</div>
                <form
                  className="shop-price"
                  onSubmit={(e) => { e.preventDefault(); go({ price_min: draftMin.trim(), price_max: draftMax.trim() }); }}
                >
                  <input className="ar-input shop-price-input" inputMode="numeric" placeholder={Math.floor(facets.price.min)} value={draftMin} onChange={(e) => setDraftMin(e.target.value)} aria-label="Lowest price" />
                  <span aria-hidden="true">–</span>
                  <input className="ar-input shop-price-input" inputMode="numeric" placeholder={Math.ceil(facets.price.max)} value={draftMax} onChange={(e) => setDraftMax(e.target.value)} aria-label="Highest price" />
                  <button type="submit" className="shop-link">Go</button>
                </form>
              </div>
            )}

            <div className="shop-h">Categories</div>
            <ul className="shop-list">
              {facets.categories.map((g) => (
                <li key={g.group}>
                  <button type="button" className={`shop-link ${shop.group === g.group && !shop.bucket ? 'on' : ''}`} onClick={() => go({ group: shop.group === g.group ? '' : g.group, bucket: '' })}>
                    {g.group} <span className="shop-count">{count(g.count)}</span>
                  </button>
                  {shop.group === g.group && (
                    <ul className="shop-list shop-sub">
                      {g.buckets.map((b) => (
                        <li key={b.bucket}>
                          <button type="button" className={`shop-link ${shop.bucket === b.bucket ? 'on' : ''}`} onClick={() => go({ bucket: shop.bucket === b.bucket ? '' : b.bucket })}>
                            {b.bucket} <span className="shop-count">{count(b.count)}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>

            <div className="shop-h">Designers</div>
            {brandId && (
              <button type="button" className="shop-link shop-back" onClick={() => go({}, '')}>← All designers</button>
            )}
            <input className="ar-input shop-designer-search" placeholder="Search designers" value={designerQuery} onChange={(e) => setDesignerQuery(e.target.value)} />
            <ul className="shop-list">
              {designers.map((d) => (
                <li key={d.brand_id}>
                  <button type="button" className={`shop-link ${brandId === d.brand_id ? 'on' : ''}`} onClick={() => go({}, brandId === d.brand_id ? '' : d.brand_id)}>
                    {d.name} <span className="shop-count">{count(d.count)}</span>
                  </button>
                </li>
              ))}
              {designers.length === 0 && <li className="shop-none">No designer matches</li>}
            </ul>
          </aside>

          {/* the grid */}
          <main className="shop-main">
            <div className="shop-heading">
              <h1 className="shop-title">{heading}</h1>
              <span className="shop-total">{state === 'ready' ? `${count(total)} products` : ''}</span>
            </div>
            {state === 'warming' && (
              <div className="ar-loading"><span className="headline">Filling the shop front</span><span>Copying every brand's catalogue into the database. A few minutes, once; this page refreshes itself.</span></div>
            )}
            {state === 'error' && (
              <div className="ar-empty"><span className="headline">The shop could not be read</span><span>Try again in a moment.</span></div>
            )}
            {state === 'ready' && tiles.length === 0 && (
              <div className="ar-empty"><span className="headline">Nothing here</span><span>Clear a filter or search for something else.</span></div>
            )}
            <div className={state === 'loading' ? 'is-loading' : ''}>
              <WindowedGrid
                rows={rows}
                scrollRef={scrollRef}
                heightsRef={heightsRef}
                estimate={rowEstimate}
                hasMore={state === 'ready' && tiles.length < total}
                onMore={loadMore}
                renderRow={(row) => row.map((t) => <Tile key={`${t.brand_id}|${t.url}`} tile={t} onOpen={() => openProduct(t)} />)}
              />
            </div>
            {state === 'ready' && tiles.length > 0 && (
              <div className="shop-more">
                <span className="shop-total">
                  {tiles.length < total ? `Showing ${count(tiles.length)} of ${count(total)}${loadingMore ? ' · loading' : ''}` : `${count(total)} products`}
                </span>
              </div>
            )}
          </main>

          {/* right column */}
          <aside className="shop-right">
            <div className="shop-h">Currency</div>
            <select className="ar-select shop-currency" aria-label="Currency" value={money.currency} onChange={(e) => money.setCurrency(e.target.value)}>
              {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <div className="shop-h">Sort</div>
            <ul className="shop-list">
              {SORTS.map(([v, label]) => (
                <li key={v}><button type="button" className={`shop-link ${(shop.sort || 'type') === v ? 'on' : ''}`} onClick={() => go({ sort: v })}>{label}</button></li>
              ))}
            </ul>
            {facets.colours.length > 0 && (
              <>
                <div className="shop-h">Colours</div>
                <ul className="shop-list">
                  <li><button type="button" className={`shop-link ${!shop.colour ? 'on' : ''}`} onClick={() => go({ colour: '' })}>All colours</button></li>
                  {facets.colours.map((c) => (
                    <li key={c.colour}><button type="button" className={`shop-link ${shop.colour === c.colour ? 'on' : ''}`} onClick={() => go({ colour: shop.colour === c.colour ? '' : c.colour })}>{c.colour} <span className="shop-count">{count(c.count)}</span></button></li>
                  ))}
                </ul>
              </>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}

// The widest a grid column gets at each layout, so the request matches the paint.
function columnWidth() {
  if (typeof window === 'undefined') return 400;
  const w = window.innerWidth;
  if (w >= 1700) return (w - 48 - 392) / 4;
  if (w >= 1100) return (w - 48 - 392) / 3;
  if (w >= 700) return (w - 48) / 3;
  return (w - 32) / 2;
}

export function Tile({ tile, onOpen }) {
  const width = columnWidth();
  const src = sized(tile.image, width);
  // The second photograph is fetched on the first hover, never with the grid:
  // loading it for every tile doubled the pictures a page pulls.
  const [wanted, setWanted] = useState(false);
  const alt = wanted && tile.image2 ? sized(tile.image2, width) : null;
  return (
    <button type="button" className="shop-tile" onClick={onOpen} onMouseEnter={() => setWanted(true)}>
      <span className={`shop-tile-img ${tile.ratio ? 'has-shape' : ''}`} style={tile.ratio ? { aspectRatio: String(tile.ratio) } : undefined}>
        {src ? <img src={src} alt="" loading="lazy" onError={fallbackOnError(tile.archived)} /> : <span className="shop-tile-none">No image</span>}
        {src && alt && <img className="shop-tile-alt" src={alt} alt="" />}
      </span>
      <span className="shop-tile-text">
        <span className="shop-tile-brand">{tile.brand}</span>
        <span className="shop-tile-name">{tile.title}</span>
        <span className="shop-tile-price">
          {tile.price !== null && tile.price !== undefined ? formatPrice(tile.price, tile.currency) : <span className="shop-tile-noprice">Price on site</span>}
          {tile.sale && <span className="shop-tile-strike">{formatPrice(tile.full_price, tile.currency)}</span>}
        </span>
      </span>
    </button>
  );
}

export default Storefront;
