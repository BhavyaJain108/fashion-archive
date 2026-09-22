import React, { useMemo, useState } from 'react';

import DevEndpoints from '../../shared/api/dev';
import useDevLoad, { Gate } from './useDevLoad';
import { ago, due, n, pct, secs, usd } from './format';

const MINUTE = 60 * 1000;

// Where a running scrape is: the phase, and a bar when the phase has a length.
// Discovery and finalising have none — the bar only claims to know what it knows.
function Progress({ p }) {
  if (!p) return <span className="dev-muted">starting</span>;
  const known = p.total != null && p.total > 0 && p.done != null;
  const share = known ? Math.min(100, Math.round((p.done / p.total) * 100)) : null;
  return (
    <span className="dev-progress" title={p.updated_at ? `as of ${ago(p.updated_at)}` : ''}>
      <span className="dev-progress-k">{p.phase}</span>
      {known && (
        <>
          <span className="dev-bar-track dev-progress-track"><span className="dev-bar" style={{ width: `${share}%` }} /></span>
          <span className="dev-progress-v">{n(p.done)} / {n(p.total)}</span>
        </>
      )}
    </span>
  );
}

// A claimed brand whose worker has stopped beating is the one state that used to
// be invisible: it looks identical to work in progress from the outside.
function statusPill(b) {
  if (b.claimed_by) {
    return b.worker_alive
      ? <Progress p={b.progress} />
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

// Sorting. One key, one direction, blanks last whichever way. The choice is kept
// per tab so a reload does not undo it.
const COLUMNS = [
  { key: 'name', label: 'Brand', value: (b) => b.name.toLowerCase() },
  { key: 'status', label: '', value: (b) => (b.claimed_by ? 0 : b.enabled ? 1 : 2) },
  { key: 'live_products', label: 'Products', n: true },
  { key: 'gate', label: 'Gate', value: (b) => (b.gate == null ? null : b.gate ? 1 : 0) },
  { key: 'fields_filled', label: 'Fields', n: true },
  { key: 'seconds_per_product', label: 's / product', n: true },
  { key: 'cost_usd', label: '$ run', n: true },
  { key: 'last_run', label: 'Last run' },
  { key: 'next_due', label: 'Next' },
];

function valueOf(col, b) {
  const v = col.value ? col.value(b) : b[col.key];
  return v === undefined ? null : v;
}

function sorted(rows, key, dir) {
  const col = COLUMNS.find((c) => c.key === key) || COLUMNS[0];
  const sign = dir === 'desc' ? -1 : 1;
  return [...rows].sort((a, b) => {
    const va = valueOf(col, a);
    const vb = valueOf(col, b);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (va < vb) return -sign;
    if (va > vb) return sign;
    return 0;
  });
}

function readSort() {
  try {
    const raw = window.sessionStorage.getItem('dev:sort');
    return raw ? JSON.parse(raw) : { key: 'name', dir: 'asc' };
  } catch {
    return { key: 'name', dir: 'asc' };
  }
}

// A brand joins by its domain. It is on the schedule and due at once from the
// moment this returns; "show on the site" is whether the public My Brands page
// lists it, which is the roster's business and not the scraper's.
function AddBrand({ onAdded }) {
  const [open, setOpen] = useState(false);
  const [domain, setDomain] = useState('');
  const [name, setName] = useState('');
  const [show, setShow] = useState(true);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    const d = domain.trim().toLowerCase().replace(/^https?:\/\//, '').split('/')[0];
    if (!d || !d.includes('.')) {
      setNote('Enter the shop’s domain, like kuurth.com');
      return;
    }
    setBusy(true);
    setNote(null);
    const r = await DevEndpoints.addBrand(d, name.trim(), show);
    setBusy(false);
    if (r.error) {
      setNote(r.error);
      return;
    }
    setNote(`${r.name} added${r.already_scheduled ? ' (was already on the schedule; now due)' : ' and due now'}`);
    setDomain('');
    setName('');
    await onAdded();
  };

  return (
    <div className="dev-add">
      <button type="button" className="dev-act" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? 'close' : 'add a brand'}
      </button>
      {open && (
        <form className="dev-add-form" onSubmit={submit}>
          <input className="ar-input" placeholder="DOMAIN" aria-label="Domain" value={domain} onChange={(e) => { setDomain(e.target.value); setNote(null); }} />
          <input className="ar-input" placeholder="NAME (OPTIONAL)" aria-label="Display name" value={name} onChange={(e) => setName(e.target.value)} />
          <label className="dev-check">
            <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} /> show on the site
          </label>
          <button type="submit" className="dev-act" disabled={busy}>add and scrape now</button>
        </form>
      )}
      {note && <div className="dev-why">{note}</div>}
    </div>
  );
}

