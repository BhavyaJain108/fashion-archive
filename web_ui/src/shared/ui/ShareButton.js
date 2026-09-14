import React, { useState } from 'react';
import ShareEndpoints from '../api/share';
import './ShareButton.css';

// One button: mint a link, put it on the clipboard, show it. `onMint` returns
// a promise of the token; what is being shared is the caller's business.
function ShareButton({ onMint, label = 'SHARE' }) {
  const [state, setState] = useState({ url: '', copied: false, error: '' });

  const share = async () => {
    setState({ url: '', copied: false, error: '' });
    try {
      const token = await onMint();
      const url = ShareEndpoints.shareUrl(token);
      let copied = false;
      try { await navigator.clipboard.writeText(url); copied = true; } catch (e) { /* shown below */ }
      setState({ url, copied, error: '' });
    } catch (e) {
      setState({ url: '', copied: false, error: e.message || 'Could not share' });
    }
  };

  return (
    <span className="share">
      <button type="button" className="ar-btn share-btn" onClick={share}>{label}</button>
      {state.url && (
        <span className="share-result">
          <input className="ar-input share-url" readOnly value={state.url}
                 onFocus={(e) => e.target.select()} />
          <span className="share-note">{state.copied ? 'Copied' : 'Copy this link'}</span>
        </span>
      )}
      {state.error && <span className="share-note">{state.error}</span>}
    </span>
  );
}

export default ShareButton;
