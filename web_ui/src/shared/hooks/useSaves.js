import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FashionArchiveAPI } from '../api';
import { FILTER_KEYS } from '../../app/routes';

// What this user has kept, of any of the three kinds, and the one way to
// change it.
//
//   useSaves() -> { isSaved(target), toggle(target), saves, loading, error }
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

// Loaded once and held as a set of keys, because the question is asked of
// every thumbnail on screen — a request per look would be hundreds of requests
// to draw a strip. Saves are per user by construction: the endpoint reads the
// session, so there is no user id to pass and no way to see anyone else's.
export function useSaves() {
  const [saves, setSaves] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const alive = useRef(true);

  // The rows, readable synchronously. A write reads what is saved, flips it,
  // and a write that runs later in the same tick must read that flip —
  // `saves` does not land until the next render, so on its own it would hand
  // the second write the state the first one started from. Everything that
  // changes the list goes through `applySaves`, so the ref and the state are
  // set in the same statement and there is no path that moves one only.
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

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const load = useCallback(async () => {
    try {
      const rows = await FashionArchiveAPI.getFavourites();
      if (!alive.current) return;
      applySaves(rows || []);
    } catch (err) {
      console.error('Could not load saves:', err);
      if (alive.current) setError(err);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [applySaves]);

  useEffect(() => { load(); }, [load]);

  const savedKeys = useMemo(() => keySetOf(saves), [saves]);

  const isSaved = useCallback((target) => {
    const key = keyOf(target);
    return !!key && savedKeys.has(key);
  }, [savedKeys]);

  // One flip undone, on the list as it stands NOW rather than by putting a
  // remembered copy back. Writes for different stars run at the same time, so
  // a snapshot taken before this one started may be missing another star's
  // write that has since landed — restoring it would quietly un-save that one.
  // The row goes back where it was, not on the end, so a rollback leaves the
  // list in the order the server sent it.
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

    const previous = savesRef.current;
    const added = !keySetOf(previous).has(key);

    // Move the marker first. `previous` is the exact list it moved from, and
    // the rollback below undoes this one flip against it.
    applySaves(added
      ? [...previous, rowOfTarget(target)]
      : previous.filter(row => keyOf(targetOfRow(row)) !== key));

    // A press on a star whose write is still out is neither sent alongside it
    // nor dropped: it is held, one deep, and run when that write lands. One
    // deep because three presses are two states and the middle one is not a
    // state the reader ever asked to end up in — what is held is always the
    // last thing they clicked.
    const job = { target, added, previous };
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
          const back = undoFlip(savesRef.current, key, next.added, next.previous);
          savesRef.current = back;
          if (alive.current) setSaves(back);
          break;
        }
        next = queued.current.get(key) || null;
        queued.current.delete(key);
      }
    } finally {
      inFlight.current.delete(key);
    }
  }, [applySaves, write, undoFlip]);

  return { isSaved, toggle, saves, loading, error, reload: load };
}

export default useSaves;
