import React, { useState } from 'react';

import DevEndpoints from '../../shared/api/dev';
import useDevLoad, { Gate } from './useDevLoad';
import { ago, due, n, pct, secs, usd } from './format';

const MINUTE = 60 * 1000;

// A claimed brand whose worker has stopped beating is the one state that used to
// be invisible: it looks identical to work in progress from the outside.
function statusPill(b) {
  if (b.claimed_by) {
    return b.worker_alive
      ? <span className="dev-pill working">scraping</span>
      : <span className="dev-pill stalled">worker dead</span>;
  }
  if (!b.enabled) return <span className="dev-pill idle">paused</span>;
  return null;
}

function gateCell(b) {
  if (b.gate === true) return <span>pass</span>;
  if (b.gate === false) return <span className="dev-strong">fail</span>;
  return '—';
}

export default function DevOverview({ go }) {
  const { data, state, refreshing, reload } = useDevLoad(() => DevEndpoints.getOverview(), [], MINUTE, 'overview');
  const [busy, setBusy] = useState({});
  const [note, setNote] = useState({});

  const act = async (domain, fn) => {
    setBusy((m) => ({ ...m, [domain]: true }));
    setNote((m) => ({ ...m, [domain]: null }));
    const r = await fn(domain);
    setBusy((m) => ({ ...m, [domain]: false }));
    if (r.error) setNote((m) => ({ ...m, [domain]: r.error }));
    await reload();
  };

  return (
    <Gate state={state}>
      {data && (
        <>
          <div className="dev-head">
            <h1 className="dev-title">Brands</h1>
            <div className="dev-stamp">
              {refreshing ? 'checking for changes…' : `read ${ago(data.generated_at)} · checks every minute`}
              {data.__error ? ` · last check failed: ${data.__error}` : ''}
            </div>
          </div>

          <div className="dev-totals">
            <div className="dev-total">
              <span className="dev-total-n">{n(data.totals.live_products)}</span>
              <span className="dev-total-k">products on the site</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{data.totals.showing}/{data.totals.brands}</span>
              <span className="dev-total-k">brands showing</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{(data.workers.running || []).length}</span>
              <span className="dev-total-k">being scraped</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{data.totals.need_a_human}</span>
              <span className="dev-total-k">need a human</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{data.totals.failed_gate}</span>
              <span className="dev-total-k">failed last gate</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">
                {usd(data.finder.usd)} <span className="dev-muted">/ {usd(data.finder.cap_usd, 0)}</span>
              </span>
              <span className="dev-total-k">finder spent today</span>
            </div>
          </div>

          {data.workers.running.length > 0 && (
            <div className="dev-now">
              <span className="dev-now-k">Scraping now</span>
              {data.brands.filter((b) => b.claimed_by && b.worker_alive).map((b) => (
                <button type="button" key={b.domain} className="dev-link dev-now-item" onClick={() => go({ brandId: b.domain })}>
                  {b.name}
                  <span className="dev-muted"> · {b.claimed_by} · since {ago(b.claimed_at)} · beat {b.heartbeat_minutes == null ? '—' : `${Math.round(b.heartbeat_minutes)}m ago`}</span>
                </button>
              ))}
            </div>
          )}

          {data.workers.stalled.length > 0 && (
            <div className="dev-alarm">
              <b>{data.workers.stalled.length === 1 ? 'A worker has stopped' : `${data.workers.stalled.length} workers have stopped`}:</b>{' '}
              {data.workers.stalled.join(', ')}. The brand stays held until the claim expires an hour
              after the last heartbeat, then another worker retries it.
            </div>
          )}

          <div className="dev-scroll">
            <table className="dev-table">
              <thead>
                <tr>
                  <th>Brand</th>
                  <th></th>
                  <th className="n">Products</th>
                  <th>Gate</th>
                  <th className="n">Fields</th>
                  <th className="n">s / product</th>
                  <th className="n">$ run</th>
                  <th>Last run</th>
                  <th>Next</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.brands.map((b) => (
                  <tr key={b.domain}>
                    <td>
                      <button type="button" className="dev-link dev-brand" onClick={() => go({ brandId: b.domain })}>
                        {b.name}
                      </button>
                      <div className="dev-domain">{b.domain}</div>
                      {b.attention_streak > 0 && (
                        <div className="dev-why dev-strong">
                          needs a human · {b.attention_streak} run{b.attention_streak === 1 ? '' : 's'}
                          {b.attention_reason ? ` · ${b.attention_reason}` : ''}
                        </div>
                      )}
                      {!b.attention_streak && b.empty_because && <div className="dev-why">{b.empty_because}</div>}
                      {!b.attention_streak && b.next_action && <div className="dev-why">next: {b.next_action}</div>}
                      {note[b.domain] && <div className="dev-why dev-strong">{note[b.domain]}</div>}
                    </td>
                    <td>{statusPill(b)}</td>
                    <td className="n">{n(b.live_products)}</td>
                    <td>{gateCell(b)}</td>
                    <td className="n">{pct(b.fields_filled)}</td>
                    <td className="n">{secs(b.seconds_per_product)}</td>
                    <td className="n">{usd(b.cost_usd)}</td>
                    <td>{ago(b.last_run)}{b.last_mode ? ` (${b.last_mode})` : ''}</td>
                    <td>{due(b.next_due)}</td>
                    <td className="dev-actions">
                      <button
                        type="button"
                        className="dev-act"
                        disabled={busy[b.domain] || !!b.claimed_by}
                        onClick={() => act(b.domain, DevEndpoints.runNow)}
                      >
                        run now
                      </button>
                      <button
                        type="button"
                        className="dev-act"
                        disabled={busy[b.domain]}
                        onClick={() => act(b.domain, b.enabled ? DevEndpoints.pause : DevEndpoints.resume)}
                      >
                        {b.enabled ? 'pause' : 'resume'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="dev-note">
            Gate, fields, speed and cost are the last scorecard&rsquo;s. &ldquo;Run now&rdquo; moves the
            brand&rsquo;s next turn to this moment; a worker polls every ten seconds and takes it from
            there. Nothing here talks to a worker directly.
          </p>
        </>
      )}
    </Gate>
  );
}
