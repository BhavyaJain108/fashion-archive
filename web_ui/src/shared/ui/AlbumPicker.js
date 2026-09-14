import React, { useEffect, useRef, useState } from 'react';
import './AlbumPicker.css';

// Which album, and nothing else.
//
//   <AlbumPicker albums={...} heading="3 selected"
//                choices={[{value:'look',label:'Look 07'}, ...]}
//                onPick={(albumId, choice) => {}}
//                onCreate={(name, choice) => {}}
//                onClose={...} busy={bool} error={err} />
//
// One component in two places — the library's selection bar and the archive
// page's viewer — because "put this in an album" is one act and the reader
// should not meet two versions of it. The two callers differ only in what
// they hand it: the library has already chosen WHAT (the selection), the
// archive page has a look and the show it belongs to and so passes `choices`.
//
// It is NOT the star, and it never will be. The star is one click, no prompt,
// no menu — a saved thing. This is the deliberate second act, behind a
// labelled control, and the two are never the same button. That separation is
// the whole reason this is a component of its own rather than a mode of
// SaveStar.
//
// Nothing here writes. `onPick` and `onCreate` are the caller's, so the hook
// that owns albums stays the only thing that talks to the server, and this
// panel can be rendered by a page that holds no album state at all.
function AlbumPicker({
  albums = [],
  heading = 'Add to album',
  choices = null,
  onPick,
  onCreate,
  onClose,
  busy = false,
  error = null,
}) {
  // Which of the things the caller could add is being added. The first is the
  // default because the callers list the narrower thing first: adding the
  // look in front of you is the common act, and the whole show is the one you
  // go looking for.
  const [choice, setChoice] = useState(
    choices && choices.length ? choices[0].value : null);
  const [name, setName] = useState('');
  const [naming, setNaming] = useState(false);

  const panel = useRef(null);
  const nameField = useRef(null);

  // Escape closes it, from anywhere. A panel that can only be dismissed by
  // finding a particular button is a panel a reader gets stuck in — and this
  // one covers the thing they were looking at.
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        if (onClose) onClose();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  useEffect(() => { if (naming && nameField.current) nameField.current.focus(); }, [naming]);

  const create = () => {
    const trimmed = name.trim();
    // The server decides whether the name is taken (409); what is refused
    // here is the one name it could never store.
    if (!trimmed || busy) return;
    if (onCreate) onCreate(trimmed, choice);
  };

  return (
    <div className="alp-scrim" onMouseDown={() => { if (onClose) onClose(); }}>
      <div
        className="alp-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`Add to album — ${heading}`}
        ref={panel}
        // The scrim closes on a press outside the panel; a press inside it is
        // not outside it.
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="alp-head">
          <span className="alp-title">Add to album</span>
          <span className="alp-heading">{heading}</span>
        </div>

        {/* What is being added, when the caller has more than one candidate.
            Named, and visible while the album is chosen, because "add to
            Resort" means two different things depending on which of these is
            lit and the reader must be able to see which. */}
        {choices && choices.length > 1 && (
          <div className="alp-choices" role="group" aria-label="What to add">
            {choices.map(c => (
              <button
                key={c.value}
                type="button"
                className={`ar-chip alp-choice ${c.value === choice ? 'selected' : ''}`}
                aria-pressed={c.value === choice}
                onClick={() => setChoice(c.value)}
                disabled={busy}
              >{c.label}</button>
            ))}
          </div>
        )}

        <div className="alp-list ar-scroll">
          {albums.length === 0 ? (
            <div className="alp-empty">No albums yet. Make the first one below.</div>
          ) : albums.map(album => (
            <button
              key={album.id}
              type="button"
              className="alp-album"
              onClick={() => { if (onPick) onPick(album.id, choice); }}
              disabled={busy}
            >
              <span className="alp-album-name">{album.name}</span>
              <span className="alp-album-count">{album.item_count}</span>
            </button>
          ))}
        </div>

        {/* Making one from here rather than sending the reader to the library
            to make it and back again to use it. The album is created and the
            thing is added in the same press. */}
        <div className="alp-new">
          {naming ? (
            <>
              <input
                ref={nameField}
                className="ar-input alp-name"
                type="text"
                value={name}
                placeholder="Album name"
                aria-label="New album name"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') create(); }}
                disabled={busy}
              />
              <button
                type="button"
                className="ar-btn alp-create"
                onClick={create}
                disabled={busy || !name.trim()}
              >Create and add</button>
            </>
          ) : (
            <button
              type="button"
              className="ar-btn ar-btn-block alp-new-btn"
              onClick={() => setNaming(true)}
              disabled={busy}
            >New album</button>
          )}
        </div>

        {error && <div className="alp-error" role="alert">{error.message || String(error)}</div>}

        <div className="alp-foot">
          <button type="button" className="ar-btn alp-cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

export default AlbumPicker;
