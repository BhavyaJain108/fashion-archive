import React, { useState } from 'react';

import DevEndpoints from '../../shared/api/dev';
import useDevLoad, { Gate, Stamp } from './useDevLoad';
import { ago, n, usd } from './format';

const MINUTE = 60 * 1000;

// The learning loop's own page: how the space organises itself (the signature
// map), what stands in the way (the walls), what the loop did last (the tick),
// what the model proposed and what the gate said, the rules that exist, and the
// budget the whole thing runs under. Every table is the loop's own objects; the
// page computes nothing.

function Budget({ b }) {
  if (!b || !b.pools) return <div className="dev-muted">no budget yet — written by the first tick</div>;
  const r = b.pools.recurring || {};
  const d = b.pools.discretionary || {};
  const bar = (spent, cap) => (
    <span className="dev-bar-track"><span className="dev-bar" style={{ width: `${cap ? Math.min(100, Math.round((spent / cap) * 100)) : 0}%` }} /></span>
  );
  return (
    <div className="dev-budget">
      <div className="dev-totals">
        <div className="dev-total"><span className="dev-total-n">{usd(b.spent_usd, 3)} <span className="dev-muted">/ {usd(b.ceiling_usd_day, 2)}</span></span><span className="dev-total-k">today vs ceiling</span></div>
        <div className="dev-total"><span className="dev-total-n">{usd(b.baseline_usd_day, 3)}</span><span className="dev-total-k">baseline a day · ×{b.multiplier}</span></div>
        <div className="dev-total"><span className="dev-total-n">{b.stretch && b.stretch > 1 ? `×${b.stretch}` : 'none'}</span><span className="dev-total-k">cadence stretch</span></div>
        <div className="dev-total"><span className="dev-total-n">{n(b.brands)}</span><span className="dev-total-k">brands priced</span></div>
      </div>
      <table className="dev-table dev-table-sub">
        <tbody>
          <tr><td className="key">recurring</td><td className="bar">{bar(r.spent, r.cap)}</td><td className="n">{usd(r.spent, 3)} / {usd(r.cap, 2)}</td><td className="wrap dev-muted">keeping every brand fresh at its cadence</td></tr>
          <tr><td className="key">discretionary</td><td className="bar">{bar(d.spent, d.cap)}</td><td className="n">{usd(d.spent, 3)} / {usd(d.cap, 2)}</td><td className="wrap dev-muted">probes, proxy sweeps, the model — poured into walls</td></tr>
        </tbody>
      </table>
    </div>
  );
}

function Cluster({ c, go }) {
  const [open, setOpen] = useState(false);
  const verdicts = Object.entries(c.verdicts || {}).map(([k, v]) => `${k} ${v}`).join(' · ');
  const walls = Object.entries(c.walls || {}).filter(([k]) => k !== 'open').map(([k, v]) => `${k} ${v}`).join(' · ');
  return (
    <>
      <tr>
        <td className="n">{n(c.count)}</td>
        <td className="mono wrap"><button type="button" className="dev-link" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? '▾' : '▸'} {c.signature}</button></td>
        <td className="wrap">{verdicts || '—'}</td>
        <td className="wrap dev-muted">{walls || 'all open'}</td>
        <td className="n">{c.median_per_product_usd != null ? usd(c.median_per_product_usd, 5) : '—'}</td>
        <td className="n">{n((c.rules || []).length)}</td>
      </tr>
      {open && (
        <tr className="dev-log-row">
          <td colSpan={6}>
            <table className="dev-table dev-table-sub">
              <tbody>
                {(c.brands || []).map((b) => (
                  <tr key={b.domain}>
                    <td><button type="button" className="dev-link" onClick={() => go({ brandId: b.domain })}>{b.name || b.domain}</button></td>
                    <td>{b.verdict}</td>
                    <td className="dev-muted">{b.wall}</td>
                    <td className="n">{b.per_day_usd != null ? `${usd(b.per_day_usd, 4)}/day` : '—'}</td>
                  </tr>
                ))}
                {(c.rules || []).map((r) => (
                  <tr key={r.id}><td className="key">rule</td><td className="wrap" colSpan={3}>{r.description} <span className="dev-muted">· {r.status} · reads {(r.brands || []).join(', ') || '—'}</span></td></tr>
                ))}
              </tbody>
            </table>
          </td>
        </tr>
      )}
    </>
  );
}

