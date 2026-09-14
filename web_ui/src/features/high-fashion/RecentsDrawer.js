import React, { useEffect } from 'react';
import { cleanDesignerName } from '../../shared/lib/designerName';
import { usePersistentState } from '../../shared/hooks/usePersistentState';

// Where you have been, at the bottom of the sidebar.
//
// Closed it is one rectangle reading RECENTLY SEEN. Open it is a fifth of
// the sidebar, and the show list above it gives up exactly that much — the
// sidebar itself does not get taller, and nothing spills out of the bottom
// of the viewport. That relationship is CSS, not arithmetic here: the
// drawer is `flex: 0 0 20%` of the sidebar's own height and the list above
// is `flex: 1` with `min-height: 0`, so the list is whatever is left. See
// `.hf2-recents` in HighFashionPage.css.
//
// Presentational apart from one thing: whether it is open, which is this
// component's own business and is remembered per browser. Everything else —
// the rows, and what opening one means — is a prop.
//
// `onOpen` is handed the recents row itself. The page passes it straight to
// the same handler a row in the show list goes through, which is why a row
// here writes the address bar and keeps the previous show on screen while
// the new one streams, without this file knowing any of that.
function RecentsDrawer({ recents = [], loading = false, onOpen, onReload }) {
  const [open, setOpen] = usePersistentState('hf-recents-open', false);

  // The server's list moves every time a show is opened and nothing tells
  // this client that it did, so it is asked again at the one moment the
  // reader has said they want to look at it. Closed, it costs nothing.
  useEffect(() => {
    if (open && onReload) onReload();
  }, [open, onReload]);

  return (
    <div className={`hf2-recents ${open ? 'open' : ''}`}>
      {/* The rectangle. It is the whole of the collapsed state, and stays
          put as the header when the drawer is open. */}
      <button
        type="button"
        className="hf2-recents-head"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        title={open ? 'Hide recently seen' : 'Show recently seen'}
      >
        <span className="label">RECENTLY SEEN</span>
        {recents.length > 0 && <span className="count">{recents.length}</span>}
        {/* Points the way it will move: up to open, down to close. */}
        <span className="chev" aria-hidden="true">{open ? '▾' : '▴'}</span>
      </button>

      {/* Rendered only when open. Closed, the drawer is one rectangle and
          has nothing inside it to scroll. */}
      {open && (
        <div className="hf2-recents-scroll">
          {recents.length === 0 ? (
            <div className="hf2-recents-empty">
              {loading ? 'Loading…' : 'No shows opened yet'}
            </div>
          ) : (
            recents.map(row => (
              <button
                key={row.collection_id || row.url}
                type="button"
                className="hf2-recent-item"
                onClick={() => onOpen && onOpen(row)}
                title={[cleanDesignerName(row.designer || ''), row.season, row.year]
                  .filter(Boolean).join(' — ')}
              >
                <span className="name">{cleanDesignerName(row.designer || '')}</span>
                <span className="meta">
                  {[row.season, row.year].filter(Boolean).join(' ')}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default RecentsDrawer;
