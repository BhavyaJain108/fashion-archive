import React, { useState } from 'react';

import DevEndpoints from '../../shared/api/dev';
import useDevLoad, { Gate, Stamp } from './useDevLoad';
import DevGlossary from './DevGlossary';
import LiveState from './LiveState';
import { ago, dateShort, due, hours, n, pct, secs, usd } from './format';

// The newest run with a log, told as sentences: what it decided, found, read,
// learned and how it ended. Time is offset from the run's start.
function LastActions({ la }) {
  if (!la) {
    return (
      <section className="dev-section dev-last">
        <h2 className="dev-section-h">Last actions</h2>
        <div className="dev-muted">no run has left a log yet — the next one will</div>
      </section>
    );
  }
  const t0 = la.started_at ? new Date(la.started_at).getTime() : null;
  const offset = (at) => {
    if (!at || t0 == null) return '';
    const s = Math.max(0, (new Date(at).getTime() - t0) / 1000);
    return s < 60 ? `+${s.toFixed(0)}s` : s < 3600 ? `+${(s / 60).toFixed(0)}m` : `+${(s / 3600).toFixed(1)}h`;
  };
  return (
    <section className="dev-section dev-last">
      <h2 className="dev-section-h">
        Last actions
        <span className="dev-count-k"> · run of {dateShort(la.started_at)} ({ago(la.started_at)}) · {la.mode}{la.finished_at ? '' : ' · still running'}</span>
      </h2>
      <table className="dev-table">
        <tbody>
          {la.lines.map((l, i) => (
            <tr key={i}>
              <td className="n dev-muted">{offset(l.at)}</td>
              <td className="wrap">{l.text}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

const MINUTE = 60 * 1000;

// One brand, everything the archive recorded about it. The plan is how we get in;
// the fields are what we get out; the runs are how that has gone; the findings
// are what to do about it. All from the small objects — never the catalogue,
// which has a page of its own. Every block is a table under one rule set.
export default function DevBrand({ domain, go }) {
  // Every minute when idle; every fifteen seconds while a worker holds the brand,
  // so the bar moves at the pace the worker writes it.
  const [held, setHeld] = React.useState(false);
  const { data, state, refreshing, checkedAt, reload } = useDevLoad(
    () => DevEndpoints.getBrand(domain), [domain], held ? 15000 : MINUTE, `brand:${domain}`,
  );
  React.useEffect(() => {
    setHeld(!!(data && data.brand && data.brand.claimed_by));
  }, [data]);
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);
  const [retrySearched, setRetrySearched] = useState(false);

  // One command at a time: a second press while the first is in flight would
  // queue the same run twice or flip a pause back before the page has caught up.
  const act = async (fn) => {
    if (busy) return;
    setBusy(true);
    setNote(null);
    const r = await fn(domain);
    setBusy(false);
    if (r.error) setNote(r.error);
    await reload();
  };

  return (
    <Gate state={state}>
      {data && (
        <>
          <div className="dev-head">
            <div>
              <h1 className="dev-title">{data.brand.name}</h1>
              <div className="dev-domain">{domain}</div>
            </div>
            <div className="dev-head-actions">
              {data.brand.claimed_by && data.brand.worker_alive === false ? (
                <button type="button" className="dev-act" disabled={busy} onClick={() => act(DevEndpoints.release)}>
                  release
                </button>
              ) : (
                <button
                  type="button"
                  className="dev-act"
                  disabled={busy || !!data.brand.claimed_by || data.brand.run_once}
                  onClick={() => act(DevEndpoints.runNow)}
                >
                  {data.brand.enabled ? 'run now' : 'run once'}
                </button>
              )}
              <button
                type="button"
                className="dev-act"
                disabled={busy || !!data.brand.claimed_by || data.brand.next_mode === 'full'}
                title="Re-read every page, not only the changed ones. The way a rule about a page reaches products whose hints never moved."
                onClick={() => act((d) => DevEndpoints.runNow(d, true))}
              >
                {data.brand.next_mode === 'full' ? 'full run queued' : 'run full'}
              </button>
              <button
                type="button"
                className="dev-act"
                disabled={busy || !!data.brand.claimed_by || data.brand.next_mode === 'learn'}
                title="The finder reads a spread of product pages and writes rules. Nothing is stored; the scheduled run is kept."
                onClick={() => act((d) => DevEndpoints.learn(d, retrySearched))}
              >
                {data.brand.next_mode === 'learn' ? 'learn queued' : 'learn fields'}
              </button>
              <label className="dev-check">
                <input
                  type="checkbox"
                  checked={retrySearched}
                  onChange={(e) => setRetrySearched(e.target.checked)}
                />
                {' '}retry searched fields
              </label>
              <button
                type="button"
                className="dev-act"
                disabled={busy}
                onClick={() => act(data.brand.enabled ? DevEndpoints.pause : DevEndpoints.resume)}
              >
                {!data.brand.enabled ? 'resume' : data.brand.claimed_by ? 'pause after run' : 'pause'}
              </button>
              <button type="button" className="dev-act" onClick={() => go({ brandId: domain, category: 'products' })}>
                catalogue →
              </button>
            </div>
          </div>
          {note && <div className="dev-alarm">{note}</div>}
          <Stamp data={data} refreshing={refreshing} checkedAt={checkedAt} every={held ? 'checks every 15 s while held' : 'checks every minute'} />
          <LiveState brand={data.brand} size="hero" />
          <DevGlossary />

          <LastActions la={data.last_actions} />

          <div className="dev-totals">
            <div className="dev-total">
              <span className="dev-total-n">{data.brand.state || '—'}</span>
              <span className="dev-total-k">state</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{n(data.brand.live_products)}</span>
              <span className="dev-total-k">products on the site</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{data.brand.gate == null ? '—' : data.brand.gate ? 'pass' : 'fail'}</span>
              <span className="dev-total-k">last gate</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{pct(data.brand.fields_filled)}</span>
              <span className="dev-total-k">of 42 fields</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{secs(data.brand.seconds_per_product)}</span>
              <span className="dev-total-k">per product</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{data.brand.claimed_by ? 'scraping' : due(data.brand.next_due)}</span>
              <span className="dev-total-k">next run · every {hours(data.brand.cadence_seconds)}</span>
            </div>
          </div>

          {data.brand.attention_streak > 0 && (
            <div className="dev-alarm">
              <b>Needs a human</b> — {data.brand.attention_streak} run
              {data.brand.attention_streak === 1 ? '' : 's'} in a row ended the same way:{' '}
              {data.brand.attention_reason}
            </div>
          )}

          <section className="dev-section">
            <h2 className="dev-section-h">What to fix first</h2>
            {data.recommendations && data.recommendations.findings.length > 0 ? (
              <div className="dev-scroll">
                <table className="dev-table">
                  <thead>
                    <tr><th className="n">#</th><th>Finding</th><th>What to do</th></tr>
                  </thead>
                  <tbody>
                    {data.recommendations.findings.map((f, i) => (
                      <tr key={i}>
                        <td className="n dev-muted">{f.priority}</td>
                        <td className="wrap">{f.headline}</td>
                        <td className="wrap dev-muted">{f.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="dev-muted">
                {data.recommendations ? 'nothing to do' : 'no scored run yet — written after the next one'}
              </div>
            )}
            {data.recommendations && (
              <div className="dev-stamp">from run {data.recommendations.run_id} · {ago(data.recommendations.at)}</div>
            )}
          </section>

          <section className="dev-section">
            <h2 className="dev-section-h">Plan — how we get in</h2>
            {data.plan ? (
              <table className="dev-table dev-table-sub">
                <tbody>
                  <tr><td className="key">composition</td><td className="wrap">{data.plan.composition}</td></tr>
                  <tr><td className="key">status</td><td className="wrap">{data.plan.status}{data.plan.stale ? ' · stale, re-probed next run' : ''}</td></tr>
                  <tr><td className="key">transport</td><td>{data.plan.transport}</td></tr>
                  <tr><td className="key">discovery</td><td className="wrap">{data.plan.discovery}{data.plan.sitemap_url ? ` · ${data.plan.sitemap_url}` : ''}</td></tr>
                  <tr><td className="key">fetch</td><td>{data.plan.fetch}</td></tr>
                  <tr><td className="key">product urls</td><td className="wrap">{data.plan.product_url_prefix || '—'}</td></tr>
                  <tr><td className="key">currency</td><td>{data.plan.currency || '—'}</td></tr>
                  <tr><td className="key">fingerprinted</td><td>{ago(data.plan.fingerprinted_at)}</td></tr>
                </tbody>
              </table>
            ) : (
              <div className="dev-muted">not probed yet</div>
            )}
            {data.plan && data.plan.tried.length > 0 && (
              <div className="dev-scroll">
                <table className="dev-table">
                  <thead>
                    <tr><th>Tried and failed</th><th>When</th><th>Why</th></tr>
                  </thead>
                  <tbody>
                    {data.plan.tried.map((t, i) => (
                      <tr key={i}>
                        <td>{t.composition}</td>
                        <td>{ago(t.failed_at)}</td>
                        <td className="wrap">{t.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="dev-section">
            <h2 className="dev-section-h">
              Fields — what we get out
              {data.recipe_book && (
                <span className="dev-count-k">
                  {' '}· {data.recipe_book.rules} learned rule{data.recipe_book.rules === 1 ? '' : 's'}
                  {data.recipe_book.rendered ? ' · need a browser' : ''}
                </span>
              )}
            </h2>
            <div className="dev-scroll">
              <table className="dev-table">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>Class</th>
                    <th className="n">Fill</th>
                    <th>Rules</th>
                    <th>Searched</th>
                  </tr>
                </thead>
                <tbody>
                  {data.fields.map((f) => (
                    <tr key={f.name} className={f.fill === 0 || f.fill == null ? 'dev-row-empty' : ''}>
                      <td className="mono">{f.name}</td>
                      <td title={data.classes[f.class] ? data.classes[f.class][1] : ''}>
                        {f.class} <span className="dev-muted">{data.classes[f.class] ? data.classes[f.class][0] : ''}</span>
                      </td>
                      <td className="n">{pct(f.fill)}</td>
                      <td className="wrap">
                        {f.rules.length === 0 ? <span className="dev-muted">—</span> : f.rules.map((r, i) => (
                          <div key={i} className="dev-rule">
                            <span className="dev-mono">{r.kind}</span> {r.expression}
                            <span className="dev-muted"> · fired {n(r.hits)}</span>
                          </div>
                        ))}
                      </td>
                      <td className="wrap dev-muted">{f.evidence}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="dev-note">
              Fill is the last scorecard&rsquo;s. &ldquo;Searched&rdquo; says where the archive looked for a
              blank field — the channel, the learned rules, a rendered page, or the model — so a blank
              can be believed: absent from every source is a fact about the brand; never searched is a
              gap in our work.
            </p>
          </section>

          <section className="dev-section">
            <h2 className="dev-section-h">Runs — every scrape, scored or not</h2>
            {data.runs.length === 0 ? (
              <div className="dev-muted">no run yet</div>
            ) : (
              <div className="dev-scroll">
                <table className="dev-table">
                  <thead>
                    <tr>
                      <th>Started</th>
                      <th>Mode</th>
                      <th>Took</th>
                      <th>Verdict</th>
                      <th className="n">Stored</th>
                      <th>Gate</th>
                      <th className="n">Fields</th>
                      <th className="n">s / product</th>
                      <th className="n">$</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.runs.map((r) => (
                      <RunRow key={r.id} domain={domain} run={r} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="dev-note">
              A run with no verdict never reached the catalogue — a plan failed, the host asked us to
              wait, or the site was gated — and its log is the only account of why. Logs are kept
              from 2026-09-22; earlier runs wrote theirs to the worker&rsquo;s disk.
            </p>
          </section>

          <Changes domain={domain} go={go} />
          <Hosts domain={domain} />
        </>
      )}
    </Gate>
  );
}

// What each run added and removed — how the catalogue has moved over time. Its
// own request: it reads the catalogue, and nothing above waits for it.
function Changes({ domain, go }) {
  const { data, state } = useDevLoad(() => DevEndpoints.getChanges(domain), [domain]);
  return (
    <section className="dev-section">
      <h2 className="dev-section-h">
        Changes — what came and went
        <span className="dev-count-k">
          {' '}·{' '}
          <button type="button" className="dev-link" onClick={() => go({ brandId: domain, category: 'products' })}>
            open the catalogue →
          </button>
        </span>
      </h2>
      {state === 'loading' && <div className="dev-muted">counting…</div>}
      {state !== 'loading' && state !== 'ready' && <div className="dev-muted">{state}</div>}
      {data && data.changes.length === 0 && <div className="dev-muted">nothing stored yet</div>}
      {data && data.changes.length > 0 && (
        <div className="dev-scroll">
          <table className="dev-table">
            <thead>
              <tr>
                <th>Run</th>
                <th className="n">Added</th>
                <th className="n">Removed</th>
                <th>Which</th>
              </tr>
            </thead>
            <tbody>
              {data.changes.map((c) => (
                <tr key={c.run_id}>
                  <td>
                    <button type="button" className="dev-link" onClick={() => go({ brandId: domain, category: 'products', token: c.run_id })}>
                      {dateShort(c.at)}
                    </button>{' '}
                    <span className="dev-muted">{ago(c.at)}</span>
                  </td>
                  <td className="n">{c.added ? `+${n(c.added)}` : '—'}</td>
                  <td className="n">{c.removed ? `−${n(c.removed)}` : '—'}</td>
                  <td className="wrap dev-muted">
                    {c.added_names.length > 0 && <div>+ {c.added_names.join(', ')}{c.added > c.added_names.length ? ` … and ${c.added - c.added_names.length} more` : ''}</div>}
                    {c.removed_names.length > 0 && <div>− {c.removed_names.join(', ')}{c.removed > c.removed_names.length ? ` … and ${c.removed - c.removed_names.length} more` : ''}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="dev-note">
        A product is added at the run that first saw it and removed at the first run that read
        the catalogue and did not. A run that failed before reading anything removes nothing.
      </p>
    </section>
  );
}

function took(run) {
  if (!run.started_at || !run.finished_at) return run.finished_at || run.abandoned ? '—' : 'running';
  const s = (new Date(run.finished_at) - new Date(run.started_at)) / 1000;
  if (Number.isNaN(s)) return '—';
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${(s / 60).toFixed(0)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

const EXIT = { 0: 'ok', 1: 'degraded', 2: 'failed' };

// One run, and — opened — what it wrote down as it went.
function RunRow({ domain, run }) {
  const [open, setOpen] = useState(false);
  const cov = run.coverage || {};
  const card = run.card;
  let verdict = cov.verdict;
  if (!verdict) {
    if (run.mode === 'learn' && run.exit_status != null) {
      const gained = (run.fields_gained || []).length;
      verdict = `learned · ${n(run.rules || 0)} rules from ${n(run.pages || 0)} pages`
        + (gained ? ` · ${gained} new field${gained === 1 ? '' : 's'}` : ' · no new fields');
    } else if (run.mode === 'sweep' && run.exit_status != null) {
      // Stock only: what the feed said, and how much of it moved.
      verdict = run.reason
        ? `sweep · skipped · ${run.reason}`
        : `sweep · ${n(run.checked || 0)} checked · ${n(run.changed || 0)} changed · ${Math.round(run.seconds || 0)} s`;
    } else if (run.abandoned) verdict = 'lost · worker gone';
    else if (run.exit_status == null) verdict = 'running';
    else if (run.reason) verdict = `no verdict · ${run.reason}`;
    else verdict = `${EXIT[run.exit_status] || run.exit_status} · no catalogue`;
  }
  return (
    <>
      <tr>
        <td>{dateShort(run.started_at)} <span className="dev-muted">{ago(run.started_at)}</span></td>
        <td>{run.mode}</td>
        <td>{took(run)}</td>
        <td className={cov.verdict === 'ok' || run.mode === 'learn' || run.mode === 'sweep' ? 'wrap' : 'wrap dev-strong'}>
          {verdict}
          {(cov.reasons || []).length > 0 && <div className="dev-why">{cov.reasons.join(' · ')}</div>}
        </td>
        <td className="n">{cov.extracted == null ? '—' : n(cov.extracted)}</td>
        <td className="wrap">
          {!card ? '—' : card.required_ok ? 'pass' : <span className="dev-strong">fail</span>}
          {card && Object.keys(card.required_gaps || {}).length > 0 && (
            <span className="dev-muted">
              {' '}· {Object.entries(card.required_gaps).map(([k, v]) => `${k} ${Math.round(v * card.products)}`).join(', ')}
            </span>
          )}
        </td>
        <td className="n">{card ? pct(card.fields_filled) : '—'}</td>
        <td className="n">{card ? secs(card.seconds_per_product) : '—'}</td>
        <td className="n">{card ? usd(card.cost_usd, 3) : '—'}</td>
        <td>
          <button type="button" className="dev-act" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? 'close' : 'log'}
          </button>
        </td>
      </tr>
      {open && (
        <tr className="dev-log-row">
          <td colSpan={10}><RunLog domain={domain} runId={run.id} /></td>
        </tr>
      )}
    </>
  );
}

function RunLog({ domain, runId }) {
  const { data, state } = useDevLoad(() => DevEndpoints.getRunLog(domain, runId), [domain, runId]);
  if (state === 'loading') return <div className="dev-muted">reading the log…</div>;
  if (state !== 'ready') return <div className="dev-muted">{state}</div>;
  const t0 = data.events.length ? new Date(data.events[0].t).getTime() : 0;
  return (
    <table className="dev-table">
      <tbody>
        {data.events.map((e, i) => {
          const { t, event, ...rest } = e;
          const dt = t ? Math.max(0, (new Date(t).getTime() - t0) / 1000) : null;
          return (
            <tr key={i}>
              <td className="n dev-muted">{dt == null ? '' : `+${dt < 60 ? `${dt.toFixed(1)}s` : `${(dt / 60).toFixed(1)}m`}`}</td>
              <td className="dev-strong">{event}</td>
              <td className="wrap">
                {Object.entries(rest).map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join('  ')}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// Loaded after the page has painted: the ledger behind it is hundreds of small
// objects, and nothing above needs it.
function Hosts({ domain }) {
  const { data, state } = useDevLoad(() => DevEndpoints.getHosts(domain), [domain]);
  return (
    <section className="dev-section">
      <h2 className="dev-section-h">Hosts — how the site answers, last 7 days</h2>
      {state === 'loading' && <div className="dev-muted">reading the request ledger…</div>}
      {state !== 'loading' && state !== 'ready' && <div className="dev-muted">{state}</div>}
      {data && data.hosts.length === 0 && (
        <div className="dev-muted">no requests recorded this week — the ledger fills as the daemon runs</div>
      )}
      {data && data.hosts.length > 0 && (
        <div className="dev-scroll">
          <table className="dev-table dev-table-sub">
            <thead>
              <tr>
                <th>Host</th>
                <th className="n">Requests</th>
                <th className="n">OK</th>
                <th className="n">Refused</th>
                <th className="n">Slow down</th>
                <th className="n">Errored</th>
                <th className="n">Avg ms</th>
              </tr>
            </thead>
            <tbody>
              {data.hosts.map((h) => (
                <tr key={h.host}>
                  <td className="mono">{h.host}</td>
                  <td className="n">{n(h.requests)}</td>
                  <td className="n">{n(h.ok)}</td>
                  <td className="n">{n(h.refused)}</td>
                  <td className="n">{n(h.busy)}</td>
                  <td className="n">{n(h.errored)}</td>
                  <td className="n">{n(h.avg_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
