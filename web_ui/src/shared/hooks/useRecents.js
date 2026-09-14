import { useCallback, useEffect, useState } from 'react';
import { FashionArchiveAPI } from '../api';

// Shows this user has opened, newest first.
//
//   useRecents() -> { recents, loading, error, reload }
//
// A row of GET /api/recents is the show as the server last saw it opened:
//
//   { collection_id, designer, season, year, gender, url,
//     thumbnail_url, look_count, viewed_at }
//
// `url` and `collection_id` are the two fields that matter beyond display —
// together they are enough for the page to open the show through the same
// handler a row in the show list goes through. Nothing here opens anything;
// this hook only holds the list.
//
// Recording is the server's job and already happens when a show is opened,
// so there is no write side to this hook. What there is instead is `reload`,
// because the list the server holds moves every time the reader opens a
// show and nothing tells this client when it did.
//
// The tolerances are the ones useSaves and useCollectionImages keep:
//
//   * an in-flight load never blanks what is already on screen — `recents`
//     is only ever replaced by a list that arrived, so a failed refresh
//     leaves the last good list where it was;
//   * a response that lands after unmount, or after a NEWER request was
//     made, is dropped rather than written. Both are the same flag: the
//     request lives in an effect, so React tears it down on unmount AND on
//     every reload, and `cancelled` is set in that teardown. Two reloads in
//     quick succession therefore leave the newer one's answer standing
//     rather than whichever fetch happened to finish last.
//
// One caveat worth stating plainly: FashionArchiveAPI.getRecents() catches
// its own failures and resolves with [], so `error` is reachable only if
// something throws outside it. It exists because a caller should not have to
// know that, and because the day getRecents rejects is not the day to
// discover this hook had nowhere to put the failure.
export function useRecents() {
  const [recents, setRecents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Bumped by reload(). The list is asked for again on the same terms — there
  // are no terms — so a counter is the whole mechanism, exactly as in
  // useCollectionImages.
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    // Set by this effect's own teardown, which React runs on unmount and
    // before every re-run. One flag, both meanings: this request is no
    // longer the one anybody is waiting for.
    let cancelled = false;

    setLoading(true);
    FashionArchiveAPI.getRecents()
      .then((rows) => {
        if (cancelled) return;
        setRecents(rows || []);
        setError(null);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error('Could not load recents:', err);
        // `recents` deliberately survives: the previous list is still a way
        // back to a show, and an empty drawer is a worse answer than a
        // slightly stale one.
        setError(err);
        setLoading(false);
      });

    return () => { cancelled = true; };
  }, [nonce]);

  const reload = useCallback(() => { setNonce((n) => n + 1); }, []);

  return { recents, loading, error, reload };
}

export default useRecents;
