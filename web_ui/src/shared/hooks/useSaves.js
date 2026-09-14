import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FashionArchiveAPI } from '../api';
import { FILTER_KEYS } from '../../app/routes';

// What this user has kept, of any of the three kinds, and the one way to
// change it.
//
//   useSaves({ withRows }) -> { isSaved(target), setSaved, toggle(target),
//                   onUnsaved,
//                   saves, total, hasMore, loadRows, loadMore, loadingMore,
//                   loading, error, reload }
//
// TWO readings of the same table, because the two questions have different
// shapes and only one of them can be paged:
//
//   the keys   every save this user has, as its identity and nothing else.
//              Complete, always, and the only thing `isSaved` reads.
//   the rows   the display half — designer, season, image path, date — and
//              the half there can be thousands of. Paged.
//
// Splitting them is the whole of the paging change. The list used to be one
// unbounded fetch of full rows on every archive-page mount, and the stars were
// keyed off exactly those rows — so capping it would have been a dark star over
// a look the reader had saved, and pressing that star writes a SECOND save of a
// row the server already holds. Paging it would have been the same bug with a
// scrollbar. The fix is not to page the thing the star reads: a key is five
// columns, the rows are twenty, and the star never draws any of the other
// fifteen. So the keys come whole and cheap, and the rows come a page at a time.
//
// A target names one saved thing and nothing else:
//
//   { kind: 'look', season: {...}, collection: {...}, look: { number, total },
//     imagePath }
//   { kind: 'show', season: {...}, collection: {...}, imagePath }
//   { kind: 'view', filters: {...}, name }
//
// The season/collection/look nesting is the shape the write API takes AND the
// shape GET /api/favourites hands back, so one key function answers for a row
// the server sent and for a target a component built. Two key functions —
// one for what is on screen and one for what came back — is how a star ends up
// lit for a row nobody saved.
//
// Everything a caller sees is a function of `saves`, the rows themselves.
// There is no second "which keys are lit" state to drift out of step with it,
// which is what makes rollback a matter of putting one array back.

// ---------------------------------------------------------------- keys ---
//
// One key per kind, pure and exported, because the whole hook is these three
// functions plus a list.
//
// JSON.stringify of an array rather than a joined string: a collection url may
// contain the separator, and ['show', 'a|b', 'c'] and ['show', 'a', 'b|c'] are
// two different saved shows that a joined key cannot tell apart.

// A row from GET /api/favourites now also carries `collection.id` — firstVIEW's
// own id for the show, derived server-side from collection_url and kept equal to
// it by a CHECK constraint. It is the identity the rest of this app already uses
// (showId, sameShow, browseCatalog) and the one the two phase-3 bugs would not
// have had: both were two spellings of one URL.
//
// It is deliberately NOT in any key below. Keys here must be the server's unique
// indexes restated, and those are still the URL ones; keying the client on the id
// while the server keys on the URL would light stars for rows the delete cannot
// find. The id rides through `targetOfRow` and `rowOfTarget` untouched so it is
// there when the key does move, which is its own change with its own migration.

const text = (value) => (value === null || value === undefined ? '' : String(value));

// A look is season + collection + number — the server's
// (season_url, collection_url, look_number) unique index, restated.
export function lookKey(target) {
  const collectionUrl = text(target.collection && target.collection.url);
  const number = (target.look || {}).number;
  // A row with no collection or no number is not a look this key can name.
  // Before this guard the misread of the list response — flat column names
  // against a nested payload — keyed every row as "undefined|undefined" and
  // lit nothing after a reload.
  if (!collectionUrl || number === null || number === undefined) return null;
  return JSON.stringify([
    'look',
    text(target.season && target.season.url),
    collectionUrl,
    text(number),
  ]);
}

// A show is season + collection, with no number. Not a prefix of the look key
// and not compared as one: `isSaved` is an exact lookup in a Set, so a saved
// show lights the show star and no look star, and a saved look lights one look
// and not the show.
export function showKey(target) {
  const collectionUrl = text(target.collection && target.collection.url);
  if (!collectionUrl) return null;
  return JSON.stringify([
    'show',
    text(target.season && target.season.url),
    collectionUrl,
  ]);
}

