import React from 'react';

import { ago, n } from './format';

// Where a running scrape is, drawn as a bar. A phase with a length — fetching,
// photographs — fills the bar; one without — probing, finalising, or the seconds
// before the first progress write — shows the sheen moving over an empty track,
// which is the light that says "alive" without claiming to know how far along.
// The sheen is the only motion on the deck; it exists to be seen from across the
// room, and it stops the moment the brand is handed back.
//
// `size` is "row" inside a table cell, "hero" at the top of a brand page.
const PHASE_WORDS = {
  fetching: 'reading products',
  finalising: 'writing the catalogue',
  photographs: 'archiving photographs',
  done: 'done',
};

export default function LiveState({ brand, size = 'row' }) {
  if (!brand || !brand.claimed_by) return null;
  if (!brand.worker_alive) {
    return <span className="dev-pill stalled">worker dead</span>;
  }
  const p = brand.progress;
  const known = p && p.total != null && p.total > 0 && p.done != null;
  const share = known ? Math.min(100, Math.round((p.done / p.total) * 100)) : 0;
  const phase = p ? (PHASE_WORDS[p.phase] || p.phase) : 'starting';
  const stale = p && p.updated_at ? ago(p.updated_at) : null;

  return (
    <div className={`dev-live dev-live-${size}`} role="status" aria-live="polite">
      <div className="dev-live-line">
        <span className="dev-live-k">{phase}</span>
        {known && <span className="dev-live-v">{n(p.done)} / {n(p.total)} · {share}%</span>}
        {size === 'hero' && (
          <span className="dev-muted">
            {' '}· {brand.claimed_by} · since {ago(brand.claimed_at)}{stale ? ` · position as of ${stale}` : ''}
          </span>
        )}
      </div>
      <div className={`dev-live-track${known ? '' : ' indeterminate'}`}>
        <div className="dev-live-fill" style={known ? { width: `${share}%` } : undefined} />
      </div>
    </div>
  );
}
