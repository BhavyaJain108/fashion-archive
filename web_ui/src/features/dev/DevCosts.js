import React from 'react';

import DevEndpoints from '../../shared/api/dev';
import useDevLoad, { Gate } from './useDevLoad';
import { ago, gb, n, secs, usd } from './format';

const TEN_MINUTES = 10 * 60 * 1000;

// Our own ledger first — exact, and ours. The providers' figures after, each in
// its own slot, read from their own APIs and cached ten minutes on the server.
// A provider that cannot be reached says so in its slot; nothing else waits.
function Provider({ title, p, children }) {
  return (
    <section className="dev-section">
      <h2 className="dev-section-h">{title}</h2>
      {p.ok ? children : <div className="dev-muted">not connected · {p.error}</div>}
    </section>
  );
}

// A per-day series as rows: the date, a bar for the amount, the amount.
function Series({ rows, max }) {
  const top = max || Math.max(...rows.map((r) => r.usd), 0) || 1;
  return (
    <table className="dev-table dev-table-sub">
      <tbody>
        {rows.map((r) => (
          <tr key={r.date}>
            <td className="key">{r.date}</td>
            <td className="bar">
              <span className="dev-bar-track">
                <span className="dev-bar" style={{ width: `${Math.min(100, Math.round((r.usd / top) * 100))}%` }} />
              </span>
            </td>
            <td className="n">{usd(r.usd)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function DevCosts() {
  const { data, state } = useDevLoad(() => DevEndpoints.getCosts(), [], TEN_MINUTES, 'costs');

  return (
    <Gate state={state}>
      {data && (
        <>
          <div className="dev-head">
            <h1 className="dev-title">Costs</h1>
            <div className="dev-stamp">read {ago(data.generated_at)} &middot; providers cached ten minutes</div>
          </div>

          <div className="dev-totals">
            <div className="dev-total">
              <span className="dev-total-n">
                {usd(data.finder.usd)} <span className="dev-muted">/ {usd(data.finder.cap_usd, 0)}</span>
              </span>
              <span className="dev-total-k">finder today · {n(data.finder.calls)} calls</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{data.providers.anthropic.ok ? usd(data.providers.anthropic.month_usd) : '—'}</span>
              <span className="dev-total-k">anthropic this month</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{data.providers.cloudflare.ok ? gb(data.providers.cloudflare.bytes) : '—'}</span>
              <span className="dev-total-k">in the bucket</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{data.providers.render.ok ? usd(data.providers.render.list_usd_month, 0) : '—'}</span>
              <span className="dev-total-k">render plans, list / month</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{data.providers.render.ok ? `${data.providers.render.bandwidth_gb_month} GB` : '—'}</span>
              <span className="dev-total-k">render bandwidth this month</span>
            </div>
          </div>

          <section className="dev-section">
            <h2 className="dev-section-h">Finder — learning field rules</h2>
            {Object.keys(data.finder.history).length === 0 && !data.finder.usd ? (
              <div className="dev-muted">nothing spent yet</div>
            ) : (
              <Series
                rows={[...Object.entries(data.finder.history).map(([date, v]) => ({ date, usd: v })), { date: data.finder.day, usd: data.finder.usd }].slice(-30)}
                max={data.finder.cap_usd || undefined}
              />
            )}
            <p className="dev-note">
              One model call per product page, only for fields the archive has never looked for on
              that brand. Stops for the day at the cap and says so; a budget stop is not recorded as
              evidence the field is absent.
            </p>
          </section>

          <section className="dev-section">
            <h2 className="dev-section-h">Per brand — last run</h2>
            {data.brands.length === 0 ? (
              <div className="dev-muted">no scored runs yet</div>
            ) : (
              <div className="dev-scroll">
                <table className="dev-table dev-table-sub">
                  <thead>
                    <tr>
                      <th>Brand</th>
                      <th className="n">Products</th>
                      <th className="n">$ run</th>
                      <th className="n">s / product</th>
                      <th>Scored</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...data.brands].sort((a, b) => (b.cost_usd || 0) - (a.cost_usd || 0)).map((b) => (
                      <tr key={b.domain}>
                        <td>{b.name} <span className="dev-domain">{b.domain}</span></td>
                        <td className="n">{n(b.products)}</td>
                        <td className="n">{usd(b.cost_usd, 3)}</td>
                        <td className="n">{secs(b.seconds_per_product)}</td>
                        <td>{ago(b.scored_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <Provider title="Anthropic — the organisation's cost report" p={data.providers.anthropic}>
            <Series rows={data.providers.anthropic.days.slice(-14)} />
            <div className="dev-stamp">{usd(data.providers.anthropic.window_usd)} over the last 30 days</div>
          </Provider>

          <Provider title="Cloudflare R2 — the bucket" p={data.providers.cloudflare}>
            <table className="dev-table dev-table-sub">
              <tbody>
                <tr><td className="key">stored</td><td className="wrap">{gb(data.providers.cloudflare.bytes)} · {n(data.providers.cloudflare.objects)} objects · as of {data.providers.cloudflare.as_of}</td></tr>
                <tr><td className="key">storage at list</td><td className="wrap">{usd(data.providers.cloudflare.storage_usd_month)} / month after the 10 GB free</td></tr>
                <tr><td className="key">egress</td><td className="wrap">free — the reason the archive lives here</td></tr>
              </tbody>
            </table>
          </Provider>

          <Provider title="Render — services on their plans" p={data.providers.render}>
            <div className="dev-scroll">
              <table className="dev-table dev-table-sub">
                <thead>
                  <tr>
                    <th>Service</th>
                    <th>Kind</th>
                    <th>Plan</th>
                    <th className="n">List / month</th>
                    <th className="n">Bandwidth this month</th>
                  </tr>
                </thead>
                <tbody>
                  {data.providers.render.services.map((s) => (
                    <tr key={s.name}>
                      <td className="mono">{s.name}{s.suspended ? <span className="dev-muted"> · suspended</span> : ''}</td>
                      <td>{s.kind}</td>
                      <td>{s.plan}</td>
                      <td className="n">{s.list_usd_month == null ? '—' : usd(s.list_usd_month, 0)}</td>
                      <td className="n">{s.bandwidth_gb_month == null ? '—' : `${s.bandwidth_gb_month.toFixed(1)} GB`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <table className="dev-table dev-table-sub">
              <tbody>
                <tr>
                  <td className="key">bandwidth</td>
                  <td className="wrap">
                    {data.providers.render.bandwidth_gb_month} GB this month · {usd(data.providers.render.bandwidth_overage_usd)} overage
                    <span className="dev-muted"> at $0.15/GB above {data.providers.render.bandwidth_included_gb} GB included</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <p className="dev-note">
              Render publishes no billing endpoint. Plan prices are list; bandwidth is metered per
              service by Render&rsquo;s own API. The scraper writes each object once because this
              line once reached 312 GB in a week.
            </p>
          </Provider>
        </>
      )}
    </Gate>
  );
}
