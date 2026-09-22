import React, { useState } from 'react';

import DevEndpoints from '../../shared/api/dev';
import useDevLoad, { Gate } from './useDevLoad';
import { ago, dateShort, due, hours, n, pct, secs, usd } from './format';

const MINUTE = 60 * 1000;

// One brand, everything the archive recorded about it. The plan is how we get in;
// the fields are what we get out; the runs are how that has gone; the findings
// are what to do about it. All from the small objects — never the catalogue,
// which has a page of its own.
export default function DevBrand({ domain, go }) {
  const { data, state, reload } = useDevLoad(() => DevEndpoints.getBrand(domain), [domain], MINUTE);
  const [note, setNote] = useState(null);

  const act = async (fn) => {
    setNote(null);
    const r = await fn(domain);
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
              <button
                type="button"
                className="dev-act"
                disabled={!!data.brand.claimed_by}
                onClick={() => act(DevEndpoints.runNow)}
              >
                run now
              </button>
              <button
                type="button"
                className="dev-act"
                onClick={() => act(data.brand.enabled ? DevEndpoints.pause : DevEndpoints.resume)}
              >
                {data.brand.enabled ? 'pause' : 'resume'}
              </button>
              <button type="button" className="dev-act" onClick={() => go({ brandId: domain, category: 'products' })}>
                catalogue →
              </button>
            </div>
          </div>
          {note && <div className="dev-alarm">{note}</div>}

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
              <ol className="dev-findings">
                {data.recommendations.findings.map((f, i) => (
                  <li key={i}>
                    <span className="dev-priority">{f.priority}</span>
                    <span className="dev-finding-h">{f.headline}</span>
                    <span className="dev-finding-a">{f.action}</span>
                  </li>
                ))}
              </ol>
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
              <dl className="dev-kv">
                <dt>composition</dt><dd>{data.plan.composition}</dd>
                <dt>status</dt><dd>{data.plan.status}{data.plan.stale ? ' · stale, re-probed next run' : ''}</dd>
                <dt>transport</dt><dd>{data.plan.transport}</dd>
                <dt>discovery</dt><dd>{data.plan.discovery}{data.plan.sitemap_url ? ` · ${data.plan.sitemap_url}` : ''}</dd>
                <dt>fetch</dt><dd>{data.plan.fetch}</dd>
                <dt>product urls</dt><dd>{data.plan.product_url_prefix || '—'}</dd>
                <dt>currency</dt><dd>{data.plan.currency || '—'}</dd>
                <dt>fingerprinted</dt><dd>{ago(data.plan.fingerprinted_at)}</dd>
              </dl>
            ) : (
              <div className="dev-muted">not probed yet</div>
            )}
            {data.plan && data.plan.tried.length > 0 && (
              <table className="dev-table dev-table-sub">
                <thead>
                  <tr><th>Tried and failed</th><th>When</th><th>Why</th></tr>
                </thead>
                <tbody>
                  {data.plan.tried.map((t, i) => (
                    <tr key={i}>
                      <td>{t.composition}</td>
                      <td>{ago(t.failed_at)}</td>
                      <td className="dev-wrap">{t.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
                      <td className="dev-mono">{f.name}</td>
                      <td title={data.classes[f.class] ? data.classes[f.class][1] : ''}>
                        {f.class} <span className="dev-muted">{data.classes[f.class] ? data.classes[f.class][0] : ''}</span>
                      </td>
                      <td className="n">{pct(f.fill)}</td>
                      <td>
                        {f.rules.length === 0 ? <span className="dev-muted">—</span> : f.rules.map((r, i) => (
                          <div key={i} className="dev-rule">
                            <span className="dev-mono">{r.kind}</span> {r.expression}
                            <span className="dev-muted"> · fired {n(r.hits)}</span>
                          </div>
                        ))}
                      </td>
                      <td className="dev-wrap dev-muted">{f.evidence}</td>
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

          <Hosts domain={domain} />
        </>
      )}
    </Gate>
  );
}

function took(run) {
  if (!run.started_at || !run.finished_at) return run.finished_at ? '—' : 'running';
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
    if (run.abandoned) verdict = 'lost · worker replaced';
    else if (run.exit_status == null) verdict = 'running';
    else verdict = `${EXIT[run.exit_status] || run.exit_status} · no catalogue`;
  }
  return (
    <>
      <tr>
        <td>{dateShort(run.started_at)} <span className="dev-muted">{ago(run.started_at)}</span></td>
        <td>{run.mode}</td>
        <td>{took(run)}</td>
        <td className={cov.verdict === 'ok' ? '' : 'dev-strong'}>
          {verdict}
          {(cov.reasons || []).length > 0 && <div className="dev-why">{cov.reasons.join(' · ')}</div>}
        </td>
        <td className="n">{cov.extracted == null ? '—' : n(cov.extracted)}</td>
        <td>
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
    <ol className="dev-events">
      {data.events.map((e, i) => {
        const { t, event, ...rest } = e;
        const dt = t ? Math.max(0, (new Date(t).getTime() - t0) / 1000) : null;
        return (
          <li key={i}>
            <span className="dev-event-t">{dt == null ? '' : `+${dt < 60 ? `${dt.toFixed(1)}s` : `${(dt / 60).toFixed(1)}m`}`}</span>
            <span className="dev-event-k">{event}</span>
            <span className="dev-event-v">
              {Object.entries(rest).map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join('  ')}
            </span>
          </li>
        );
      })}
    </ol>
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
                <td className="dev-mono">{h.host}</td>
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
      )}
    </section>
  );
}
