import React, { useEffect, useRef, useState } from 'react';

// ---------------------------------------------------------------------------
// ScrapeConsole — live status panel for an active brand scrape.
//
// Shown while `active` is true. Subscribes to the same SSE stream
// MyBrandsPanel uses (one connection per brand, multiplexed because Flask
// supports multiple listeners per brand_id), polls /scrape/status every
// 2s for stage info, and renders a compact terminal-style panel:
//
//   Stage: Stage 2+3: Extracting products...
//   ✓ 37 products / 5m 12s        rate 7.1 / min
//   ✗ 0 errors
//
//   Recent:
//     ✓ crash-rhinestone-bikini-top-black     [just-restocked]
//     ✓ enemy-rhinestone-hotpa                [just-restocked]
//     ...
// ---------------------------------------------------------------------------

function ScrapeConsole({ brandId, active }) {
  const [status, setStatus] = useState(null);
  const [productCount, setProductCount] = useState(0);
  const [errors, setErrors] = useState(0);
  const [recent, setRecent] = useState([]);  // latest 5 product entries
  const [startTime] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());

  // Poll /scrape/status every 2s for stage + job state.
  useEffect(() => {
    if (!active || !brandId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch(`http://localhost:8081/api/brands/${brandId}/scrape/status`);
        if (!r.ok) return;
        const j = await r.json();
        if (!cancelled) setStatus(j);
      } catch {}
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, [active, brandId]);

  // Tick a clock every second so elapsed/throughput stay live.
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);

  // Subscribe to the SSE stream to count products + capture recent.
  useEffect(() => {
    if (!active || !brandId) return;
    const src = new EventSource(`http://localhost:8081/api/brands/${brandId}/scrape/stream`);
    src.onmessage = (e) => {
      try {
        const p = JSON.parse(e.data);
        const title = p.product_title || p.name || '(no title)';
        const cat = p._category_path || '';
        setProductCount(n => n + 1);
        setRecent(prev => [{ title, cat, t: Date.now() }, ...prev].slice(0, 5));
      } catch {
        // ignore parse failures
      }
    };
    src.onerror = () => setErrors(n => n + 1);
    src.addEventListener('done', () => src.close());
    return () => src.close();
  }, [active, brandId]);

  if (!active) return null;

  const elapsedMs = now - startTime;
  const elapsedStr = fmtDuration(elapsedMs);
  const throughputPerMin = elapsedMs > 0
    ? (productCount / (elapsedMs / 60000)).toFixed(1)
    : '0.0';
  const stage = status?.current_action || 'Initializing…';
  const jobStatus = status?.status || 'running';

  return (
    <div className="scrape-console">
      <div className="scrape-console-head">
        <span className="scrape-console-led" />
        <span className="scrape-console-title">SCRAPE · {brandId}</span>
        <span className="scrape-console-status">{jobStatus}</span>
      </div>

      <div className="scrape-console-stage">{stage}</div>

      <div className="scrape-console-stats">
        <div className="scrape-stat">
          <div className="scrape-stat-num">{productCount}</div>
          <div className="scrape-stat-label">products</div>
        </div>
        <div className="scrape-stat">
          <div className="scrape-stat-num">{elapsedStr}</div>
          <div className="scrape-stat-label">elapsed</div>
        </div>
        <div className="scrape-stat">
          <div className="scrape-stat-num">{throughputPerMin}</div>
          <div className="scrape-stat-label">/ min</div>
        </div>
        <div className="scrape-stat">
          <div className="scrape-stat-num">{errors}</div>
          <div className="scrape-stat-label">errors</div>
        </div>
      </div>

      <div className="scrape-console-recent">
        <div className="scrape-console-recent-head">Recent</div>
        {recent.length === 0 && (
          <div className="scrape-console-recent-empty">waiting for first product…</div>
        )}
        {recent.map((r, i) => (
          <div key={i} className="scrape-console-recent-row">
            <span className="scrape-console-check">✓</span>
            <span className="scrape-console-name">{r.title}</span>
            {r.cat && <span className="scrape-console-cat">[{r.cat}]</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function fmtDuration(ms) {
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec.toString().padStart(2, '0')}s`;
  return `${sec}s`;
}

export default ScrapeConsole;
