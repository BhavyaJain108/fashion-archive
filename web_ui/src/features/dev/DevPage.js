import React, { useCallback, useEffect, useState } from 'react';

import DevEndpoints from '../../shared/api/dev';
import './DevPage.css';

const MINUTE = 60 * 1000;

// Answers "is it working" at a glance. A claimed brand whose worker has stopped
// beating is the one state that used to be invisible: it looks identical to work in
// progress from the outside, and cost most of a day before anyone noticed.
function workerPill(brand) {
  if (!brand.claimed_by) return null;
  if (brand.worker_alive) {
    return <span className="dev-pill working">scraping</span>;
  }
  return <span className="dev-pill stalled">worker dead</span>;
}

function ago(iso) {
  if (!iso) return '—';
  const mins = (Date.now() - new Date(iso).getTime()) / MINUTE;
  if (Number.isNaN(mins)) return '—';
  if (mins < 60) return `${Math.round(mins)}m ago`;
  if (mins < 1440) return `${(mins / 60).toFixed(1)}h ago`;
  return `${(mins / 1440).toFixed(1)}d ago`;
}

function due(iso) {
  if (!iso) return '—';
  const mins = (new Date(iso).getTime() - Date.now()) / MINUTE;
  if (Number.isNaN(mins)) return '—';
  if (mins <= 0) return 'due now';
  if (mins < 60) return `in ${Math.round(mins)}m`;
  if (mins < 1440) return `in ${(mins / 60).toFixed(1)}h`;
  return `in ${(mins / 1440).toFixed(1)}d`;
}

const n = (v) => (v || 0).toLocaleString();

export default function DevPage() {
  const [data, setData] = useState(null);
  const [state, setState] = useState('loading');
  const [photos, setPhotos] = useState({});

  const load = useCallback(async () => {
    const body = await DevEndpoints.getOverview();
    if (body.forbidden) {
      setState('forbidden');
      return;
    }
    if (body.error) {
      setState(body.error);
      return;
    }
    setData(body);
    setState('ready');
  }, []);

  useEffect(() => {
    load();
    // A scrape changes state in minutes, not seconds, and every refresh is a read
    // of the bucket — so once a minute, not a live stream.
    const timer = setInterval(load, MINUTE);
    return () => clearInterval(timer);
  }, [load]);

  const count = async (domain) => {
    setPhotos((p) => ({ ...p, [domain]: { loading: true } }));
    const got = await DevEndpoints.getPhotographs(domain);
    setPhotos((p) => ({ ...p, [domain]: got }));
  };

  if (state === 'forbidden') {
    return (
      <div className="dev">
        <div className="dev-empty">
          This page is for the archive&rsquo;s owner. Your account is not on that list.
        </div>
      </div>
    );
  }
  if (state === 'loading') return <div className="dev"><div className="dev-empty">Reading the archive&hellip;</div></div>;
  if (state !== 'ready') return <div className="dev"><div className="dev-empty">{state}</div></div>;

  const { totals, workers, brands } = data;
  const stalled = workers.stalled || [];

  return (
    <div className="dev">
      <div className="dev-head">
        <h1 className="dev-title">Machine room</h1>
        <div className="dev-stamp">read {ago(data.generated_at)} &middot; refreshes every minute</div>
      </div>

      <div className="dev-totals">
        <div className="dev-total">
          <span className="dev-total-n">{n(totals.live_products)}</span>
          <span className="dev-total-k">products on the site</span>
        </div>
        <div className="dev-total">
          <span className="dev-total-n">{totals.showing}/{totals.brands}</span>
          <span className="dev-total-k">brands showing</span>
        </div>
        <div className="dev-total">
          <span className="dev-total-n">{n(totals.photographs)}</span>
          <span className="dev-total-k">photographs kept</span>
        </div>
        <div className="dev-total">
          <span className="dev-total-n">{(workers.running || []).length}</span>
          <span className="dev-total-k">brands being scraped</span>
        </div>
      </div>

      {stalled.length > 0 && (
        <div className="dev-alarm">
          <b>{stalled.length === 1 ? 'A worker has stopped' : `${stalled.length} workers have stopped`}:</b>{' '}
          {stalled.join(', ')}. The brand stays held until the claim expires an hour after
          the last heartbeat, then another worker retries it.
        </div>
      )}

      <div className="dev-scroll">
        <table className="dev-table">
          <thead>
            <tr>
              <th>Brand</th>
              <th></th>
              <th className="n">Products</th>
              <th className="n">Photographs</th>
              <th>Last run</th>
              <th>Next run</th>
              <th className="n">Coverage</th>
            </tr>
          </thead>
          <tbody>
            {brands.map((b) => {
              const shot = photos[b.domain];
              return (
                <tr key={b.domain}>
                  <td>
                    <div className="dev-brand">{b.name}</div>
                    <div className="dev-domain">{b.domain}</div>
                    {b.empty_because && <div className="dev-why">{b.empty_because}</div>}
                  </td>
                  <td>
                    {workerPill(b) || (!b.enabled && <span className="dev-pill idle">paused</span>)}
                  </td>
                  <td className="n">{n(b.live_products)}</td>
                  <td className="n">
                    {shot?.loading && '…'}
                    {shot?.error && <span className="dev-why">{shot.error}</span>}
                    {shot?.stored !== undefined && (
                      <>
                        {n(shot.stored)}
                        {shot.waiting > 0 && <span className="dev-why"> · {n(shot.waiting)} to fetch</span>}
                      </>
                    )}
                    {!shot && (
                      <button type="button" className="dev-count" onClick={() => count(b.domain)}>
                        count
                      </button>
                    )}
                  </td>
                  <td>{ago(b.last_run)}{b.last_mode ? ` (${b.last_mode})` : ''}</td>
                  <td>{due(b.next_due)}</td>
                  <td className="n">
                    {b.coverage_pct == null ? '—' : `${Math.round(b.coverage_pct * 100)}%`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="dev-note">
        Photograph counts are asked for one brand at a time because answering needs that
        brand&rsquo;s whole catalogue — 35&nbsp;MB for psylos1 — and reading every one at
        once is what killed the worker.
      </p>
    </div>
  );
}
