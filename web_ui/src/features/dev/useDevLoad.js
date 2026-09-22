import React, { useCallback, useEffect, useRef, useState } from 'react';

import { ago } from './format';

// One loading shape for every machine-room view: a fetcher, an optional refresh
// interval, and the four states a read can be in. Pages render the state, never
// the promise.
//
// A view paints from the last answer it got before it asks again. The API sits
// on another continent from the person reading it and every answer is a handful
// of bucket reads, so a page that was empty for two seconds on every visit read as
// broken. The last answer is kept per view in session storage — this browser tab
// only, gone when it closes — shown at once and marked as being refreshed, then
// replaced. Nothing is trusted longer than the tab.
const PREFIX = 'dev:';

function remembered(key) {
  if (!key) return null;
  try {
    const raw = window.sessionStorage.getItem(PREFIX + key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function remember(key, body) {
  if (!key) return;
  try {
    window.sessionStorage.setItem(PREFIX + key, JSON.stringify(body));
  } catch {
    // Quota or a private window: the next visit is simply not instant.
  }
}

export default function useDevLoad(fetcher, deps, refreshMs = 0, key = null) {
  const first = remembered(key);
  const [data, setData] = useState(first);
  const [state, setState] = useState(first ? 'ready' : 'loading');
  const [refreshing, setRefreshing] = useState(!!first);
  // When the server last confirmed what is on screen, whether by a fresh answer or
  // by a 304. The numbers' own age is `generated_at`; this is how recently that
  // age was verified.
  const [checkedAt, setCheckedAt] = useState(null);
  const alive = useRef(true);

  const load = useCallback(async () => {
    setRefreshing(true);
    const body = await fetcher();
    if (!alive.current) return;
    setRefreshing(false);
    if (body.notModified) {
      // The server confirmed what is on screen is current. Nothing to replace.
      setState('ready');
      setCheckedAt(Date.now());
      setData((d) => (d && d.__error ? { ...d, __error: undefined } : d));
      return;
    }
    if (body.forbidden) {
      setState('forbidden');
      return;
    }
    if (body.error) {
      // A failed refresh keeps the last answer on screen rather than replacing
      // it with an error the reader cannot act on; the error rides beside it.
      setState((s) => (s === 'ready' ? 'ready' : body.error));
      setData((d) => (d ? { ...d, __error: body.error } : d));
      return;
    }
    setData(body);
    setState('ready');
    setCheckedAt(Date.now());
    remember(key, body);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    alive.current = true;
    load();
    let timer;
    if (refreshMs) timer = setInterval(load, refreshMs);
    return () => {
      alive.current = false;
      if (timer) clearInterval(timer);
    };
  }, [load, refreshMs]);

  return { data, state, refreshing, checkedAt, reload: load };
}

export function Gate({ state, children }) {
  if (state === 'forbidden') {
    return (
      <div className="dev-empty">
        This page is for the archive&rsquo;s owner. Your account is not on that list.
      </div>
    );
  }
  if (state === 'loading') return <div className="dev-empty">Reading the archive&hellip;</div>;
  if (state !== 'ready') return <div className="dev-empty">{state}</div>;
  return children;
}

// The line under every title: how old the numbers are, when that was last
// confirmed, and whether the last check failed. One component so the four views
// cannot drift into four wordings — and so no view can show old numbers as fresh.
export function Stamp({ data, refreshing, checkedAt, every }) {
  if (!data) return null;
  const parts = [];
  if (data.generated_at) parts.push(`numbers from ${ago(data.generated_at)}`);
  if (refreshing) parts.push('checking…');
  else if (checkedAt) parts.push(`confirmed ${ago(new Date(checkedAt).toISOString())}`);
  if (every) parts.push(every);
  return (
    <div className={data.__error ? 'dev-stamp dev-stamp-failed' : 'dev-stamp'}>
      {parts.join(' · ')}
      {data.__error ? ` · last check failed: ${data.__error}` : ''}
    </div>
  );
}