export default function DevLearning({ go }) {
  const { data, state, refreshing, checkedAt, reload } = useDevLoad(() => DevEndpoints.getLearning(), [], MINUTE, 'learning');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);
  const tick = async () => {
    setBusy(true);
    setNote(null);
    const r = await DevEndpoints.learningTick();
    setBusy(false);
    setNote(r.error || 'tick started — the map and the walls refresh as it runs');
    await reload();
  };
  return (
    <Gate state={state}>
      {data && (
        <>
          <div className="dev-head">
            <h1 className="dev-title">Learning</h1>
            <div className="dev-head-actions">
              <button type="button" className="dev-act" disabled={busy} onClick={tick}>tick now</button>
            </div>
          </div>
          <Stamp data={data} refreshing={refreshing} checkedAt={checkedAt} every="checks every minute" />
          {note && <div className="dev-why">{note}</div>}

          <div className="dev-totals">
            <div className="dev-total"><span className="dev-total-n">{data.status.at ? ago(data.status.at) : 'never'}</span><span className="dev-total-k">last tick{data.status.seconds ? ` · ${data.status.seconds}s` : ''}</span></div>
            <div className="dev-total"><span className="dev-total-n">{n((data.status.actions || []).length)}</span><span className="dev-total-k">actions</span></div>
            <div className="dev-total"><span className="dev-total-n">{n((data.status.analyses || []).length)}</span><span className="dev-total-k">analyses</span></div>
            <div className="dev-total"><span className="dev-total-n">{n((data.status.landed || []).length)}</span><span className="dev-total-k">landed</span></div>
            <div className="dev-total"><span className="dev-total-n">{data.model ? 'on' : 'off'}</span><span className="dev-total-k">model{data.model ? '' : ' · set ANTHROPIC_API_KEY'}</span></div>
            <div className="dev-total"><span className="dev-total-n">{data.proxy ? 'on' : 'off'}</span><span className="dev-total-k">proxy rung{data.proxy ? '' : ' · set ARCHIVE_PROXY_URL'}</span></div>
          </div>

          <section className="dev-section">
            <h2 className="dev-section-h">Budget</h2>
            <Budget b={data.budget} />
          </section>

          <section className="dev-section">
            <h2 className="dev-section-h">The space — brands by signature <span className="dev-count-k">· {n((data.map.clusters || []).length)} shapes{data.map.at ? ` · as of ${ago(data.map.at)}` : ''}</span></h2>
            {(data.map.clusters || []).length === 0 ? <div className="dev-muted">no dossiers yet — the first tick onboards the roster</div> : (
              <div className="dev-scroll">
                <table className="dev-table">
                  <thead><tr><th className="n">Brands</th><th>Signature · platform · feed · sitemap · page · defence · locale</th><th>Verdicts</th><th>Walls</th><th className="n">$ / product</th><th className="n">Rules</th></tr></thead>
                  <tbody>{data.map.clusters.map((c) => <Cluster key={c.signature} c={c} go={go} />)}</tbody>
                </table>
              </div>
            )}
            <p className="dev-note">A signature is six words the probe reads off a shop. Rules hang on signatures, never on brands; a signature that matches one brand for ever is a brand name in disguise.</p>
          </section>

          <section className="dev-section">
            <h2 className="dev-section-h">Walls <span className="dev-count-k">· {n(data.walls.length)} brands not simply open</span></h2>
            {data.walls.length === 0 ? <div className="dev-muted">every brand reads</div> : (
              <div className="dev-scroll">
                <table className="dev-table">
                  <thead><tr><th>Brand</th><th>Wall</th><th>Verdict</th><th>Signature</th><th className="n">$ / day</th></tr></thead>
                  <tbody>
                    {data.walls.map((w) => (
                      <tr key={w.domain}>
                        <td><button type="button" className="dev-link" onClick={() => go({ brandId: w.domain })}>{w.name}</button></td>
                        <td className="dev-strong">{w.wall}</td>
                        <td>{w.verdict}</td>
                        <td className="mono wrap dev-muted">{w.signature}</td>
                        <td className="n">{w.per_day_usd != null ? usd(w.per_day_usd, 4) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="dev-section">
            <h2 className="dev-section-h">Last tick — what the loop did</h2>
            {(data.status.actions || []).length === 0 ? <div className="dev-muted">nothing to do, or no tick yet</div> : (
              <div className="dev-scroll">
                <table className="dev-table">
                  <thead><tr><th>Brand</th><th>Wall</th><th>Action</th><th>Did</th></tr></thead>
                  <tbody>
                    {data.status.actions.map((a, i) => (
                      <tr key={i}>
                        <td><button type="button" className="dev-link" onClick={() => go({ brandId: a.domain })}>{a.domain}</button></td>
                        <td>{a.wall}</td>
                        <td>{a.action}</td>
                        <td className="wrap">{a.did}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {(data.history || []).length > 1 && (
              <p className="dev-note">
                {data.history.slice(-8).reverse().map((h) => `${ago(h.at)}: ${(h.actions || []).length} actions, ${(h.landed || []).length} landed${h.errors ? `, ${h.errors} errors` : ''}`).join(' · ')}
              </p>
            )}
          </section>

          <section className="dev-section">
            <h2 className="dev-section-h">Proposals — code the model wrote <span className="dev-count-k">· {n(data.proposals.length)}</span></h2>
            {data.proposals.length === 0 ? <div className="dev-muted">none — recipes land on their own; only code is filed here</div> : (
              <div className="dev-scroll">
                <table className="dev-table">
                  <thead><tr><th>When</th><th>Brand</th><th>Summary</th><th>Files</th><th>Where</th></tr></thead>
                  <tbody>
                    {data.proposals.map((p) => (
                      <tr key={p.id}>
                        <td>{ago(p.at)}</td>
                        <td><button type="button" className="dev-link" onClick={() => go({ brandId: p.domain })}>{p.domain}</button></td>
                        <td className="wrap">{p.summary}</td>
                        <td className="wrap mono">{(p.files || []).map((f) => f.path).join(', ')}</td>
                        <td className="wrap">{p.branch ? `branch ${p.branch}` : `filed · cli learn apply ${p.id}`}{p.push_error ? ` · push failed: ${p.push_error}` : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="dev-section">
            <h2 className="dev-section-h">Rules that exist <span className="dev-count-k">· {n(data.rules.length)}</span></h2>
            {data.rules.length === 0 ? <div className="dev-muted">no learned rule yet — the built-in lanes are in the code</div> : (
              <table className="dev-table">
                <thead><tr><th>Signature</th><th>Rule</th><th>Status</th><th>Reads</th></tr></thead>
                <tbody>
                  {data.rules.map((r) => (
                    <tr key={r.id}><td className="mono wrap">{r.signature}</td><td className="wrap">{r.description}</td><td>{r.status}</td><td className="wrap dev-muted">{(r.brands || []).join(', ') || '—'}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {data.learnings.length > 0 && (
            <section className="dev-section">
              <h2 className="dev-section-h">Learnings — the notebook</h2>
              <table className="dev-table">
                <tbody>
                  {[...data.learnings].reverse().map((l, i) => (
                    <tr key={i}><td className="n dev-muted">{ago(l.at)}</td><td>{l.domain}</td><td className="wrap">{l.text}</td></tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </>
      )}
    </Gate>
  );
}
