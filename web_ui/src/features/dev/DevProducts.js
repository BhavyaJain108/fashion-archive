import React, { useState } from 'react';

import DevEndpoints from '../../shared/api/dev';
import useDevLoad, { Gate } from './useDevLoad';
import { n } from './format';

const PAGE = 100;

// The catalogue as stored, a page at a time. This is the one large read in the
// machine room — the server cuts the page and lets the catalogue go — so it is
// its own view rather than a panel on the brand page.
export default function DevProducts({ domain }) {
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState('');
  const [typed, setTyped] = useState('');
  const { data, state } = useDevLoad(
    () => DevEndpoints.getProducts(domain, { offset, limit: PAGE, q }),
    [domain, offset, q],
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
            <div className="dev-scroll">
              <table className="dev-table dev-products">
                <thead>
                  <tr>
                    <th></th>
                    <th>Product</th>
                    <th>Code</th>
                    <th className="n">Price</th>
                    <th>Stock</th>
                    <th>Sizes</th>
                    <th>Colour</th>
                    <th>Category</th>
                  </tr>
                </thead>
                <tbody>
                  {data.products.map((p) => (
                    <tr key={p.itemurl}>
                      <td>
                        {p.main_image_url ? (
                          <img className="dev-thumb" src={p.main_image_url} alt="" loading="lazy" />
                        ) : (
                          <span className="dev-thumb dev-thumb-none" aria-hidden="true" />
                        )}
                      </td>
                      <td>
                        <a className="dev-product-title" href={p.itemurl} target="_blank" rel="noreferrer">
                          {p.product_title || <span className="dev-muted">untitled</span>}
                        </a>
                        {p.brand && <div className="dev-domain">{p.brand}</div>}
                      </td>
                      <td className="dev-mono">{p.product_code || '—'}</td>
                      <td className="n">
                        {p.price == null ? '—' : `${p.price}${p.currency ? ` ${p.currency}` : ''}`}
                        {p.full_price != null && p.full_price !== p.price && (
                          <div className="dev-muted">was {p.full_price}</div>
                        )}
                      </td>
                      <td>{p.in_stock == null ? '—' : p.in_stock ? 'in' : 'out'}</td>
                      <td className="dev-wrap">{p.size_info || '—'}</td>
                      <td className="dev-wrap">{p.color_info || '—'}</td>
                      <td className="dev-wrap">{[p.category1, p.category2].filter(Boolean).join(' / ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
