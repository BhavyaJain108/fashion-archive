// The only file in the app that touches window.history.
//
// There is no router dependency here on purpose: the whole surface is three
// functions, and a library would bring a component tree, a context, and its
// own opinions about where state lives — none of which this app needs.
import { parseRoute, buildRoute } from './routes';

const subscribers = new Set();

export function getRoute() {
  return parseRoute(window.location.pathname, window.location.search);
}

const notify = () => {
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
  const current = window.location.pathname + window.location.search;

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
