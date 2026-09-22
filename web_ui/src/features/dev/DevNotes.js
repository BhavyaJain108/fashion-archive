import React, { useState } from 'react';

import DevEndpoints from '../../shared/api/dev';
import useDevLoad from './useDevLoad';
import { ago } from './format';

// The owner's running list of what to change, kept with the archive rather than
// in a chat. Open notes first. `cli notes` prints the same list, so whoever works
// on the deck next starts from it.
export default function DevNotes() {
  const { data, state, reload } = useDevLoad(() => DevEndpoints.getNotes(), [], 0, 'notes');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [showDone, setShowDone] = useState(false);

  const add = async (e) => {
    e.preventDefault();
    const t = text.trim();
    if (!t) {
      setError('Write the note first');
      return;
    }
    setBusy(true);
    setError(null);
    const r = await DevEndpoints.addNote(t);
    setBusy(false);
    if (r.error) {
      setError(r.error);
      return;
    }
    setText('');
    await reload();
  };

  const tick = async (n) => {
    const r = await DevEndpoints.setNoteDone(n.id, !n.done);
    if (r.error) setError(r.error);
    await reload();
  };

  const remove = async (n) => {
    const r = await DevEndpoints.deleteNote(n.id);
    if (r.error) setError(r.error);
    await reload();
  };

  const notes = data ? data.notes : [];
  const open = notes.filter((n) => !n.done);
  const done = notes.filter((n) => n.done);

  return (
    <aside className="dev-aside" aria-label="Notes">
      <h2 className="dev-section-h">
        Notes <span className="dev-count-k">· {open.length} open</span>
      </h2>
      <form className="dev-note-form" onSubmit={add}>
        <textarea
          className="ar-input dev-note-input"
          rows={3}
          placeholder="WHAT SHOULD CHANGE"
          aria-label="New note"
          value={text}
          onChange={(e) => { setText(e.target.value); if (error) setError(null); }}
        />
        <div className="dev-note-row">
          <button type="submit" className="dev-act" disabled={busy}>add note</button>
          {error && <span className="dev-why dev-strong">{error}</span>}
        </div>
      </form>

      {state === 'loading' && <div className="dev-muted">reading…</div>}
      {state !== 'loading' && state !== 'ready' && <div className="dev-muted">{state}</div>}

      <ul className="dev-notes">
        {open.map((n) => (
          <li key={n.id} className="dev-note">
            <input type="checkbox" aria-label="Done" checked={false} onChange={() => tick(n)} />
            <div className="dev-note-body">
              <div className="dev-note-text">{n.text}</div>
              <div className="dev-domain">{ago(n.at)}</div>
            </div>
            <button type="button" className="dev-link dev-note-x" aria-label="Remove note" onClick={() => remove(n)}>✕</button>
          </li>
        ))}
        {data && open.length === 0 && <li className="dev-muted">nothing open</li>}
      </ul>

      {done.length > 0 && (
        <>
          <button type="button" className="dev-link dev-domain" onClick={() => setShowDone(!showDone)}>
            {showDone ? '▾' : '▸'} {done.length} done
          </button>
          {showDone && (
            <ul className="dev-notes">
              {done.map((n) => (
                <li key={n.id} className="dev-note dev-note-done">
                  <input type="checkbox" aria-label="Done" checked onChange={() => tick(n)} />
                  <div className="dev-note-body">
                    <div className="dev-note-text">{n.text}</div>
                    <div className="dev-domain">done {ago(n.done_at)}</div>
                  </div>
                  <button type="button" className="dev-link dev-note-x" aria-label="Remove note" onClick={() => remove(n)}>✕</button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </aside>
  );
}
