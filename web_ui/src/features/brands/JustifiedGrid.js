import React, { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { layoutRows, limitsFor } from './justified';

// A grid with no whitespace: rows of photographs at one height each, every
// photograph at its own aspect ratio, widths summing to the container. The
// maths is in justified.js; this measures the container and the images.
//
// Aspect ratios are not stored yet, so a photograph is assumed portrait (3:4)
// until it loads and reports its real ratio, at which point the rows re-flow.
// Ratios are remembered per key so "load more" and a return to the page do not
// re-flow what was already measured.

const DEFAULT_RATIO = 0.75;
const known = new Map(); // key -> ratio, for the life of the tab

export default function JustifiedGrid({ items, keyOf, renderTile, className = '' }) {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  const [, bump] = useState(0);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const measure = () => setWidth(Math.floor(el.getBoundingClientRect().width));
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onRatio = useCallback((key, ratio) => {
    if (!ratio || !Number.isFinite(ratio)) return;
    const had = known.get(key);
    if (had && Math.abs(had - ratio) / had < 0.01) return;
    known.set(key, ratio);
    bump((n) => n + 1);
  }, []);

  const limits = limitsFor(width || 1200);
  const ratios = items.map((it) => known.get(keyOf(it)) || DEFAULT_RATIO);
  const rows = width ? layoutRows(ratios, width, limits) : [];

  return (
    <div className={`shop-grid ${className}`} ref={ref}>
      {rows.map((row, r) => (
        <div className={`jg-row ${row.ragged ? 'ragged' : ''}`} key={r} style={{ gap: limits.gap, marginBottom: limits.gap }}>
          {row.items.map(({ index, width: w }) => {
            const it = items[index];
            const key = keyOf(it);
            return (
              <React.Fragment key={key}>
                {renderTile(it, { width: w, height: row.height, onRatio: (ratio) => onRatio(key, ratio) })}
              </React.Fragment>
            );
          })}
        </div>
      ))}
    </div>
  );
}
