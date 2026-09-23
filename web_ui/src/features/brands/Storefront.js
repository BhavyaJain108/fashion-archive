import React, { useEffect, useRef, useState } from 'react';
import TopBar from '../../shared/ui/TopBar';
import ArchiveAPI from '../../shared/api/brands';
import { formatPrice, count, fallbackOnError } from './shop';
import './storefront.css';

// My Brands, laid out like a shop: every designer in one grid, a thin column of
// filters on the left, sort on the right, and the page scrolls. All of the state
// that changes what the grid shows lives in the URL (route.shop and route.brandId),
// so a filtered view is a link and the back button works.

const PAGE = 60;
const SORTS = [
  ['latest', 'Latest arrivals'],
  ['price-asc', 'Price: low to high'],
  ['price-desc', 'Price: high to low'],
  ['discount', 'Discount: high to low'],
];

function Storefront({ currentPage, onPageSwitch, currentUser, onLogout, navigate, route }) {
  const shop = route.shop || {};
  const brandId = route.brandId || '';
  const [data, setData] = useState(null);      // last answer from the server
  const [tiles, setTiles] = useState([]);      // accumulated across "load more"
  const [state, setState] = useState('loading'); // loading | ready | warming | error
  const [designerQuery, setDesignerQuery] = useState('');
  const [draftQ, setDraftQ] = useState(shop.q || '');
  const scrollRef = useRef(null);
  const requestId = useRef(0);

  const key = JSON.stringify([shop, brandId]);

  // A change of view starts from the top; "load more" appends.
  useEffect(() => {
    let cancelled = false;
    const id = ++requestId.current;
    setState('loading');
    setDraftQ(shop.q || '');
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

  const loadMore = async () => {
    if (!data) return;
    const res = await ArchiveAPI.storefront({ ...shop, brand: brandId, offset: tiles.length, limit: PAGE });
    if (res.warming) return;
    setTiles((t) => [...t, ...res.products]); setData(res);
  };

  const go = (patch, nextBrand = brandId) => {
    const next = { ...shop, ...patch };
    for (const k of Object.keys(next)) if (!next[k]) delete next[k];
    navigate({ page: 'brands', brandId: nextBrand || null, shop: next });
  };
  const openProduct = (t) => navigate({ page: 'product', brandId: t.brand_id, productHandle: t.handle });

  const facets = data?.facets || { categories: [], designers: [], colours: [], sale: 0 };
  const brandName = brandId ? (facets.designers.find((d) => d.brand_id === brandId)?.name || brandId) : '';
  const designers = designerQuery
    ? facets.designers.filter((d) => d.name.toLowerCase().includes(designerQuery.toLowerCase()))
    : facets.designers;

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
          </div>
          <form className="shop-searchform" onSubmit={(e) => { e.preventDefault(); go({ q: draftQ.trim() }); }}>
            <input className="ar-input shop-search" placeholder="Search" value={draftQ} onChange={(e) => setDraftQ(e.target.value)} />
          </form>
        </div>

        <div className="shop-body">
          {/* left column */}
          <aside className="shop-left">
            <button type="button" className={`shop-check ${shop.sale ? 'on' : ''}`} onClick={() => go({ sale: shop.sale ? '' : '1' })}>
              <span className="shop-box" aria-hidden="true">{shop.sale ? '■' : '□'}</span> Sale <span className="shop-count">{count(facets.sale)}</span>
            </button>

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
              <div className="ar-loading"><span className="headline">Building the shop front</span><span>Reading every brand's catalogue. About a minute, once.</span></div>
            )}
            {state === 'error' && (
              <div className="ar-empty"><span className="headline">The shop could not be read</span><span>Try again in a moment.</span></div>
            )}
            {state === 'ready' && tiles.length === 0 && (
              <div className="ar-empty"><span className="headline">Nothing here</span><span>Clear a filter or search for something else.</span></div>
            )}
            <div className={`shop-grid ${state === 'loading' ? 'is-loading' : ''}`}>
              {tiles.map((t) => <Tile key={`${t.brand_id}|${t.url}`} tile={t} onOpen={() => openProduct(t)} />)}
            </div>
            {state === 'ready' && tiles.length < total && (
              <div className="shop-more">
                <span className="shop-total">Showing {count(tiles.length)} of {count(total)}</span>
                <button type="button" className="ar-btn" onClick={loadMore}>Load more</button>
              </div>
            )}
          </main>

          {/* right column */}
          <aside className="shop-right">
            <div className="shop-h">Sort</div>
            <ul className="shop-list">
              {SORTS.map(([v, label]) => (
                <li key={v}><button type="button" className={`shop-link ${(shop.sort || 'latest') === v ? 'on' : ''}`} onClick={() => go({ sort: v })}>{label}</button></li>
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

export function Tile({ tile, onOpen }) {
  const [hover, setHover] = useState(false);
  const src = hover && tile.image2 ? tile.image2 : tile.image;
  return (
    <button type="button" className="shop-tile" onClick={onOpen} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <span className="shop-tile-img">
        {src ? <img src={src} alt="" loading="lazy" onError={fallbackOnError(tile.archived)} /> : <span className="shop-tile-none">No image</span>}
      </span>
      <span className="shop-tile-brand">{tile.brand}</span>
      <span className="shop-tile-name">{tile.title}</span>
      <span className="shop-tile-price">
        {tile.price !== null && tile.price !== undefined ? formatPrice(tile.price, tile.currency) : <span className="shop-tile-noprice">Price on site</span>}
        {tile.sale && <span className="shop-tile-strike">{formatPrice(tile.full_price, tile.currency)}</span>}
      </span>
    </button>
  );
}

export default Storefront;
