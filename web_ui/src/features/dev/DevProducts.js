import React, { useState } from 'react';

import DevEndpoints from '../../shared/api/dev';
import useDevLoad, { Gate } from './useDevLoad';
import { ago, dateShort, n } from './format';

const PAGE = 100;
const STATUSES = [['live', 'on the site'], ['gone', 'removed'], ['all', 'everything']];

// The catalogue as stored, a page at a time. This is the one large read in the
// machine room — the server cuts the page and lets the catalogue go — so it is
// its own view rather than a panel on the brand page. Every product carries when
// it was added, when it was last scraped, and — if it has gone — when it was last
// on the site; the filter chooses between what is there now and what has left.
export default function DevProducts({ domain }) {
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState('');
  const [typed, setTyped] = useState('');
  const [status, setStatus] = useState('live');
  const { data, state } = useDevLoad(
    () => DevEndpoints.getProducts(domain, { offset, limit: PAGE, q, status }),
    [domain, offset, q, status],
  );

  const search = (e) => {
    e.preventDefault();
    setOffset(0);
    setQ(typed.trim());
  };

  return (
    <>
      <div className="dev-head">
        <h1 className="dev-title">Catalogue</h1>
        <div className="dev-head-actions" role="group" aria-label="Which products">
          {STATUSES.map(([key, label]) => (
            <button
              type="button"
              key={key}
              className={`dev-act${status === key ? ' selected' : ''}`}
              aria-pressed={status === key}
              onClick={() => { setStatus(key); setOffset(0); }}
            >
              {label}
            </button>
          ))}
        </div>
        <form className="dev-search" onSubmit={search}>
          <input
            className="ar-input"
            type="search"
            placeholder="TITLE"
            aria-label="Filter by title"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
          <button type="submit" className="dev-act">filter</button>
        </form>
      </div>
      <Gate state={state}>
        {data && (
          <>
            <div className="dev-stamp">
              {n(data.total)} product{data.total === 1 ? '' : 's'}
              {q ? ` matching “${q}”` : ''} · showing {data.total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, data.total)}
            </div>
            <ol className="dev-products">
              {data.products.map((p) => {
                const images = p.images && p.images.length ? p.images : [p.main_image_url].filter(Boolean);
                const price = p.price == null ? null : `${p.price}${p.currency ? ` ${p.currency}` : ''}`;
                const facts = [
                  p.product_code,
                  price && (p.full_price != null && p.full_price !== p.price ? `${price} (was ${p.full_price})` : price),
                  p.in_stock == null ? null : p.in_stock ? 'in stock' : 'out of stock',
                  [p.category1, p.category2].filter(Boolean).join(' / ') || null,
                ].filter(Boolean);
                return (
                  <li className="dev-product" key={p.itemurl}>
                    <div className="dev-product-facts">
                      <a className="dev-product-title" href={p.itemurl} target="_blank" rel="noreferrer">
                        {p.product_title || <span className="dev-muted">untitled</span>}
                      </a>
                      <div className="dev-domain">{facts.join(' · ')}</div>
                      {p.size_info && <div className="dev-domain">sizes {p.size_info}</div>}
                      {p.color_info && <div className="dev-domain">colour {p.color_info}</div>}
                      <div className="dev-domain">{images.length} photograph{images.length === 1 ? '' : 's'}</div>
                      <div className="dev-domain">
                        added {dateShort(p.first_seen)} · last scraped {ago(p.last_seen)}
                        {p.live === false && (
                          <span className="dev-strong"> · gone — last on the site {dateShort(p.last_on_site)}</span>
                        )}
                      </div>
                    </div>
                    {images.length === 0 ? (
                      <div className="dev-strip dev-strip-none" aria-hidden="true" />
                    ) : (
                      <div className="dev-strip">
                        {images.map((u, i) => (
                          <a key={u + i} href={u} target="_blank" rel="noreferrer">
                            <img src={u} alt="" loading="lazy" />
                          </a>
                        ))}
                      </div>
                    )}
                  </li>
                );
              })}
            </ol>
            <div className="dev-pager">
              <button type="button" className="dev-act" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                ← previous
              </button>
              <button type="button" className="dev-act" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
                next →
              </button>
            </div>
          </>
        )}
      </Gate>
    </>
  );
}
