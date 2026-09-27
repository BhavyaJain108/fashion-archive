import React, { useState } from 'react';

import DevEndpoints from '../../shared/api/dev';
import { ago, n, pct, usd } from './format';

// One brand's dossier, as the brand page shows it: the signature and the wall at
// the top, then the ladder, the money, the gaps, the analyses and the rules, then
// the timeline. Every number is the record's own; nothing is computed on the page.
const WALL_WORDS = {
  open: 'open — reads',
  field_gap: 'field gap — reads, something published is not read',
  busy: 'busy — the host asked for a moment',
  rate_limited: 'rate limited',
  tls: 'refuses Python’s handshake',
  address: 'refuses the address',
  challenge: 'a script must run first',
  geo: 'serves one country',
  gated: 'password',
  unreadable: 'lets us in, nothing readable',
  not_a_shop: 'not a shop',
  expensive: 'reads, dearly',
  unknown: 'never looked at',
};

const ACTION_WORDS = {
  none: 'nothing to do',
  onboard: 'onboard',
  pace: 'wait and retry slower',
  'climb:t1': 'try a browser’s handshake',
  'climb:t1p': 'try another address',
  'climb:t2': 'try a real browser',
  analyse: 'ask the model',
  cheapen: 'ask the model for a cheaper way in',
  watch: 'watch',
};

const RUNG_WORDS = { t0: 'plain HTTP', t1: 'browser handshake', t1p: 'via proxy', t2: 'real browser', t4: 'gated' };

