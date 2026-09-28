// Small helpers the shop front and the product page share.

import { showPrice, shopPrice } from '../../shared/money';

// A price reads in the visitor's currency, converted with the day's rates and
// marked approximate; the shop's own figure is what the card is charged.
export function formatPrice(value, currency = 'USD') {
  if (value === null || value === undefined) return '';
  return showPrice(value, currency);
}

export function shopFigure(value, currency = 'USD') {
  if (value === null || value === undefined) return '';
  return shopPrice(value, currency);
}

export const count = (n) => Number(n || 0).toLocaleString('en-US');

// The shop's CDN is the live copy and can stop resolving; the archive kept bytes
// for some products, so a dead image falls back to ours before it goes blank.
export function fallbackOnError(archived = []) {
  return (e) => {
    const img = e.currentTarget;
    const next = (archived || []).find((u) => u !== img.getAttribute('src'));
    if (next) img.src = next;
    else img.style.visibility = 'hidden';
  };
}

// The shop's CDN can resize on request. Ask for the width the display will
// actually paint — the column's CSS width times the device pixel ratio, rounded
// up to a step so caches hit — instead of the 2000px original for every tile.
export function sized(url, cssWidth) {
  if (!url || typeof url !== 'string') return url;
  if (!/cdn\.shopify\.com/.test(url)) return url;
  const dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
  const px = Math.min(2400, Math.ceil((cssWidth * dpr) / 200) * 200);
  const base = url.replace(/([?&])width=\d+&?/, '$1').replace(/[?&]$/, '');
  return `${base}${base.includes('?') ? '&' : '?'}width=${px}`;
}

// How many photographs share a row at this viewport width. Matches storefront.css:
// four from 1700px, three down to 700px, two below.
export function columnsFor(width) {
  if (width >= 1700) return 4;
  if (width >= 700) return 3;
  return 2;
}

// A photograph's shape, coarse enough that 3:4 and 3:4-ish land together.
export function shapeKey(tile) {
  return tile.ratio ? Math.round(tile.ratio * 20) / 20 : null;
}

// Same-shaped photographs on the same row, moving pictures only a little: a row
// takes its first picture's shape, then pulls matches from the next `look` rows'
// worth of pictures. Whatever is left keeps its order, so a mixed row happens only
// when there is nothing nearby of the same shape. Pure: the same input gives the
// same rows, and nothing moves once drawn.
export function groupRows(tiles, columns, look = 3) {
  const pool = tiles.slice();
  const out = [];
  while (pool.length) {
    const first = pool.shift();
    const row = [first];
    const key = shapeKey(first);
    if (key !== null) {
      let i = 0;
      let scanned = 0;
      while (i < pool.length && scanned < columns * look && row.length < columns) {
        if (shapeKey(pool[i]) === key) row.push(pool.splice(i, 1)[0]);
        else i += 1;
        scanned += 1;
      }
    }
    while (row.length < columns && pool.length) row.push(pool.shift());
    out.push(...row);
  }
  return out;
}

// Rows for the whole grid, grouped page by page. A page that has been drawn is
// never regrouped when the next one arrives, so infinite scroll adds rows below
// and moves nothing above.
export function pageRows(tiles, columns, page) {
  const rows = [];
  for (let at = 0; at < tiles.length; at += page) {
    const ordered = groupRows(tiles.slice(at, at + page), columns);
    for (let i = 0; i < ordered.length; i += columns) rows.push(ordered.slice(i, i + columns));
  }
  return rows;
}

// The top of every row (and one past the last), from measured heights where a
// row has been drawn and the estimate where it has not.
export function rowTops(heights, estimate, count) {
  const tops = new Array(count + 1);
  let y = 0;
  for (let i = 0; i < count; i += 1) {
    tops[i] = y;
    y += heights[i] || estimate;
  }
  tops[count] = y;
  return tops;
}

// Which rows to mount for a viewport of `height` px whose top is `scrollTop` px
// below the grid's top, with `overscan` rows kept beyond each edge.
export function windowRange(scrollTop, height, tops, count, overscan) {
  if (count === 0) return [0, 0];
  let first = 0;
  while (first < count - 1 && tops[first + 1] <= scrollTop) first += 1;
  let last = first;
  while (last < count - 1 && tops[last + 1] < scrollTop + height) last += 1;
  return [Math.max(0, first - overscan), Math.min(count, last + 1 + overscan)];
}
