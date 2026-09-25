import React, { useEffect, useState } from 'react';
import TopBar from '../../shared/ui/TopBar';
import ArchiveAPI from '../../shared/api/brands';
import { Tile } from './Storefront';
import JustifiedGrid from './JustifiedGrid';
import { formatPrice, shopFigure, fallbackOnError, sized } from './shop';
import { useMoney } from '../../shared/money';
import './storefront.css';

// One product: its photographs stacked on the left, the facts pinned on the right,
// and eight more from the same brand underneath. The archive does not sell, so
// the one action is opening the shop's own page. Saving a product is not wired:
// the library has no favourite kind for products yet.

function ProductPage({ currentPage, onPageSwitch, currentUser, onLogout, navigate, brandId, handle }) {
  const money = useMoney();
  const [res, setRes] = useState(undefined); // undefined loading, null missing

  useEffect(() => {
    let cancelled = false;
    setRes(undefined);
    const load = async () => {
      try {
        const r = await ArchiveAPI.product(brandId, handle);
        if (cancelled) return;
        if (r && r.warming) { setTimeout(load, 8000); return; }
        setRes(r);
      } catch { if (!cancelled) setRes(null); }
    };
    load();
    return () => { cancelled = true; };
  }, [brandId, handle]);

  const back = () => navigate({ page: 'brands', brandId, shop: {} });
  const openTile = (t) => navigate({ page: 'product', brandId: t.brand_id, productHandle: t.handle });

  let body;
  if (res === undefined) body = <div className="ar-loading"><span className="headline">Loading</span></div>;
  else if (res === null) body = <div className="ar-empty"><span className="headline">Not in the archive</span><span>This product is no longer in the catalogue.</span></div>;
  else {
    const { tile: t, more } = res;
    const images = t.images && t.images.length ? t.images : (t.image ? [t.image] : []);
    const desc = String(t.description || '').split(/\n+|(?<=\.)\s+(?=[A-Z])/).map((x) => x.trim()).filter(Boolean);
    // The column is 640px wide on a desktop and the viewport's width below 1100px.
    const imgW = typeof window !== 'undefined' && window.innerWidth < 1100 ? Math.min(640, window.innerWidth - 32) : 640;
    body = (
      <>
        <div className="shop-product">
          <div className="shop-product-images">
            {(images.length ? images : [null]).map((u, i) => (
              <div className="shop-product-img" key={u || i}>
                {u ? <img src={sized(u, imgW)} alt="" loading={i === 0 ? 'eager' : 'lazy'} onError={fallbackOnError(t.archived)} /> : <span className="shop-tile-none">No image</span>}
              </div>
            ))}
          </div>
          <aside className="shop-product-info">
            <button type="button" className="shop-link shop-back" onClick={back}>← {t.brand}</button>
            <div className="shop-product-brand">{t.brand}</div>
            <h1 className="shop-product-name">{t.title}</h1>
            <div className="shop-product-price">
              {t.price !== null ? formatPrice(t.price, t.currency) : 'Price on the brand site'}
              {t.sale && <span className="shop-tile-strike">{formatPrice(t.full_price, t.currency)}</span>}
              {t.price !== null && t.currency && t.currency !== money.currency && (
                <span className="shop-product-shopprice"> · {shopFigure(t.price, t.currency)} at the shop</span>
              )}
              {t.sale && <span className="shop-product-off">{Math.round(t.discount * 100)}% off</span>}
            </div>
            {t.sizes.length > 0 && (
              <div className="shop-sizes">
                {t.sizes.map((s) => <span key={s.size} className={`shop-size ${s.available ? '' : 'gone'}`}>{s.size}</span>)}
              </div>
            )}
            <a className="ar-btn active ar-btn-block shop-open" href={t.url} target="_blank" rel="noopener noreferrer">Open on brand site ↗</a>
            <div className="shop-h">Item info</div>
            <ul className="shop-facts">
              {desc.slice(0, 8).map((d, i) => <li key={i}>{d}</li>)}
              {t.material && <li>{t.material}</li>}
              {t.colour && <li>Colour: {t.colour}</li>}
              {t.colour_text && t.colour_text !== t.colour && <li>Shop colour: {t.colour_text}</li>}
              <li>{t.group} · {t.bucket}</li>
              {t.code && <li>{t.code}</li>}
            </ul>
            <div className="shop-h">In the archive</div>
            <ul className="shop-facts shop-facts-quiet">
              {t.first_seen && <li>First seen {t.first_seen}</li>}
              {t.last_seen && <li>Last read {t.last_seen}</li>}
              <li>{t.in_stock ? 'In stock at last read' : 'Stock unknown at last read'}</li>
            </ul>
          </aside>
        </div>
        {more && more.length > 0 && (
          <div className="shop-more-from">
            <div className="shop-h">More from {t.brand}</div>
            <JustifiedGrid items={more} keyOf={(m) => `${m.brand_id}|${m.url}`} renderTile={(m, box) => <Tile tile={m} box={box} onOpen={() => openTile(m)} />} />
          </div>
        )}
      </>
    );
  }

  return (
    <div className="ar-page">
      <TopBar currentPage={currentPage} onPageSwitch={onPageSwitch} currentUser={currentUser} onLogout={onLogout} />
      <div className="shop ar-scroll">{body}</div>
    </div>
  );
}

export default ProductPage;
