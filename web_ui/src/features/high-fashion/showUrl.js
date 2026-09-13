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
//   'ignore' — it is the show on screen. Not a navigation, so no history
//              entry, and no reason to throw away the look being read.
//   'open'   — a show the user chose. Load it and push.
//
// 'ignore' is the whole of the Back fix. A push of /hf/x/1 while standing on
// /hf/x/1/7 left an entry that differed from the URL shown, so Back could
// land on it and change nothing visible.
export function clickAction({ clicked, open, fromUrl = false }) {
  if (fromUrl) return 'adopt';
  if (sameShow(clicked, open)) return 'ignore';
  return 'open';
}

// ── Which effect may write the address bar ────────────────────────────────

// firstWrite: true until the page has had a reason to write a URL of its own.
//   It exists to stop the first no-selection render from overwriting the URL
//   the user arrived on.
// pending: the collection id a deep link is fetching, or null. While it is
//   set the URL is ahead of the state rather than behind it, and state → URL
//   must keep its hands off.
// look: the look number the URL asked for, held until it is reached, clamped,
//   or superseded by hand.
export const initialUrlSync = () => ({
  firstWrite: true,
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

// The URL moved on before the fetch came back. Nothing was resolved, so
// firstWrite is left alone — whichever deep link follows will retire it.
export function deepLinkAbandoned(state) {
  return { ...state, pending: null };
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
