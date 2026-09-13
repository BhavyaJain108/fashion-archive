// The only file in the app that touches window.history.
//
// There is no router dependency here on purpose: the whole surface is three
// functions, and a library would bring a component tree, a context, and its
// own opinions about where state lives — none of which this app needs.
import { parseRoute, buildRoute } from './routes';

const subscribers = new Set();

// getRoute() must return the SAME object reference across calls that see no
// URL change: useRoute() hands getRoute straight to React's
// useSyncExternalStore, which compares snapshots with Object.is and will
// re-render forever if handed a fresh object every time. cachedHref records
// the URL the cached route was parsed from, so a change made outside
// navigate() (the browser's own back/forward, or code that calls
// history.replaceState directly) is still caught — getRoute() checks the
// live href on every call rather than trusting a stale cache.
let cachedHref = null;
let cachedRoute = null;

export function getRoute() {
  if (cachedRoute === null || window.location.href !== cachedHref) {
    cachedHref = window.location.href;
    cachedRoute = parseRoute(window.location.pathname, window.location.search);
  }
  return cachedRoute;
}

const notify = () => {
  // The address bar has already changed by this point, so the cache is
  // invalidated first — otherwise subscribers (and any getRoute() call a
  // subscriber triggers, e.g. a React re-render) would see the stale route.
  cachedRoute = null;
  const route = getRoute();
  for (const fn of subscribers) {
    try {
      fn(route);
    } catch (error) {
      // One bad subscriber must not strand the rest of the app on the wrong
      // URL — the address bar has already changed by this point.
      console.error('Route subscriber failed:', error);
    }
  }
};

export function navigate(route, { replace = false } = {}) {
  const url = buildRoute(route);
  // Compare canonical form to canonical form. buildRoute() always emits
  // filter keys in sorted order, but the address bar can hold them in any
  // order — a shared link, a hand-edited URL, or an earlier replaceState —
  // so comparing against the raw pathname+search would treat a
  // semantically identical route as a change and push a spurious history
  // entry. Routing the current URL through parseRoute/buildRoute canonicalizes
  // it the same way; this round-trip is exact because parseRoute keeps the
  // slug it saw, so buildRoute(getRoute()) reproduces the current URL rather
  // than replacing the readable segment with the placeholder.
  const current = buildRoute(getRoute());

  // An effect that navigates on every render would otherwise push an entry
  // per render and bury the user's actual history.
  if (url === current) return;

  if (replace) window.history.replaceState({}, '', url);
  else window.history.pushState({}, '', url);

  notify();
}

export function subscribe(fn) {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}

// Back and forward. Registered once, at module load, for the life of the page.
window.addEventListener('popstate', notify);
