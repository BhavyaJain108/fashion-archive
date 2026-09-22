import { useCallback, useEffect, useState } from 'react';

// One loading shape for every machine-room view: a fetcher, an optional refresh
// interval, and the four states a read can be in. Pages render the state, never
// the promise.
export default function useDevLoad(fetcher, deps, refreshMs = 0) {
  const [data, setData] = useState(null);
  const [state, setState] = useState('loading');

  const load = useCallback(async () => {
    const body = await fetcher();
    if (body.forbidden) {
      setState('forbidden');
      return;
    }
    if (body.error) {
      setState(body.error);
      return;
    }
    setData(body);
    setState('ready');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    load();
    if (!refreshMs) return undefined;
    const timer = setInterval(load, refreshMs);
    return () => clearInterval(timer);
  }, [load, refreshMs]);

  return { data, state, reload: load };
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
