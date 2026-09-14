// Everything about this page's relationship with the address bar that does not
// need React.
//
// Two of these live here rather than inside HighFashionPage for a reason
// beyond tidiness: the page runs two effects pointing in opposite directions
// — URL → state and state → URL — and the bookkeeping that decides which of
// them may write is three mutable flags read across several renders. Both
// bugs this file was extracted for were sequences, not lines: a deep link
// that resolved nothing used to swallow the user's next URL write, and
// re-clicking the show already open used to push a history entry Back could
// reach without changing the screen. A sequence is only testable if the
// decisions are functions of a value, so they are.

import { FILTER_KEYS, slugify } from '../../app/routes';

// Which filters exist is decided in exactly one place — FILTER_KEYS in
// routes.js — because that is the list the query string is read and written
// through. Spelling the set out again would be how an eighth filter gets
// added to the page and then quietly fails to survive a reload: the page
// would have it, the URL would drop it.
export const EMPTY_FILTERS = Array.from(FILTER_KEYS).reduce(
  (acc, key) => ({ ...acc, [key]: '' }), {});

// The readable half of a show URL. Never parsed back — see routes.js — so a
// row with an odd designer or no subtitle still produces something.
export const showSlug = (collection) => slugify(
  (collection || {}).designer || (collection || {}).designer_name,
  (collection || {}).subtitle);

// A show is only addressable if its id is firstVIEW's own bare integer.
// Anything else (a crawled row with no id at all) cannot be written into a
// URL that parseRoute would read back, so it is not written into one.
export const showId = (collection) => {
  const id = String((collection && collection.collection_id) ?? '');
  return /^\d+$/.test(id) ? id : null;
};

// Are these two rows the same show? By id when both have one, because the
// list refetches and hands back fresh objects for the same show; by
// collection url otherwise, which is the only other thing a crawled row
// carries. Two rows with neither are not assumed to match.
export function sameShow(a, b) {
  if (!a || !b) return false;
  const idA = showId(a);
  const idB = showId(b);
  if (idA && idB) return idA === idB;
  return Boolean(a.url) && a.url === b.url;
}

// What clicking a row means:
//
//   'adopt'  — the address bar already named this show, so open it but write
//              nothing: the user has already made this navigation.
//   'ignore' — it is the show on screen, or the show a deep link is already
//              fetching. Not a navigation, so no history entry, and no
//              reason to throw away the look being read.
//   'reload' — it is the show on screen, and the stream gave it no images.
//              Load it again, but replace: the user is retrying the entry
//              they are standing on, not going anywhere new.
//   'open'   — a show the user chose. Load it and push.
//
// 'ignore' is the whole of the Back fix. A push of /hf/x/1 while standing on
// /hf/x/1/7 left an entry that differed from the URL shown, so Back could
// land on it and change nothing visible. `pendingId` is the same fix one
// beat earlier: while /hf/x/1/12 is still being resolved nothing is open
// yet, so clicking that row read as a fresh navigation and pushed /hf/x/1
// over the URL already shown — the same unreachable entry, from the other
// direction.
//
// 'reload' is why 'ignore' is not the end of the story. When the stream
// produces nothing the viewer says "No images found", and re-clicking the
// highlighted row was the only retry the page ever had; a failure message
// beside a dead click reads as broken. A show still loading is not retried —
// the reader is waiting on it, not stuck.
export function clickAction({
  clicked,
  open,
  pendingId = null,
  hasImages = true,
  imagesLoading = false,
  fromUrl = false,
}) {
  if (fromUrl) return 'adopt';
  if (pendingId !== null && showId(clicked) === pendingId) return 'ignore';
  if (sameShow(clicked, open)) {
    return (!hasImages && !imagesLoading) ? 'reload' : 'ignore';
  }
  return 'open';
}

// ── Which effect may write the address bar ────────────────────────────────

// firstWrite: true until the page has had a reason to write a URL of its own.
//   It exists to stop the first no-selection render from overwriting the URL
//   the user arrived on.
// arrivedAt: that URL, as path+search, or null when the caller did not say.
//   Only ever compared for equality — see routeChanged.
// pending: the collection id a deep link is fetching, or null. While it is
//   set the URL is ahead of the state rather than behind it, and state → URL
//   must keep its hands off.
// look: the look number the URL asked for, held until it is reached, clamped,
//   or superseded by hand.
export const initialUrlSync = (arrivedAt = null) => ({
  firstWrite: true,
  arrivedAt,
  pending: null,
  look: null,
});

export function deepLinkStarted(state, { collectionId, imageNumber = null }) {
  return { ...state, pending: collectionId, look: imageNumber ?? null };
}

// The deep link has come back — with a row, or with nothing, or as an error.
// firstWrite is retired either way: it only ever protected the URL the user
// arrived on, and that URL has now been given every chance it is going to
// get. Leaving it standing is what made a filter change after a dead deep
// link do nothing at all.
export function deepLinkSettled(state, { found }) {
  return {
    ...state,
    firstWrite: false,
    pending: null,
    look: found ? state.look : null,
  };
}

