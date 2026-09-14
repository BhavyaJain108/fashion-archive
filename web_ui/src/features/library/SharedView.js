import React, { useEffect, useState } from 'react';
import ShareEndpoints from '../../shared/api/share';
import ApiClient from '../../shared/api/client';
import './SharedView.css';

// What a link opens for someone with no account: one look, one show, or one
// album. Read-only, and it asks the server for exactly that one thing.
function SharedView({ token }) {
  const [state, setState] = useState({ loading: true, data: null, error: '' });

  useEffect(() => {
    let cancelled = false;
    ShareEndpoints.resolveShare(token)
      .then((data) => { if (!cancelled) setState({ loading: false, data, error: '' }); })
      .catch((e) => { if (!cancelled) setState({ loading: false, data: null, error: e.message }); });
    return () => { cancelled = true; };
  }, [token]);

  if (state.loading) {
    return <div className="ar-page"><div className="ar-loading"><span className="headline">Opening</span></div></div>;
  }
  if (state.error || !state.data) {
    return (
      <div className="ar-page shv">
        <div className="ar-empty"><span className="headline">This link has nothing behind it</span>
          <span>{state.error || 'It may have been revoked, or never existed.'}</span></div>
      </div>
    );
  }

  const d = state.data;
  return (
    <div className="ar-page shv">
      <div className="shv-top"><span className="topbar-logo">ARCHIVE</span><span className="shv-kind">{d.kind}</span></div>

      {d.kind === 'look' && (
        <div className="shv-one">
          <img className="shv-img" src={ApiClient.getImageUrl(d.look.image_path)} alt={`Look ${d.look.look_number}`} />
          <div className="shv-cap">{d.look.designer} {d.look.season_name ? `· ${d.look.season_name}` : ''} · {String(d.look.look_number).padStart(2, '0')}</div>
        </div>
      )}

      {d.kind === 'show' && (
        <>
          <div className="shv-head"><span className="shv-name">{d.show.designer}</span><span className="shv-sub">{d.show.subtitle}</span></div>
          {!d.available ? (
            <div className="ar-empty"><span className="headline">Not available yet</span>
              <span>The owner has not opened this show recently enough for its pictures to be held here.</span></div>
          ) : (
            <div className="shv-grid">
              {d.images.map((p, i) => (
                <div className="shv-tile" key={p || i}>
                  <img src={ApiClient.getImageUrl(p)} alt={`Look ${i + 1}`} loading="lazy" />
                  <span className="shv-tile-cap">{String(i + 1).padStart(2, '0')}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {d.kind === 'album' && (
        <>
          <div className="shv-head"><span className="shv-name">{d.album.name}</span><span className="shv-sub">{d.items.length} saved</span></div>
          {d.items.length === 0 ? (
            <div className="ar-empty"><span className="headline">Empty album</span></div>
          ) : (
            <div className="shv-grid">
              {d.items.map((it, i) => (
                <div className="shv-tile" key={i}>
                  {it.image_path
                    ? <img src={ApiClient.getImageUrl(it.image_path)} alt={it.collection.designer} loading="lazy" />
                    : <span className="shv-tile-blank">{it.kind}</span>}
                  <span className="shv-tile-cap">{it.collection.designer}{it.look?.number ? ` · ${String(it.look.number).padStart(2, '0')}` : ''}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default SharedView;
