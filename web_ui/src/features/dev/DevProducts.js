import React, { useState } from 'react';

import DevEndpoints from '../../shared/api/dev';
import useDevLoad, { Gate } from './useDevLoad';
import { ago, dateShort, n } from './format';

const PAGE = 100;
// The order the facets are shown in, and their labels. What a brand's own filter
// bar offers, in the brand's own words; a facet with nothing to offer is not shown.
// `type` leads: it is the archive's own word for the thing, the one label that means
// the same on every brand. Everything after it is the brand's own vocabulary.
const FACET_ORDER = [
  ['type', 'type'], ['category', 'category'], ['colour', 'colour'], ['size', 'size'],
  ['material', 'material'], ['stock', 'stock'], ['sale', 'price'], ['tag', 'tag'],
];

// One facet: its values as chips with counts. Clicking toggles a value; a chip
// says how many products it would leave under the other facets' choices.
function Facet({ name, label, items, onToggle }) {
  if (!items || !items.length) return null;
  return (
    <div className="dev-facet" role="group" aria-label={label}>
      <span className="dev-facet-k">{label}</span>
      <div className="dev-facet-values">
        {items.map((it) => (
          <button
            type="button"
            key={it.value}
            className={`ar-chip${it.selected ? ' selected' : ''}`}
            aria-pressed={it.selected}
            onClick={() => onToggle(name, it.value)}
          >
            {it.value}
            <span className="dev-facet-n">
              {' '}{n(it.count)}
              {name === 'size' && it.in_stock != null && it.in_stock !== it.count ? ` (${n(it.in_stock)} in stock)` : ''}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

const STATUSES = [['live', 'on the site'], ['gone', 'removed'], ['all', 'everything']];
const RUN_STATUSES = [['live', 'present then'], ['added', 'added in it'], ['gone', 'removed at it'], ['all', 'seen by then']];

// The catalogue as stored, a page at a time. This is the one large read in the
// machine room — the server cuts the page and lets the catalogue go — so it is
// its own view rather than a panel on the brand page. Every product carries when
// it was added, when it was last scraped, and — if it has gone — when it was last
// on the site; the filter chooses between what is there now and what has left.
//
// "As of a run" is the same catalogue read through those stamps — nothing is
// stored per run. Present at run R: first seen no later than R, last on the site
// no earlier. Added: first seen in R. Removed: last on the site in the run before.
export default function DevProducts({ domain, run = null, go }) {
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState('');
  const [typed, setTyped] = useState('');
  const [status, setStatus] = useState('live');
  const [filters, setFilters] = useState({});
  const [sizedInStock, setSizedInStock] = useState(false);
  const [priceMin, setPriceMin] = useState('');
  const [priceMax, setPriceMax] = useState('');
  const [priceTyped, setPriceTyped] = useState(['', '']);
  const { data, state } = useDevLoad(
    () => DevEndpoints.getProducts(domain, { offset, limit: PAGE, q, status, run, filters, sizedInStock, priceMin, priceMax }),
    [domain, offset, q, status, run, filters, sizedInStock, priceMin, priceMax],
  );
  const chosen = Object.values(filters).reduce((a, v) => a + v.length, 0) + (priceMin || priceMax ? 1 : 0);

  const toggle = (facet, value) => {
    setOffset(0);
    setFilters((f) => {
      const have = f[facet] || [];
      const next = have.includes(value) ? have.filter((v) => v !== value) : [...have, value];
      const out = { ...f, [facet]: next };
      if (!next.length) delete out[facet];
      return out;
    });
  };
  const clear = () => {
    setOffset(0);
    setFilters({});
    setSizedInStock(false);
    setPriceMin('');
    setPriceMax('');
    setPriceTyped(['', '']);
  };
  const applyPrice = (e) => {
    e.preventDefault();
    setOffset(0);
    setPriceMin(priceTyped[0].trim());
    setPriceMax(priceTyped[1].trim());
  };
  const choices = run ? RUN_STATUSES : STATUSES;

  const pickRun = (id) => {
    setOffset(0);
    if (status === 'added' && !id) setStatus('live');
    go({ brandId: domain, category: 'products', token: id || null });
  };

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
          <select
            className="ar-select"
            aria-label="As of which run"
            value={run || ''}
            onChange={(e) => pickRun(e.target.value)}
          >
            <option value="">as of now</option>
            {(data ? data.runs : []).map((r) => (
              <option key={r.id} value={r.id}>as of {dateShort(r.at)} {r.at.slice(11, 16)} · {r.mode}</option>
            ))}
          </select>
          {choices.map(([key, label]) => (
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
              {run ? ` as of the run of ${dateShort(run)}` : ''}
              {q ? ` matching “${q}”` : ''}
              {chosen ? ` under ${chosen} filter${chosen === 1 ? '' : 's'}` : ''}
              {' '}· showing {data.total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, data.total)}
            </div>
            <div className="dev-facets">
              {FACET_ORDER.map(([name, label]) => (
                <Facet key={name} name={name} label={label} items={data.facets && data.facets[name]} onToggle={toggle} />
              ))}
              {filters.size && filters.size.length > 0 && (
                <label className="dev-check dev-facet-opt">
                  <input type="checkbox" checked={sizedInStock} onChange={(e) => { setOffset(0); setSizedInStock(e.target.checked); }} />
                  {' '}only where that size is in stock
                </label>
              )}
              {data.price_range && (
                <form className="dev-facet dev-facet-price" onSubmit={applyPrice}>
                  <span className="dev-facet-k">price {data.price_range.min}–{data.price_range.max}</span>
                  <input className="ar-input" type="number" step="any" placeholder="MIN" aria-label="Minimum price" value={priceTyped[0]} onChange={(e) => setPriceTyped([e.target.value, priceTyped[1]])} />
                  <input className="ar-input" type="number" step="any" placeholder="MAX" aria-label="Maximum price" value={priceTyped[1]} onChange={(e) => setPriceTyped([priceTyped[0], e.target.value])} />
                  <button type="submit" className="dev-act">apply</button>
                </form>
              )}
              {chosen > 0 && (
                <button type="button" className="dev-act" onClick={clear}>clear filters</button>
              )}
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
                  p.material_info || null,
                ].filter(Boolean);
                return (
                  <li className="dev-product" key={p.itemurl}>
                    <div className="dev-product-facts">
                      <a className="dev-product-title" href={p.itemurl} target="_blank" rel="noreferrer">
                        {p.product_title || <span className="dev-muted">untitled</span>}
                      </a>
                      <div className="dev-domain">{facts.join(' · ')}</div>
                      {p.archive_type && <div className="dev-domain">type {p.archive_type}</div>}
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