// The URL moved on before the fetch came back. Nothing was resolved, so this
// says nothing about firstWrite; routeChanged is what retires it, because
// the URL moving on is the fact that matters and a deep link is only one of
// the ways it can move.
export function deepLinkAbandoned(state) {
  return { ...state, pending: null };
}

// The address bar is no longer showing the URL the page mounted on, so the
// first-write guard has done its whole job: it exists to stop the first
// no-selection render from overwriting the URL the user arrived on, and the
// user has now navigated away from that URL themselves.
//
// This is separate from deepLinkAbandoned rather than folded into it because
// abandonment is one route change among several — Back off a deep link
// before its row lands is the sequence that bit, but nothing here depends on
// a deep link having been in flight. deepLinkAbandoned used to assume
// another deep link would follow and retire the guard; when the user went
// Back to the archive instead, none did, and their next filter change wrote
// nothing at all.
//
// Returns the same object when there is nothing to retire, so a caller can
// assign it back on every route change without churning identity.
export function routeChanged(state, { path }) {
  if (!state.firstWrite) return state;
  if (state.arrivedAt === null || path === state.arrivedAt) return state;
  return { ...state, firstWrite: false };
}

// The reader chose a look themselves. Whatever the link was still waiting to
// reach is now beside the point; without this they get yanked to the URL's
// look the moment that image lands.
export function manualLook(state) {
  return state.look === null ? state : { ...state, look: null };
}

// state → URL. Returns the next bookkeeping value and what to write:
//   'none'    — write nothing.
//   'archive' — the list, carrying its filters.
//   'show'    — the open show, at imageNumber (null when no look is known).
export function urlWrite(state, { hasSelection, imagesLength = 0, currentIndex = 0 }) {
  if (state.pending) return { state, target: 'none', imageNumber: null };

  if (!hasSelection) {
    if (state.firstWrite) {
      return { state: { ...state, firstWrite: false }, target: 'none', imageNumber: null };
    }
    return { state, target: 'archive', imageNumber: null };
  }

  // A look a link asked for outranks the look on screen until it is settled,
  // so /hf/x/1/12 does not fall back to /hf/x/1 while the stream loads — a
  // stream that then fails would have lost the shared look for good.
  const imageNumber = state.look !== null
    ? state.look
    : (imagesLength ? currentIndex + 1 : null);

  return { state: { ...state, firstWrite: false }, target: 'show', imageNumber };
}

// The look a deep link named, applied once it has actually arrived. Images
// stream in one at a time, so imagesLength grows: settling on the first
// render would put a link to look 12 on look 1. expectedLookCount comes from
// the stream's meta event and is how a link to look 200 of a 40-look show
// knows to stop at 40 rather than wait forever.
export function lookToApply(state, { imagesLength, expectedLookCount }) {
  const wanted = state.look;
  if (!wanted || !imagesLength) return { state, index: null };
  const complete = expectedLookCount > 0 && imagesLength >= expectedLookCount;
  if (imagesLength < wanted && !complete) return { state, index: null };
  return {
    state: { ...state, look: null },
    index: Math.min(wanted, imagesLength) - 1,
  };
}

// ── URL → state, for the filters ──────────────────────────────────────────

// What the applied filters should become for a URL that says `routeFilters`,
// or null when they already say it.
//
// The bug this exists for is a sequence, which is why it is a function of a
// value rather than a line in an effect. `route.filters` used to be read
// once, in the page's initial state, and never again:
//
//   filters F1 → open show A, which pushes ?F1
//               → change to F2, which replaces, so no new entry
//               → open show B, which pushes ?F2
//               → Back
//
// Back restores the entry carrying ?F1 and reopens show A. Nothing read the
// F1 out of it, so the applied filters were still F2 — and the state → URL
// effect, re-running because the selection had changed, wrote F2 straight
// back over the entry Back had just restored. The filters were discarded and
// the history entry was rewritten in place, so pressing Back again could not
// get them back either.
//
// Returning null rather than an equal object is the whole of the guard that
// keeps this from fighting state → URL. Every URL that effect writes carries
// the applied filters, so the route change it causes arrives here saying
// exactly what is already applied, and this answers "nothing to do". Only a
// URL the page did not write — Back, Forward, a shared link, a restored
// session — can differ, and that is the only case where the URL should win.
// (The caller must not run this on a filter change of its own: the route has
// not caught up yet at that point, and this would read the stale query
// string as a disagreement and undo the reader's change.)
//
// The answer is a whole filter set, not a patch. A filter dropped from the
// query string is a filter that was cleared, and patching would leave it
// applied — Back out of "Paris, 2024" into "2024" has to lose Paris.
export function filtersToApply(applied, routeFilters) {
  const next = { ...EMPTY_FILTERS };
  for (const key of Object.keys(routeFilters || {})) {
    // Only the seven. parseRoute already drops everything else, but this is
    // also reached from a stored session, and the query string it came from
    // is shared with the auth parameters.
    if (key in next) next[key] = routeFilters[key] || '';
  }

  const unchanged = Object.keys(next).every(
    (key) => ((applied || {})[key] || '') === next[key]);
  return unchanged ? null : next;
}
