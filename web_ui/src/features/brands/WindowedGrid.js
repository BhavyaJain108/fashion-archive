import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { rowTops, windowRange } from './shop';

// The grid as rows, only the rows near the viewport in the DOM.
//
// Rows you have scrolled past collapse into one spacer of their measured heights,
// so nothing below them moves and scrolling back up is exact. Rows below the
// window are not mounted at all until they come near, and when the last loaded
// row comes near, the next page is asked for. Photographs outside the window are
// unmounted, so the browser can drop their decoded bitmaps: the page costs the
// same at row 3,000 as at row 30.
//
// A tile whose photograph shape is known reserves its height before the picture
// arrives, so a freshly mounted row is the right height at once. Unknown shapes
// settle when their picture loads, and the ResizeObserver records the change.

const OVERSCAN = 2; // rows kept mounted beyond each edge of the viewport

export default function WindowedGrid({ rows, scrollRef, heightsRef, estimate, renderRow, hasMore, onMore }) {
  const [range, setRange] = useState([0, Math.min(rows.length, 4)]);
  const [, bump] = useState(0); // re-render after a measured height changes the layout
  const gridRef = useRef(null);
  const asked = useRef(-1); // rows.length when onMore was last called, so it fires once per page

  // Where the viewport sits over the rows, from the scroll container's position.
  const measure = () => {
    const el = scrollRef.current;
    const grid = gridRef.current;
    if (!el || !grid) return;
    const gridTop = grid.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop;
    const tops = rowTops(heightsRef.current, estimate, rows.length);
    const next = windowRange(el.scrollTop - gridTop, el.clientHeight, tops, rows.length, OVERSCAN);
    setRange((r) => (r[0] === next[0] && r[1] === next[1] ? r : next));
  };

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; measure(); });
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    measure();
    return () => {
      el.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows.length, estimate]);

  // Row heights, kept as they are measured. One observer for every mounted row.
  const observer = useRef(null);
  useLayoutEffect(() => {
    if (typeof ResizeObserver === 'undefined') return undefined;
    observer.current = new ResizeObserver((entries) => {
      let changed = false;
      for (const e of entries) {
        const i = Number(e.target.dataset.row);
        const h = Math.round(e.contentRect.height);
        if (h > 0 && heightsRef.current[i] !== h) { heightsRef.current[i] = h; changed = true; }
      }
      if (changed) bump((n) => n + 1);
    });
    return () => observer.current && observer.current.disconnect();
  }, [heightsRef]);
  const observe = (el) => { if (el && observer.current) observer.current.observe(el); };

  // Near the end of what is loaded: ask for more, once per page.
  useEffect(() => {
    if (!hasMore || !onMore) return;
    if (range[1] >= rows.length - OVERSCAN && asked.current !== rows.length) {
      asked.current = rows.length;
      onMore();
    }
  }, [range, rows.length, hasMore, onMore]);

  const [start, end] = range;
  const tops = rowTops(heightsRef.current, estimate, rows.length);
  const above = tops[start] || 0;
  const below = Math.max(0, (tops[rows.length] || 0) - (tops[end] || 0));

  return (
    <div ref={gridRef} className="shop-rows">
      {above > 0 && <div className="shop-spacer" style={{ height: above }} aria-hidden="true" />}
      {rows.slice(start, end).map((row, k) => {
        const i = start + k;
        return (
          <div key={i} className="shop-grid shop-row" data-row={i} ref={observe}>
            {renderRow(row, i)}
          </div>
        );
      })}
      {below > 0 && <div className="shop-spacer" style={{ height: below }} aria-hidden="true" />}
    </div>
  );
}
