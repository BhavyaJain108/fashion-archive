// Where the reader was last, so that opening the app on a bare "/" puts them
// back rather than on the front of the archive.
//
// Two rules decide everything here, and both are about the URL winning:
//
//   1. Only a bare "/" — no path, no query string — is a blank enough
//      arrival to fill in. A URL that names a show is obviously a
//      destination, and so is one that carries only filters: "/?city=Paris
//      &year=2024" is somebody's bookmark of a view, and reopening last
//      night's show over it would throw away the thing they clicked.
//
//   2. Nothing but a route is ever stored. A route is where you were; a
//      collection row, a list of looks, or a cursor is what you had loaded,
//      and a stale copy of that is worse than no restore at all — it would
//      put last week's version of a show on screen and call it live.
//
// The stored value is the URL string rather than the parsed route object,
// for the same reason parseRoute exists at all: a URL is the one format this
// app already has to tolerate anything in. A route object written by an
// older release would want a migration every time its shape changed, and a
// half-written one would be an object with the right keys and wrong values.
// A path and a query string go back through parseRoute, which already drops
// what it does not recognise and opens the archive when it recognises
// nothing.

import { parseRoute, buildRoute } from './routes';

// The same 'fa:' namespace usePersistentState writes under, so everything
// this origin holds for the app sits beneath one prefix and can never
// collide with another app served from the same host.
export const SESSION_KEY = 'fa:lastRoute';

// Is this arrival blank enough to fill in? Exactly "/" with nothing behind
// it. A lone "?" carries nothing, so it counts as nothing; anything else in
// the query string is a deliberate destination and is left alone.
export function shouldRestore(pathname, search) {
  const path = pathname || '/';
  const query = (search || '').replace(/^\?/, '');
  return path === '/' && query === '';
}

// Store where we are. Called on every real navigation, so it is on the hot
// path of Back and Forward as well as of clicking a show — which is why it
// does nothing but one setItem and swallows everything.
//
// Every storage call is wrapped for the same reasons usePersistentState
// wraps its own: localStorage throws on setItem in Safari's private mode
// and when the origin's quota is full. A preference that will not persist
// is not worth a broken page.
export function rememberSession(route) {
  try {
    window.localStorage.setItem(SESSION_KEY, JSON.stringify(buildRoute(route)));
  } catch (e) {
    // Storage is unavailable, blocked, or full. There is nothing to fall
    // back to and nothing to tell the reader: the next visit simply opens
    // on the archive.
  }
}

// The stored route, or null when there is nothing usable.
//
// "Usable" is deliberately narrow, because this value was written by some
// earlier release of this app and read by this one. A corrupt value (a
// half-written string from a release that stored something else here), a
// value of the wrong type, or a localStorage that throws on read all return
// null and the caller opens the archive — the same answer an unrecognised
// URL gets.
export function restoreSession() {
  let raw;
  try {
    raw = window.localStorage.getItem(SESSION_KEY);
  } catch (e) {
    // Storage itself is unavailable — Safari private mode, or a browser
    // configured to block site data.
    return null;
  }
  if (raw === null || raw === undefined) return null;

  let url;
  try {
    url = JSON.parse(raw);
  } catch (e) {
    // Not JSON at all. An old release that wrote a bare string here, or a
    // write that was cut off halfway.
    return null;
  }

  // A number, an object, a null, or a string that is not a path: none of
  // these is a URL this app ever wrote, and parseRoute would quietly turn
  // the lot of them into the archive route, which is indistinguishable from
  // having restored something. Refusing here keeps "nothing stored" and
  // "something unreadable stored" the same answer.
  if (typeof url !== 'string' || !url.startsWith('/')) return null;

  const q = url.indexOf('?');
  const pathname = q === -1 ? url : url.slice(0, q);
  const search = q === -1 ? '' : url.slice(q);
  return parseRoute(pathname, search);
}