// A view IS its filters, so its key is the filters made canonical.
//
// The server's identity for a saved view is md5(view_filters::text) over
// Postgres's jsonb rendering, and `normalise_filters` in
// backend/userdata/favourites.py decides what goes in: the seven known keys,
// values trimmed, empty values dropped, numbers as their text, everything else
// dropped. The same rule is applied here, so two filter objects collide on the
// client exactly when they collide on the server. The two strings need not
// match — jsonb orders keys by length then bytes and this orders them
// lexicographically — only the equivalence classes must, and they do, because
// both are a canonical rendering of the same normalised dictionary.
export function canonicalFilters(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const out = {};
  for (const key of Object.keys(raw).sort()) {
    if (!FILTER_KEYS.has(key)) continue;          // unknown keys dropped
    const value = raw[key];
    let asText;
    if (typeof value === 'boolean') continue;     // a filter is never true
    else if (typeof value === 'number') asText = String(value);
    else if (typeof value === 'string') asText = value.trim();
    else continue;                                // a list or object is
    if (asText) out[key] = asText;                // somebody else's payload
  }
  return out;
}

export function viewKey(target) {
  // Sorted on the way in, so stringify's insertion order is the sorted order.
  return JSON.stringify(['view', canonicalFilters(target.filters)]);
}

const KEYS = { look: lookKey, show: showKey, view: viewKey };

// The key for a target of any kind, or null if it names nothing.
export function keyOf(target) {
  if (!target) return null;
  const key = KEYS[target.kind || 'look'];
  return key ? key(target) : null;
}

// One target as the row the list would have held, so an optimistic marker and
// a row the server sent key identically. Round-tripping is the point:
// keyOf(targetOfRow(rowOfTarget(t))) is keyOf(t) for every kind.
export function rowOfTarget(target) {
  const kind = (target || {}).kind || 'look';
  return {
    kind,
    season: target.season || {},
    // Whole, so a `collection.id` the caller had is on the optimistic row too
    // and the row does not change shape when the server's copy replaces it.
    collection: target.collection || {},
    look: target.look || {},
    view: { name: target.name || '', filters: canonicalFilters(target.filters) },
    image_path: target.imagePath || '',
  };
}

// One row of GET /api/favourites as a target. The list nests these —
// collection.url, look.number, view.filters — and a row saved before kinds
// existed carries no `kind` at all, which the server also reads as a look.
//
// A KEY row from GET /api/favourites/keys reads through here unchanged: it is
// this same nesting with the display fields left out, and nothing below
// touches a display field. That is deliberate and it is the reason the key
// endpoint answers in this shape rather than a flat one — one key function for
// what the server sent, whichever of the two it sent, because two key
// functions is how a star ends up lit for a row nobody saved.
export function targetOfRow(row) {
  if (!row) return null;
  const kind = row.kind || 'look';
  if (kind === 'view') return { kind, filters: (row.view || {}).filters };
  return {
    kind,
    season: row.season,
    collection: row.collection,
    look: row.look,
  };
}

// Every key a list of rows names. The lit set on screen and the "was this
// saved" a write starts from are both this function, so the two readings
// cannot disagree.
export function keySetOf(rows) {
  const keys = new Set();
  for (const row of rows || []) {
    const key = keyOf(targetOfRow(row));
    if (key) keys.add(key);
  }
  return keys;
}

// Whether a write the server answered actually happened.
//
// A resolved promise is not a completed write. The favourites endpoints answer
// a change they did not make with HTTP 200 and {"success": false} — so
// `callPython` resolves, and awaiting it and returning true meant a delete
// that matched nothing was indistinguishable from one that removed a row. The
// star went dark, the row stayed in the database, and the next load put it
// back. LibraryPage.js has always read `result.success` on these same
// endpoints; this hook did not, and that difference is what made the recents
// key split silent instead of noisy.
//
// The two directions do not mean the same thing, because the server's two
// refusals do not:
//
//   delete -> "Not found in favourites"  the row is still there under some
//                                        other key; the press did not happen
//   add    -> "Already in favourites"    the row is there, which is exactly
//                                        what the press asked for
//
// So a refused delete is a failure and is rolled back, and a refused add is
// not: un-starring it would leave a dark star over a saved row, which is the
// same bug pointing the other way. An answer with no `success` field at all is
// taken at its word — not every endpoint sends one, and inventing a failure
// out of its absence would break every write that has ever worked.
export function wrote(answer, added) {
  if (!answer || typeof answer !== 'object') return true;
  if (answer.success !== false) return true;
  return Boolean(added);
}