export default function DevOverview({ go }) {
  const { data, state, refreshing, reload } = useDevLoad(() => DevEndpoints.getOverview(), [], MINUTE, 'overview');
  const [busy, setBusy] = useState({});
  const [note, setNote] = useState({});
  const [sort, setSort] = useState(readSort);
  const [picked, setPicked] = useState(() => new Set());
  const [bulkNote, setBulkNote] = useState(null);
  const [bulkBusy, setBulkBusy] = useState(false);

  const rows = useMemo(() => (data ? sorted(data.brands, sort.key, sort.dir) : []), [data, sort]);

  const sortBy = (key) => {
    const next = sort.key === key ? { key, dir: sort.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' };
    setSort(next);
    try { window.sessionStorage.setItem('dev:sort', JSON.stringify(next)); } catch { /* fine */ }
  };

  const act = async (domain, fn) => {
    setBusy((m) => ({ ...m, [domain]: true }));
    setNote((m) => ({ ...m, [domain]: null }));
    const r = await fn(domain);
    setBusy((m) => ({ ...m, [domain]: false }));
    if (r.error) setNote((m) => ({ ...m, [domain]: r.error }));
    await reload();
  };

  const toggle = (domain) => {
    setPicked((s) => {
      const next = new Set(s);
      if (next.has(domain)) next.delete(domain); else next.add(domain);
      return next;
    });
  };

  const allShown = rows.length > 0 && rows.every((b) => picked.has(b.domain));
  const toggleAll = () => setPicked(allShown ? new Set() : new Set(rows.map((b) => b.domain)));

  const bulk = async (action) => {
    const domains = [...picked];
    if (!domains.length) return;
    setBulkBusy(true);
    setBulkNote(null);
    const r = await DevEndpoints.batch(action, domains);
    setBulkBusy(false);
    if (r.error) {
      setBulkNote(r.error);
    } else {
      const tally = {};
      Object.values(r.results).forEach((v) => { tally[v] = (tally[v] || 0) + 1; });
      setBulkNote(Object.entries(tally).map(([k, v]) => `${v} ${k}`).join(' · '));
      setPicked(new Set());
    }
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
                <span key={b.domain} className="dev-now-item">
                  <button type="button" className="dev-link" onClick={() => go({ brandId: b.domain })}>{b.name}</button>
                  <span className="dev-muted"> · {b.claimed_by} · since {ago(b.claimed_at)} · </span>
                  <Progress p={b.progress} />
                </span>
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

          <AddBrand onAdded={reload} />

          <div className="dev-bulk" role="group" aria-label="Selected brands">
            <span className="dev-bulk-k">{picked.size} selected</span>
            <button type="button" className="dev-act" disabled={bulkBusy || !picked.size} onClick={() => bulk('run')}>run selected</button>
            <button type="button" className="dev-act" disabled={bulkBusy || !picked.size} onClick={() => bulk('pause')}>pause selected</button>
            <button type="button" className="dev-act" disabled={bulkBusy || !picked.size} onClick={() => bulk('resume')}>resume selected</button>
            {bulkNote && <span className="dev-muted">{bulkNote}</span>}
          </div>

          <div className="dev-scroll">
            <table className="dev-table">
              <thead>
                <tr>
                  <th>
                    <input type="checkbox" aria-label="Select every brand shown" checked={allShown} onChange={toggleAll} />
                  </th>
                  {COLUMNS.map((c) => (
                    <th key={c.key} className={c.n ? 'n' : ''} aria-sort={sort.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                      {c.label ? (
                        <button type="button" className="dev-sort" onClick={() => sortBy(c.key)}>
                          {c.label}{sort.key === c.key ? (sort.dir === 'asc' ? ' ▴' : ' ▾') : ''}
                        </button>
                      ) : null}
                    </th>
                  ))}
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((b) => (
                  <tr key={b.domain} className={picked.has(b.domain) ? 'dev-row-picked' : ''}>
                    <td>
                      <input type="checkbox" aria-label={`Select ${b.name}`} checked={picked.has(b.domain)} onChange={() => toggle(b.domain)} />
                    </td>
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
            there. Two workers run at once, so a selection is a queue, not a burst. Nothing here talks
            to a worker directly.
          </p>
        </>
      )}
    </Gate>
  );
}