export default function DevDossier({ domain, dossier, onAct, busy, model, proxy }) {
  const [note, setNote] = useState(null);
  if (!dossier) {
    return (
      <section className="dev-section">
        <h2 className="dev-section-h">Dossier</h2>
        <div className="dev-muted">no dossier yet — the learning loop opens one at the brand’s first turn</div>
        <div className="dev-head-actions" style={{ marginTop: 8 }}>
          <button type="button" className="dev-act" disabled={busy} onClick={() => onAct(DevEndpoints.reprobe, 'probe started')}>probe now</button>
        </div>
      </section>
    );
  }
  const w = dossier.wall || {};
  const p = dossier.predicted || {};
  const cost = dossier.cost || {};
  const unread = Object.entries(dossier.gaps || {}).filter(([, g]) => g.state === 'unread').map(([f]) => f);
  const unsought = Object.entries(dossier.gaps || {}).filter(([, g]) => g.state === 'unsought').map(([f]) => f);
  const absent = Object.entries(dossier.gaps || {}).filter(([, g]) => g.state === 'absent').map(([f]) => f);
  const act = async (fn, said) => {
    setNote(null);
    const r = await onAct(fn, said);
    if (r && r.error) setNote(r.error);
  };
  return (
    <section className="dev-section dev-dossier">
      <h2 className="dev-section-h">
        Dossier
        <span className="dev-count-k"> · opened {ago(dossier.created_at)} · {n((dossier.events || []).length)} events</span>
      </h2>

      <div className="dev-totals">
        <div className="dev-total">
          <span className="dev-total-n dev-mono-sm">{dossier.signature || '—'}</span>
          <span className="dev-total-k">signature</span>
        </div>
        <div className="dev-total">
          <span className="dev-total-n">{WALL_WORDS[w.type] || w.type || '—'}</span>
          <span className="dev-total-k">wall{w.since ? ` · since ${ago(w.since)}` : ''}</span>
        </div>
        <div className="dev-total">
          <span className="dev-total-n">{ACTION_WORDS[w.action] || w.action || '—'}</span>
          <span className="dev-total-k">next{w.attempts ? ` · tried ${w.attempts}×` : ''}</span>
        </div>
        <div className="dev-total">
          <span className="dev-total-n">{usd(cost.today, 4)} <span className="dev-muted">/ {usd(p.per_day_usd, 4)}</span></span>
          <span className="dev-total-k">today vs predicted a day</span>
        </div>
        <div className="dev-total">
          <span className="dev-total-n">{usd(cost.week, 3)}</span>
          <span className="dev-total-k">this week{p.measured ? ' · measured' : ' · estimated'}</span>
        </div>
      </div>
      {w.why && <div className="dev-why">{w.why}</div>}

      <div className="dev-head-actions">
        <button type="button" className="dev-act" disabled={busy} onClick={() => act(DevEndpoints.reprobe, 'probe started')}>probe again</button>
        <button type="button" className="dev-act" disabled={busy} onClick={() => act((d) => DevEndpoints.climb(d, 't1'), 'climbing to t1')}>climb t1</button>
        <button type="button" className="dev-act" disabled={busy || !proxy} title={proxy ? '' : 'needs ARCHIVE_PROXY_URL'} onClick={() => act((d) => DevEndpoints.climb(d, 't1p'), 'climbing to t1p')}>climb t1p</button>
        <button type="button" className="dev-act" disabled={busy} onClick={() => act((d) => DevEndpoints.climb(d, 't2'), 'climbing to t2')}>climb t2</button>
        <button type="button" className="dev-act" disabled={busy || !model} title={model ? '' : 'needs ANTHROPIC_API_KEY on the API'} onClick={() => act((d) => DevEndpoints.analyse(d, 'brand'), 'analysis started')}>ask the model</button>
        <button type="button" className="dev-act" disabled={busy || !model} title={model ? '' : 'needs ANTHROPIC_API_KEY on the API'} onClick={() => act((d) => DevEndpoints.analyse(d, 'cheapen'), 'analysis started')}>find a cheaper way</button>
      </div>
      {note && <div className="dev-alarm">{note}</div>}

      <h3 className="dev-sub-h">Ladder — every rung ever tried</h3>
      {(dossier.ladder || []).length === 0 ? <div className="dev-muted">not probed yet</div> : (
        <div className="dev-scroll">
          <table className="dev-table dev-table-sub">
            <thead><tr><th>When</th><th>Rung</th><th>Outcome</th><th>Statuses</th><th className="n">s</th><th>Note</th></tr></thead>
            <tbody>
              {[...dossier.ladder].reverse().map((r, i) => (
                <tr key={i}>
                  <td>{ago(r.at)}</td>
                  <td>{r.level} <span className="dev-muted">{RUNG_WORDS[r.level] || ''}</span></td>
                  <td className={r.outcome === 'ok' ? '' : 'dev-strong'}>{r.outcome}</td>
                  <td className="mono">{(r.statuses || []).slice(0, 8).join(' ')}</td>
                  <td className="n">{r.seconds != null ? r.seconds.toFixed(1) : '—'}</td>
                  <td className="wrap dev-muted">{r.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="dev-sub-h">Lanes — what has read it</h3>
      {(dossier.lanes || []).length === 0 ? <div className="dev-muted">no lane has been tried</div> : (
        <div className="dev-scroll">
          <table className="dev-table dev-table-sub">
            <thead><tr><th>When</th><th>Lane</th><th>Verdict</th><th className="n">Products</th><th className="n">Title</th><th className="n">Price</th><th className="n">Stock</th><th className="n">Images</th><th>Note</th></tr></thead>
            <tbody>
              {[...dossier.lanes].reverse().map((l, i) => (
                <tr key={i}>
                  <td>{ago(l.at)}</td>
                  <td className="mono">{l.composition}</td>
                  <td className={['full', 'partial', 'ok'].includes(l.verdict) ? '' : 'dev-strong'}>{l.verdict}</td>
                  <td className="n">{n(l.products)}</td>
                  <td className="n">{pct((l.fill || {}).product_title)}</td>
                  <td className="n">{pct((l.fill || {}).price)}</td>
                  <td className="n">{pct((l.fill || {}).in_stock)}</td>
                  <td className="n">{pct((l.fill || {}).all_images)}</td>
                  <td className="wrap dev-muted">{l.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="dev-sub-h">Gaps</h3>
      <div className="dev-gaps">
        <div><span className="dev-live-k">unread</span> <span className="dev-muted">guaranteed by the sale and blank — ours to fix</span><div className="wrap">{unread.length ? unread.join(', ') : '—'}</div></div>
        <div><span className="dev-live-k">unsought</span> <span className="dev-muted">the page has not been read for it — worth a look</span><div className="wrap">{unsought.length ? unsought.join(', ') : '—'}</div></div>
        <div><span className="dev-live-k">absent</span> <span className="dev-muted">the shop does not publish it</span><div className="wrap">{absent.length ? absent.join(', ') : '—'}</div></div>
      </div>

      <h3 className="dev-sub-h">Money — by day</h3>
      {Object.keys(dossier.meter || {}).length === 0 ? <div className="dev-muted">nothing metered yet</div> : (
        <div className="dev-scroll">
          <table className="dev-table dev-table-sub">
            <thead><tr><th>Day</th><th className="n">Requests</th><th className="n">Proxy</th><th className="n">Browser s</th><th className="n">Model calls</th><th className="n">$</th><th className="n">Runs</th></tr></thead>
            <tbody>
              {Object.entries(dossier.meter).reverse().slice(0, 14).map(([day, m]) => (
                <tr key={day}>
                  <td>{day}</td>
                  <td className="n">{n(Object.values(m.requests || {}).reduce((a, b) => a + b, 0))} <span className="dev-muted">{Object.entries(m.requests || {}).map(([k, v]) => `${k} ${v}`).join(' ')}</span></td>
                  <td className="n">{n(m.proxy_requests)}</td>
                  <td className="n">{m.browser_seconds ? m.browser_seconds.toFixed(0) : '—'}</td>
                  <td className="n">{n(m.llm_calls)}</td>
                  <td className="n">{usd(m.usd, 4)}</td>
                  <td className="n">{n(m.runs)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="dev-sub-h">Analyses — what the model said</h3>
      {(dossier.analyses || []).length === 0 ? <div className="dev-muted">the model has not been asked</div> : (
        <div className="dev-scroll">
          <table className="dev-table">
            <thead><tr><th>When</th><th>Kind</th><th>Status</th><th className="n">$</th><th>Reasoning</th><th>Gate</th></tr></thead>
            <tbody>
              {[...dossier.analyses].reverse().map((a) => (
                <tr key={a.id}>
                  <td>{ago(a.at)}</td>
                  <td>{a.kind}</td>
                  <td className={a.status === 'landed' ? '' : 'dev-strong'}>{a.status}</td>
                  <td className="n">{usd(a.usd, 3)}</td>
                  <td className="wrap">{a.reasoning}</td>
                  <td className="wrap dev-muted">
                    {a.gate ? (a.gate.steps || []).map((s) => `${s.step}: ${s.passed === null ? '—' : s.passed ? 'pass' : 'fail'}`).join(' · ') || a.gate.note : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(dossier.rules || []).length > 0 && (
        <>
          <h3 className="dev-sub-h">Rules applied</h3>
          <table className="dev-table dev-table-sub">
            <tbody>
              {dossier.rules.map((r) => (
                <tr key={r.id}><td className="key">{r.kind}</td><td className="wrap">{r.description} <span className="dev-muted">· {r.status} · {r.signature}</span></td></tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h3 className="dev-sub-h">Timeline</h3>
      <table className="dev-table">
        <tbody>
          {[...(dossier.events || [])].reverse().map((e, i) => (
            <tr key={i}>
              <td className="n dev-muted">{ago(e.at)}</td>
              <td className="dev-strong">{e.kind}</td>
              <td className="wrap">{e.text}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
