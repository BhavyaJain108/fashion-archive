import React, { useState } from 'react';

import DevEndpoints from '../../shared/api/dev';
import useDevLoad, { Gate, Stamp } from './useDevLoad';

// The API, read off the running server. Every operation is declared once in the
// registry and answers three ways — the HTTP route, the MCP tool, this page — so
// what is shown here is what is served, and a new operation appears here with its
// try-it form the moment it is registered. Routes from before the registry are
// listed as legacy under each family, each with what replaces it.

const METHOD_WORD = { GET: 'read', POST: 'write', PUT: 'write', PATCH: 'write', DELETE: 'delete' };

function Method({ m }) {
  return <span className={`dev-pill dev-api-method ${METHOD_WORD[m] || 'read'}`}>{m}</span>;
}

// One input per declared parameter, shaped by its type: a select for a fixed
// choice, a checkbox for a flag, JSON for an object, text for the rest.
function Field({ p, value, onChange }) {
  const id = `api-${p.name}`;
  if (p.choices) {
    return (
      <select id={id} className="dev-api-input" value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
        {!p.required && <option value="">—</option>}
        {p.choices.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    );
  }
  if (p.type === 'boolean') {
    return <input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />;
  }
  return (
    <input
      id={id}
      className="dev-api-input"
      type={p.type === 'integer' || p.type === 'number' ? 'number' : 'text'}
      value={value ?? ''}
      placeholder={p.type === 'object' ? '{ "…": "…" }' : p.type === 'array' ? 'a,b' : ''}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function initial(op) {
  const out = {};
  op.params.forEach((p) => {
    if (op.example && op.example[p.name] !== undefined) out[p.name] = op.example[p.name];
    else if (p.default !== undefined && p.type !== 'boolean') out[p.name] = p.default;
    else if (p.type === 'boolean') out[p.name] = !!p.default;
  });
  return out;
}

// Values as the server will read them: objects parsed from their JSON text, flags
// left out when false, blanks left out.
function prepare(op, values) {
  const out = {};
  op.params.forEach((p) => {
    const v = values[p.name];
    if (v === '' || v === null || v === undefined) return;
    if (p.type === 'boolean') { if (v) out[p.name] = true; return; }
    if (p.type === 'object' && typeof v === 'string') {
      try { out[p.name] = JSON.parse(v); } catch { out[p.name] = v; }
      return;
    }
    out[p.name] = typeof v === 'object' ? JSON.stringify(v) : v;
  });
  return out;
}

const SHOWN = 12000;

function Answer({ a }) {
  const [all, setAll] = useState(false);
  if (!a) return null;
  const text = typeof a.body === 'string' ? a.body : JSON.stringify(a.body, null, 2);
  const cut = !all && text.length > SHOWN;
  return (
    <div className="dev-api-answer">
      <div className="dev-api-answer-head">
        <span className={a.status >= 200 && a.status < 300 ? 'dev-strong' : 'dev-api-bad'}>{a.status || 'no answer'}</span>
        <span className="dev-muted"> · {a.ms} ms · {text.length.toLocaleString()} chars</span>
        <span className="dev-api-url dev-muted"> · {a.url}</span>
      </div>
      <pre className="dev-api-out">{cut ? text.slice(0, SHOWN) : text}</pre>
      {cut && (
        <button type="button" className="dev-link dev-domain" onClick={() => setAll(true)}>show all</button>
      )}
    </div>
  );
}

function TryIt({ op }) {
  const [values, setValues] = useState(() => initial(op));
  const [answer, setAnswer] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async (e) => {
    e.preventDefault();
    setBusy(true);
    setAnswer(await DevEndpoints.call(op.method, op.path, prepare(op, values)));
    setBusy(false);
  };
  return (
    <form className="dev-api-form" onSubmit={run}>
      {op.params.map((p) => (
        <label key={p.name} className="dev-api-field" htmlFor={`api-${p.name}`}>
          <span className="dev-api-k">{p.name}{p.required ? ' *' : ''}</span>
          <Field p={p} value={values[p.name]} onChange={(v) => setValues({ ...values, [p.name]: v })} />
        </label>
      ))}
      <div className="dev-api-run">
        <button type="submit" className="dev-act" disabled={busy}>
          {busy ? 'calling…' : op.writes ? `${op.method} — this writes` : 'call'}
        </button>
      </div>
      <Answer a={answer} />
    </form>
  );
}

function Operation({ op }) {
  const [open, setOpen] = useState(false);
  return (
    <article className="dev-api-op" id={`op-${op.name}`}>
      <div className="dev-api-line">
        <Method m={op.method} />
        <code className="dev-api-path">{op.path}</code>
        {op.owner && <span className="dev-pill idle">owner</span>}
      </div>
      <p className="dev-api-summary">{op.summary}</p>
      {op.detail && <p className="dev-api-detail">{op.detail}</p>}
      <div className="dev-api-meta">
        <span><span className="dev-api-k">mcp tool</span> {op.mcp_tool}</span>
        {op.reads.length > 0 && <span><span className="dev-api-k">reads</span> {op.reads.join(', ')}</span>}
        {op.replaces.length > 0 && <span><span className="dev-api-k">replaces</span> {op.replaces.join(', ')}</span>}
      </div>
      {op.params.length > 0 && (
        <table className="dev-table dev-table-sub dev-api-params">
          <thead><tr><th>Parameter</th><th>Type</th><th>Meaning</th></tr></thead>
          <tbody>
            {op.params.map((p) => (
              <tr key={p.name}>
                <td className="mono">{p.name}{p.required ? ' *' : ''}</td>
                <td>{p.choices ? p.choices.join(' | ') : p.type}{p.default !== undefined && p.default !== '' ? ` = ${JSON.stringify(p.default)}` : ''}</td>
                <td className="wrap">{p.doc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button type="button" className="dev-link dev-domain" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} try it
      </button>
      {open && <TryIt op={op} />}
    </article>
  );
}

function Legacy({ rows }) {
  const [open, setOpen] = useState(false);
  if (!rows.length) return null;
  return (
    <div className="dev-api-legacy">
      <button type="button" className="dev-link dev-domain" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} {rows.length} legacy route{rows.length === 1 ? '' : 's'}
      </button>
      {open && (
        <table className="dev-table">
          <thead><tr><th>Method</th><th>Path</th><th>What</th><th>Replaced by</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.method} ${r.path}`}>
                <td className="mono">{r.method}</td>
                <td className="mono">{r.path}{r.public ? <span className="dev-muted"> · public</span> : ''}</td>
                <td className="wrap">{r.summary || <span className="dev-api-bad">undocumented</span>}</td>
                <td>{r.replaced_by ? <a className="dev-link" href={`#op-${r.replaced_by}`}>{r.replaced_by}</a> : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function DevApi() {
  const { data, state, refreshing, checkedAt } = useDevLoad(() => DevEndpoints.getDocs(), [], 0, 'docs');
  return (
    <Gate state={state}>
      {data && (
        <>
          <div className="dev-head">
            <h1 className="dev-title">API</h1>
            <Stamp data={data} refreshing={refreshing} checkedAt={checkedAt} every="read off the running server" />
          </div>

          <div className="dev-totals">
            <div className="dev-total">
              <span className="dev-total-n">{data.totals.operations}</span>
              <span className="dev-total-k">operations · each an HTTP route and an MCP tool</span>
            </div>
            <div className="dev-total">
              <span className="dev-total-n">{data.totals.legacy}</span>
              <span className="dev-total-k">legacy routes still served</span>
            </div>
            <div className="dev-total">
              <span className={`dev-total-n${data.totals.undocumented ? ' dev-api-bad' : ''}`}>{data.totals.undocumented}</span>
              <span className="dev-total-k">undocumented</span>
            </div>
          </div>

          <p className="dev-note">
            One registry, three doors. An operation is declared once — name, parameters, what it reads —
            and from that come the HTTP route below, the MCP tool of the same name, and this page.
            Assistants connect at <code className="dev-api-path">POST {data.mcp.endpoint}</code> (MCP {data.mcp.protocol},
            {' '}{data.mcp.tools} tools; {data.mcp.auth}). The rule for growing it: one operation per thing,
            extended with parameters, never with sibling paths.
          </p>

          <nav className="dev-api-jump" aria-label="Families">
            {data.families.map((f) => (
              <a key={f.key} className="dev-link" href={`#fam-${f.key}`}>{f.name}</a>
            ))}
          </nav>

          {data.families.map((f) => (
            <section key={f.key} className="dev-section" id={`fam-${f.key}`}>
              <h2 className="dev-section-h">
                {f.name}
                {f.owner && <span className="dev-pill idle dev-api-owner">owner only</span>}
              </h2>
              {f.about && <p className="dev-note">{f.about}</p>}
              {f.operations.map((op) => <Operation key={op.name} op={op} />)}
              <Legacy rows={f.legacy} />
            </section>
          ))}
        </>
      )}
    </Gate>
  );
}