// ---------------------------------------------------------------- hook ---

// How many rows one page of the library is. Not how many keys — there is no
// such number, the keys come whole.
export const PAGE_SIZE = 200;

// The keys are loaded once, whole, and held as a Set, because the question is
// asked of every thumbnail on screen — a request per look would be hundreds of
// requests to draw a strip. The rows are loaded a page at a time, because there
// is no ceiling on how many a reader has and the archive page used to fetch all
// of them to draw none of them.
//
// Saves are per user by construction: both endpoints read the session, so there
// is no user id to pass and no way to see anyone else's.
//
// The rows are OPT-IN and the keys are not, which is the other half of the
// split and was missing from it. Only a caller that draws the shelf wants two
// hundred rows; the archive page draws none of them and reads nothing but
// `isSaved`, `setSaved` and `toggle`, each of which is a function of the keys
// alone. Fetching both on every mount made that page cost two requests where
// it had cost one and throw away two hundred rows instead of all of them —
// the same bug the split was written to end, halved. Pass `withRows` (or call
// `loadRows()` later) and the shelf half loads; leave it off and nothing asks
// for it.
export function useSaves({ withRows = false } = {}) {
  // ── What is saved ──────────────────────────────────────────────────────
  //
  // The identity of every save, complete. This is the list `isSaved` reads and
  // the list every optimistic flip moves. It is NOT the paged one, and that
  // separation is the whole point: a star must be right about a save whose row
  // has not been fetched.
  const [keys, setKeys] = useState([]);

  // ── What is on the shelf ───────────────────────────────────────────────
  //
  // The rows, a page at a time, newest first. `cursor` is the server's opaque
  // bookmark for the last row delivered — passed back untouched, never parsed
  // and never built here.
  const [saves, setSaves] = useState([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const cursor = useRef(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const alive = useRef(true);

  // Whether the keys have ever landed. Not "whether loading has finished" —
  // a load that failed has finished too, and it is the one that matters.
  //
  // A ref because `toggle` reads it synchronously, in the same tick as the
  // press, before any state a failed load set could have rendered.
  //
  // Everything a star does is a function of the key set, and an empty key set
  // is indistinguishable from a reader who has saved nothing: every star reads
  // dark. Press one and the add is answered "Already in favourites", which is
  // deliberately not rolled back; press it again and the marker — now lit by
  // this hook's own optimism — sends a DELETE for a row the reader never asked
  // to lose. So until this is true, `toggle` writes nothing at all.
  const keysLoaded = useRef(false);

  // Both lists, readable synchronously. A write reads what is saved, flips it,
  // and a write that runs later in the same tick must read that flip — state
  // does not land until the next render, so on its own it would hand the second
  // write the state the first one started from. Everything that changes either
  // list goes through these, so the ref and the state are set in the same
  // statement and there is no path that moves one only.
  const keysRef = useRef(keys);
  const applyKeys = useCallback((rows) => {
    keysRef.current = rows;
    setKeys(rows);
  }, []);

  const savesRef = useRef(saves);
  const applySaves = useCallback((rows) => {
    savesRef.current = rows;
    setSaves(rows);
  }, []);

  // One write at a time PER SAVED THING, rather than one write at a time
  // overall. The star is now in four places at once, and a single global flag
  // made keeping a show silently drop the look you starred a moment earlier —
  // different rows, different keys, no reason to queue behind each other.
  //
  // What the flag was protecting is real, but it is per key: the optimistic
  // marker means a second press on the SAME star reads the marker the first
  // one moved and would send the opposite write against a row the server has
  // not heard about yet. So a repeat press on a key already in flight is
  // neither sent nor dropped — it is held here, one deep, and run when the
  // write in front of it lands. The last thing the reader clicked is always
  // the thing that gets written.
  const inFlight = useRef(new Set());
  const queued = useRef(new Map());

  // ── who else needs to know a save is gone ──────────────────────────────
  //
  // Unsaving something does not only empty a star. `album_items` is ON DELETE
  // CASCADE on the favourite, so the server takes the row out of every album
  // it was in inside the same statement, and the client is never asked. An
  // album shelf drawn from `item_count` is therefore stale the instant a
  // delete lands, and it stays stale: the next add to that album counts up
  // from the wrong number, so the shelf says two over an album holding one
  // and goes on saying it until the page is remounted.
  //
  // `LibraryPage` re-reads the shelf after its own delete for exactly this
  // reason. The archive page has the same delete, on the star, and had no way
  // to hear about it — so this is that way, and it is deliberately a
  // notification rather than a handle on the list: the listener is told a save
  // went, and goes and asks the server what it holds now. Handing it the list
  // would make it a second owner of the thing `isSaved` reads, which is the
  // one arrangement this hook exists to prevent.
  const listeners = useRef(new Set());

  // Subscribe; the returned function unsubscribes. Stable, so an effect that
  // subscribes does not tear down and re-subscribe on every render.
  const onUnsaved = useCallback((listener) => {
    if (typeof listener !== 'function') return () => {};
    listeners.current.add(listener);
    return () => { listeners.current.delete(listener); };
  }, []);

  // Announced for a delete the SERVER made, and for nothing else. Not for a
  // refused one — that is rolled back here and nothing cascaded — and not for
  // `setSaved`, which moves a marker and sends no request at all.
  //
  // One listener throwing must not stop the next from being told, and must not
  // turn a completed write into a failed one.
  const announceUnsaved = useCallback((key, target) => {
    listeners.current.forEach((listener) => {
      try {
        listener(key, target);
      } catch (err) {
        console.error('A listener for an unsaved row threw:', err);
      }
    });
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  // The two loads, in one call, because a star lit off the keys over a shelf
  // drawn off the rows must not be able to show a half-loaded library.
  //
  // The keys request is the one that matters. If it fails there is no key set,
  // every star reads dark, and pressing one writes a second save of a row the
  // server already holds — so it is reported as an error rather than swallowed
  // into an empty list, and `saves` is left alone.
  // Whether anybody has asked for the rows: the option at mount, or a
  // `loadRows()` since. A ref, so a reload after that first page keeps
  // fetching them without the caller having to say so twice.
  const rowsWanted = useRef(withRows);
  if (withRows) rowsWanted.current = true;

  // One page of rows, applied. Shared by the mount and by `loadRows`, so
  // there is one statement of what a first page does to this state.
  const takeFirstPage = useCallback((page) => {
    applySaves(page.favourites || []);
    setTotal(page.total || 0);
    setHasMore(Boolean(page.hasMore));
    cursor.current = page.nextCursor || null;
  }, [applySaves]);

  const load = useCallback(async () => {
    try {
      const [allKeys, page] = await Promise.all([
        FashionArchiveAPI.getFavouriteKeys(),
        rowsWanted.current
          ? FashionArchiveAPI.getFavouritesPage({ limit: PAGE_SIZE })
          : null,
      ]);
      if (!alive.current) return;
      keysLoaded.current = true;
      applyKeys(allKeys || []);
      if (page) takeFirstPage(page);
      setError(null);
    } catch (err) {
      console.error('Could not load saves:', err);
      if (alive.current) setError(err);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [applyKeys, takeFirstPage]);

  // The shelf half, asked for after the fact. From here on a reload fetches
  // it too — a caller that has drawn the rows once is drawing them still.
  const loadRows = useCallback(async () => {
    rowsWanted.current = true;
    try {
      const page = await FashionArchiveAPI.getFavouritesPage({ limit: PAGE_SIZE });
      if (!alive.current) return;
      takeFirstPage(page);
      setError(null);
    } catch (err) {
      console.error('Could not load saves:', err);
      if (alive.current) setError(err);
    }
  }, [takeFirstPage]);

  useEffect(() => { load(); }, [load]);

  // The next page of ROWS. Never of keys — there is no next page of those, and
  // a caller cannot ask for one.
  //
  // Guarded on `cursor.current` rather than only on `hasMore`: `hasMore` is
  // state and lags a render behind, so two quick presses (or a scroll handler
  // firing twice) would both see it true. The cursor is a ref and is cleared
  // the moment a page is asked for.
  const loadMore = useCallback(async () => {
    const from = cursor.current;
    if (!from) return;
    cursor.current = null;
    setLoadingMore(true);
    try {
      const page = await FashionArchiveAPI.getFavouritesPage(
        { limit: PAGE_SIZE, cursor: from });
      if (!alive.current) return;
      // Appended to what is there NOW, not to a copy taken before the request
      // went out: a star pressed while this page was in flight has already put
      // its row on the front, and rebuilding from a snapshot would drop it.
      applySaves([...savesRef.current, ...(page.favourites || [])]);
      setTotal(page.total || 0);
      setHasMore(Boolean(page.hasMore));
      cursor.current = page.nextCursor || null;
      setError(null);
    } catch (err) {
      console.error('Could not load more saves:', err);
      if (alive.current) {
        setError(err);
        // Put the cursor back, so the control the reader pressed can be
        // pressed again rather than becoming the end of their library.
        cursor.current = from;
      }
    } finally {
      if (alive.current) setLoadingMore(false);
    }
  }, [applySaves]);

  const savedKeys = useMemo(() => keySetOf(keys), [keys]);

  const isSaved = useCallback((target) => {
    const key = keyOf(target);
    return !!key && savedKeys.has(key);
  }, [savedKeys]);

  // One flip, applied to both lists at once.
  //
  // The keys decide the star; the rows are the shelf. They move together or a
  // press lights a star over a shelf that does not show the thing — and the
  // rows move to the FRONT on an add, because the list is newest first and a
  // save made a moment ago is the newest thing in it.
  const flip = useCallback((target, key, added) => {
    const drop = (rows) => rows.filter(row => keyOf(targetOfRow(row)) !== key);
    applyKeys(added
      ? [...keysRef.current, rowOfTarget(target)]
      : drop(keysRef.current));
    applySaves(added
      ? [rowOfTarget(target), ...savesRef.current]
      : drop(savesRef.current));
  }, [applyKeys, applySaves]);

  // The marker moved, and NOTHING sent. The only write-less way into this
  // list, and it exists for exactly one caller.
  //
  // `useAlbums` adds something to an album that may not be saved yet, and the
  // server does the save and the filing in one transaction: by the time that
  // answer lands the favourite row exists, and there is no second request left
  // to make — only a star to light. Calling `toggle` for it would send a
  // second add of a row the server already has, and a `removeFavourite` on the
  // rollback would delete a favourite the failed transaction never created.
  //
  // This hook stays the one owner of the list a star reads. `useAlbums` does
  // not hold saves, it asks the owner to move one marker, which is why the
  // collaborator it takes is this pair and not the list.
  //
  // Idempotent on purpose, and it moves ONE key: asked for a state the list is
  // already in it does nothing, so an album add that lit a star cannot be
  // undone into putting out a star somebody else lit.
  const setSaved = useCallback((target, saved) => {
    const key = keyOf(target);
    if (!key) return;
    if (savedKeys.has(key) === Boolean(saved)) return;
    flip(target, key, Boolean(saved));
  }, [flip, savedKeys]);

  // One flip undone, on the list as it stands NOW rather than by putting a
  // remembered copy back. Writes for different stars run at the same time, so
  // a snapshot taken before this one started may be missing another star's
  // write that has since landed — restoring it would quietly un-save that one.
  // The row goes back where it was, not on the end, so a rollback leaves the
  // list in the order the server sent it.
  //
  // Generic over both lists: a key row and a full row are both keyed by
  // `keyOf(targetOfRow(...))`, which is the whole reason the key endpoint
  // answers in the row's own nesting.
  const undoFlip = useCallback((rows, key, added, previous) => {
    if (added) return rows.filter(row => keyOf(targetOfRow(row)) !== key);
    if (keySetOf(rows).has(key)) return rows;          // something put it back
    const at = previous.findIndex(row => keyOf(targetOfRow(row)) === key);
    if (at < 0) return rows;
    const back = [...rows];
    back.splice(Math.min(at, back.length), 0, previous[at]);
    return back;
  }, []);

  // The write itself, and nothing else: which endpoint, in which direction.
  // `added` is what the marker already says — the flip happened in `toggle`,
  // before this ran — so the two cannot disagree about the direction.
  //
  // Everything below comes off `t`, read once: the writes are positional and
  // two of a look's three arguments are urls, so a triple assembled out of
  // two shows names a row that exists, deletes it, and reports success.
  // Nothing here may reach for a season or a collection by any other name.
  const write = useCallback(async (target, added) => {
    const t = target;
    const kind = t.kind || 'look';
    try {
      let answer;
      if (kind === 'look') {
        if (added) {
          answer = await FashionArchiveAPI.addFavourite(
            t.season, t.collection, t.look, t.imagePath);
        } else {
          answer = await FashionArchiveAPI.removeFavourite(
            (t.season || {}).url || '', (t.collection || {}).url, (t.look || {}).number);
        }
      } else if (kind === 'show') {
        if (added) {
          answer = await FashionArchiveAPI.addShowFavourite(
            t.season, t.collection, t.imagePath);
        } else {
          answer = await FashionArchiveAPI.removeShowFavourite(
            (t.season || {}).url || '', (t.collection || {}).url);
        }
      } else if (added) {
        answer = await FashionArchiveAPI.addViewFavourite(
          canonicalFilters(t.filters), t.name || '');
      } else {
        // A view is sent as the filters this client keyed it on, not as they
        // arrived: saving through one rule and deleting through another is how
        // a view becomes undeletable.
        answer = await FashionArchiveAPI.removeViewFavourite(canonicalFilters(t.filters));
      }
      if (!wrote(answer, added)) {
        const err = new Error(
          (answer && answer.message) || 'The server did not make that change');
        console.error('Could not change favourite:', err);
        if (alive.current) setError(err);
        return false;
      }
      if (alive.current) setError(null);
      return true;
    } catch (err) {
      console.error('Could not change favourite:', err);
      if (alive.current) setError(err);
      return false;
    }
  }, []);

  // The one way in, and the only place that knows about ordering.
  //
  // Every press moves the marker straight away — keeping something should
  // feel instantaneous, and a press held behind a write in flight that did
  // NOT move it would leave the reader clicking a star that does not
  // respond. So the marker is the reader's intent, and the queue below is
  // only about making the server agree with it.
  //
  // The returned promise settles when this press and anything held behind it
  // has been written, so a caller that awaits a toggle has awaited the burst.
  const toggle = useCallback(async (target) => {
    const key = keyOf(target);
    if (!key) return;

    // A star whose state is unknown does not flip and does not write. See
    // `keysLoaded`: the second press of a dark star over a load that failed
    // is a delete, and it is the only press on this page that destroys
    // something. The reader is told why by whatever renders `error`.
    if (!keysLoaded.current) return;

    // Read off the KEYS, not off the page of rows. This is the trap the whole
    // split exists for: a look saved long enough ago that its row is on a page
    // nobody has fetched is still saved, and asking the visible rows would say
    // it was not — so the press would send an ADD, the server would answer
    // "Already in favourites", and the star would sit lit over a row that was
    // already there while the reader thinks they just saved it.
    const previousKeys = keysRef.current;
    const previousRows = savesRef.current;
    const added = !keySetOf(previousKeys).has(key);

    // Move the marker first, in both lists. The two `previous` above are the
    // exact lists it moved from, and the rollback below undoes this one flip
    // against them.
    flip(target, key, added);

    // A press on a star whose write is still out is neither sent alongside it
    // nor dropped: it is held, one deep, and run when that write lands. One
    // deep because three presses are two states and the middle one is not a
    // state the reader ever asked to end up in — what is held is always the
    // last thing they clicked.
    const job = { target, added, previousKeys, previousRows };
    if (inFlight.current.has(key)) {
      queued.current.set(key, job);
      return;
    }

    inFlight.current.add(key);
    try {
      let next = job;
      while (next) {
        // eslint-disable-next-line no-await-in-loop
        const ok = await write(next.target, next.added);
        if (!ok) {
          // The burst failed at this press. Put its flip back and drop
          // anything held behind it — it was queued against a state the
          // server never reached.
          queued.current.delete(key);
          applyKeys(undoFlip(keysRef.current, key, next.added, next.previousKeys));
          applySaves(undoFlip(savesRef.current, key, next.added, next.previousRows));
          break;
        }
        // The server has made this change. If it was a delete it has also
        // cascaded the row out of every album it was in, and whoever draws
        // those albums is now showing a count that was true a moment ago.
        if (!next.added) announceUnsaved(key, next.target);
        next = queued.current.get(key) || null;
        queued.current.delete(key);
      }
    } finally {
      inFlight.current.delete(key);
    }
  }, [applyKeys, applySaves, flip, write, undoFlip, announceUnsaved]);

  return {
    isSaved, setSaved, toggle, onUnsaved,
    saves, total, hasMore, loadRows, loadMore, loadingMore,
    loading, error, reload: load,
  };
}

export default useSaves;
