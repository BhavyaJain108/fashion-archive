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

// ---------------------------------------------------------------- hook ---

// Loaded once and held as a set of keys, because the question is asked of
// every thumbnail on screen — a request per look would be hundreds of requests
// to draw a strip. Saves are per user by construction: the endpoint reads the
// session, so there is no user id to pass and no way to see anyone else's.
export function useSaves() {
  const [saves, setSaves] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const load = useCallback(async () => {
    try {
      const rows = await FashionArchiveAPI.getFavourites();
      if (!alive.current) return;
      setSaves(rows || []);
    } catch (err) {
      console.error('Could not load saves:', err);
      if (alive.current) setError(err);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const savedKeys = useMemo(() => {
    const keys = new Set();
    for (const row of saves) {
      const key = keyOf(targetOfRow(row));
      if (key) keys.add(key);
    }
    return keys;
  }, [saves]);

  const isSaved = useCallback((target) => {
    const key = keyOf(target);
    return !!key && savedKeys.has(key);
  }, [savedKeys]);

  const toggle = useCallback(async (target) => {
    // `t` is read once, here, and every argument below comes off it. The
    // writes are positional and two of a look's three arguments are urls: a
    // triple assembled out of two shows names a row that exists, deletes it,
    // and reports success. Nothing below may reach for a season or a
    // collection by any other name.
    const t = target;
    const key = keyOf(t);
    if (!key || busy) return;

    const kind = t.kind || 'look';
    const had = savedKeys.has(key);

    // Move the marker first: keeping something should feel instantaneous, and
    // the whole list is put back below if the write turns out not to have
    // worked. `previous` is the exact array that was on screen — restoring it
    // restores every kind's marker, not just the one that was clicked.
    const previous = saves;
    setSaves(had
      ? previous.filter(row => keyOf(targetOfRow(row)) !== key)
      : [...previous, rowOfTarget(t)]);
    setBusy(true);

    try {
      if (kind === 'look') {
        if (had) {
          await FashionArchiveAPI.removeFavourite(
            (t.season || {}).url || '', (t.collection || {}).url, (t.look || {}).number);
        } else {
          await FashionArchiveAPI.addFavourite(
            t.season, t.collection, t.look, t.imagePath);
        }
      } else if (kind === 'show') {
        if (had) {
          await FashionArchiveAPI.removeShowFavourite(
            (t.season || {}).url || '', (t.collection || {}).url);
        } else {
          await FashionArchiveAPI.addShowFavourite(
            t.season, t.collection, t.imagePath);
        }
      } else if (had) {
        // A view is sent as the filters this client keyed it on, not as they
        // arrived: saving through one rule and deleting through another is how
        // a view becomes undeletable.
        await FashionArchiveAPI.removeViewFavourite(canonicalFilters(t.filters));
      } else {
        await FashionArchiveAPI.addViewFavourite(canonicalFilters(t.filters), t.name || '');
      }
      if (alive.current) setError(null);
    } catch (err) {
      console.error('Could not change favourite:', err);
      if (alive.current) {
        setSaves(previous);   // put it back exactly the way it was
        setError(err);
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [saves, savedKeys, busy]);

  return { isSaved, toggle, saves, loading, error, reload: load };
}

export default useSaves;
