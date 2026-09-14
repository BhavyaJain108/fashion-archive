import { useCallback, useEffect, useRef, useState } from 'react';
import { AlbumsAPI } from '../api';
import { canonicalFilters, keyOf, rowOfTarget, targetOfRow } from './useSaves';

// Albums: the shelf, one album's contents in order, and the seven writes that
// change them.
//
//   useAlbums(albumId, { saves, shelf })
//     -> { albums, loading,                          the shelf
//          album, items, itemsLoading,               the one that is open
//          createAlbum, renameAlbum,                 the album itself
//          setAlbumOptions, deleteAlbum,
//          addToAlbum, removeFromAlbum,              what is in it
//          reorderAlbum,
//          error, reload }
//
// One hook and not two, because the shelf and the open album are not
// independent: every write to an album's contents changes the shelf row's
// `item_count` and can change its cover. Two hooks would be two lists holding
// the same fact, and the count on the shelf would drift from the tiles on
// screen — the "two readings of one thing" mistake useSaves exists to avoid.
//
// `albumId` is the album the page has open, or null for a page that only
// shows the shelf. Pass it and `album`/`items` are that album; leave it off
// and they are null and []. The writes all take an album id anyway, so a page
// showing the shelf can add to any album on it without opening one.
//
// `shelf` is whether to fetch the shelf at all, and it defaults to true
// because two of the three callers draw one. The album page does not — the
// shelf is the library's sidebar — so it opened an album with two requests
// and threw the answer to one of them away. With no shelf the counts below
// have no row to move and quietly do nothing, which is right: there is
// nothing on screen showing them.
//
// The function names are the API client's names, deliberately. `deleteAlbum`
// and `removeFromAlbum` are the two destructive acts this feature has, they
// are one letter apart in a menu, and only one of them is recoverable — a
// button wired to the wrong one deletes an arrangement instead of a tile. One
// vocabulary from the button to the endpoint means the miswiring has to be
// visible at the call site.
//
// Everything on screen is a function of `albums` and `items`, the rows
// themselves. There is no second "which tiles are in which album" state to
// drift out of step with them, which is what makes every rollback below a
// matter of putting rows back.

// ------------------------------------------------------------- the star ---
//
// `saves` is the optional collaborator that owns the star, and it is optional
// because only one of the two callers has one on screen.
//
//   { isSaved(target) -> bool, setSaved(target, saved),
//     onUnsaved(listener) -> unsubscribe, reload() }
//
// Adding something unsaved to an album SAVES it — one user action, two server
// effects, in one transaction. The album half of that is this hook's state and
// is updated optimistically below. The favourite half is `useSaves`'s state,
// and there is exactly one owner of the list a star reads; this hook must not
// become a second one. So it asks the owner to move the marker and, if the
// write fails, asks it to move it back — and it only ever moves a marker it
// moved itself, because un-starring a row that was already saved is the same
// bug pointing the other way.
//
// With no collaborator the album half is still optimistic and the star simply
// follows on the next load of the favourites list. Nothing here breaks; the
// star is late.
//
// `onUnsaved` is the other direction, and it is a notification rather than a
// handle on the list. Unsaving something is not an album write and does not
// come through this hook at all — but `album_items` is ON DELETE CASCADE on
// the favourite, so the server empties the thing out of every album it was in
// inside the same statement and tells nobody. The shelf's `item_count` is
// stale from that instant, and permanently: the next add counts up from the
// stale number, so the shelf says two over an album holding one and goes on
// saying it until the page is remounted. Told that a save went, this hook
// asks the server what it holds now. It is not handed the saved list, for the
// reason above — one owner.
//
// `reload` is the third: an add whose answer this hook could not read may or
// may not have saved the thing, and the star is not this hook's to decide. It
// asks the owner to go and look, the same way it asks the server about its own
// half. Guessing either way is a bug — a star put out over a saved row, or one
// left lit over a row nothing saved.
const NO_SAVES = {
  isSaved: () => true,
  setSaved: () => {},
  onUnsaved: () => () => {},
  reload: () => {},
};

// ------------------------------------------------------------- reading ---

// Album ids arrive as numbers from the server and as strings from the route,
// and `7 === '7'` is false. Every comparison of two album ids goes through
// here so a deep link into an album cannot silently match nothing.
export const sameAlbum = (a, b) => (
  a !== null && a !== undefined && b !== null && b !== undefined && String(a) === String(b)
);

// The cover a shelf row should show for these items: the first one carrying a
// photograph, in the album's own order. An album of nothing but saved views
// has none, and null is what the server sends for that.
export function coverOf(rows) {
  const withImage = (rows || []).find(row => row && row.image_path);
  return withImage ? withImage.image_path : null;
}

// One album item's identity, for the purpose of "is this the same write".
//
// The content key first — `useSaves`'s key, unchanged — because the same look
// can be added by its favourite id from the library and as a target from the
// archive page, and the two must queue behind each other rather than race. An
// item those key functions cannot name falls back to its id.
export function itemKeyOf(row) {
  const key = row ? keyOf(targetOfRow(row)) : null;
  if (key) return key;
  const id = row && row.id;
  return id === null || id === undefined ? null : `#${id}`;
}

// `ids` as an order, applied to the rows there actually are.
//
// This is both the optimistic reorder AND its rollback: undoing a reorder is
// applying the previous order to the list as it stands now, not restoring a
// remembered array. A remembered array would resurrect a tile another write
// removed while this one was out, which is the snapshot mistake useSaves was
// reviewed into fixing. Anything the list names but `ids` does not keeps its
// relative position, at the end — sort is stable — which is as close as the
// client gets to the server's "keeps the index it had".
export function applyOrder(rows, ids) {
  const at = new Map();
  (ids || []).forEach((id, index) => { if (!at.has(id)) at.set(id, index); });
  const rank = (row) => (at.has(row.id) ? at.get(row.id) : Number.MAX_SAFE_INTEGER);
  return [...(rows || [])].sort((a, b) => rank(a) - rank(b));
}

// Whether the write the server answered actually happened.
//
// A resolved promise is not a completed write, and phase 3 found exactly that
// swallowed in useSaves: the favourites endpoints answer a change they did not
// make with HTTP 200 and {"success": false}, the star went dark, and the row
// stayed in the database. The album endpoints do it too.
//
// Two fields, because the album endpoints have two ways of refusing:
//
//   ok === false          404 not yours, 409 the name is taken, 400 a body the
//                         server would not store. Always a failure.
//   success === false     200, and the only endpoint that sends it is
//   with ok               DELETE .../items/<id>: "Not in that album".
//
// The second is the case useSaves' note is about. The reader asked for the
// thing to be out of the album and the server says it is not in the album:
// that is the state they asked for, reached before they asked. Rolling it back
// would put a tile on screen for a membership row that does not exist — the
// same bug as the swallowed refusal, pointing the other way. So `remove` alone
// passes `refusalMeansDone`, and nothing else does.
//
// An answer with neither field is taken at its word, as useSaves takes one:
// inventing a failure out of a missing field breaks every write that works.
export function wrote(answer, { refusalMeansDone = false } = {}) {
  if (!answer || typeof answer !== 'object') return true;
  if (answer.ok === false) return false;
  if (answer.success === false) return refusalMeansDone;
  return true;
}

// A 2xx that says nothing readable about what it did.
//
// `albumRequest` marks a body it could not parse — or one that is not an
// object — with `bodyRead: false`. Such an answer used to arrive as
// `{ok: true, status: 200}`, which is indistinguishable from a write that
// worked and had nothing to add, so `wrote` above said true over a proxy's
// HTML error page.
//
// This is a THIRD state and not a fourth flavour of failure. A failure is
// rolled back, because the server did not make the change. An unknown answer
// is not rolled back, because it may have: the only honest move is to apply
// neither half and go and ask.
//
// An answer with no `bodyRead` at all — every hand-written one, and every
// caller that does not go through `albumRequest` — is taken at its word,
// which is the same rule `wrote` applies to a missing `success`.
export function unread(answer) {
  return Boolean(answer) && typeof answer === 'object'
    && answer.ok !== false && answer.bodyRead === false;
}

// Whether an add's answer carries the two things the caller reads off it.
//
// `favourite_id` is the id the tile is stamped with and the id every later
// write names it by; `added` is whether the thing went in or was already
// there, and it has to be a BOOLEAN, because `undefined` is not `false` and
// skipping the "already in this album" correction is a count one too high.
// An answer missing either is not a failure and not a success: it is the same
// unknown as an unreadable one, and gets the same reload.
export function addAnswered(answer) {
  if (!answer || typeof answer !== 'object') return false;
  const id = answer.favourite_id;
  return id !== null && id !== undefined && typeof answer.added === 'boolean';
}

// The reason the server gave, or a plain one. `error` is what the album
// endpoints put a refusal in; `message` is what they put a report in.
export function reasonOf(answer) {
  const said = answer && (answer.error || answer.message);
  return new Error(said || 'The server did not make that change');
}

// ---------------------------------------------------------------- hook ---

export function useAlbums(albumId = null, options = {}) {
  const [albums, setAlbums] = useState([]);
  const [album, setAlbum] = useState(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [itemsLoading, setItemsLoading] = useState(albumId !== null && albumId !== undefined);
  const [error, setError] = useState(null);

  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  // Read through a ref, so a caller writing `{ saves }` inline — which every
  // caller will — does not rebuild every callback below on every render.
  const saves = useRef(options.saves || NO_SAVES);
  useEffect(() => { saves.current = options.saves || NO_SAVES; });

  // The rows, readable synchronously, for the reason useSaves has the same
  // pair: a write reads the list, changes it, and a write that starts later in
  // the same tick must read that change — state does not land until the next
  // render. Everything that changes a list goes through these, so the ref and
  // the state are set in one statement and cannot part company.
  const albumsRef = useRef(albums);
  const applyAlbums = useCallback((rows) => { albumsRef.current = rows; setAlbums(rows); }, []);
  const albumRef = useRef(album);
  const applyAlbum = useCallback((row) => { albumRef.current = row; setAlbum(row); }, []);
  const itemsRef = useRef(items);
  const applyItems = useCallback((rows) => { itemsRef.current = rows; setItems(rows); }, []);

  const opened = useCallback((id) => sameAlbum(id, albumId), [albumId]);

  // ------------------------------------------------------------ loading ---

  const wantShelf = options.shelf !== false;

  const load = useCallback(async () => {
    if (!wantShelf) {
      // Nothing to wait for, so `loading` must not sit true over a page that
      // is already drawn.
      if (alive.current) setLoading(false);
      return;
    }
    try {
      const rows = await AlbumsAPI.getAlbums();
      if (!alive.current) return;
      applyAlbums(rows || []);
    } catch (err) {
      console.error('Could not load albums:', err);
      if (alive.current) setError(err);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [applyAlbums, wantShelf]);

  // "An album id that is not yours is a 404, not a 403" — so gone and never
  // yours arrive here as one answer, and there is nothing to tell apart. Both
  // mean: stop showing that album. Without this the shelf keeps a row whose
  // every button fails.
  const forget = useCallback((id) => {
    applyAlbums(albumsRef.current.filter(row => !sameAlbum(row.id, id)));
    if (albumRef.current && sameAlbum(albumRef.current.id, id)) {
      applyAlbum(null);
      applyItems([]);
    }
  }, [applyAlbums, applyAlbum, applyItems]);

  // One token per load, because switching albums quickly starts two and the
  // one that answers last is not necessarily the one that was asked for last.
  const loadCount = useRef(0);

  const loadItems = useCallback(async () => {
    loadCount.current += 1;
    const token = loadCount.current;
    const mine = () => alive.current && token === loadCount.current;
    if (albumId === null || albumId === undefined) {
      applyAlbum(null);
      applyItems([]);
      setItemsLoading(false);
      return;
    }
    setItemsLoading(true);
    try {
      const answer = await AlbumsAPI.getAlbum(albumId);
      if (!mine()) return;
      if (!answer) { forget(albumId); return; }   // 404: not this user's album
      applyAlbum(answer.album || null);
      applyItems(answer.items || []);
    } catch (err) {
      console.error('Could not load album:', err);
      if (mine()) setError(err);
    } finally {
      if (mine()) setItemsLoading(false);
    }
  }, [albumId, applyAlbum, applyItems, forget]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadItems(); }, [loadItems]);

  const reload = useCallback(async () => {
    await Promise.all([load(), loadItems()]);
  }, [load, loadItems]);

  // A save deleted anywhere on the page has already been cascaded out of
  // every album on the server. Nothing local can be patched honestly from
  // here — the key names one favourite, and which albums held it is the
  // server's fact, not ours — so the answer is to ask again.
  //
  // `options.saves` directly rather than the ref above: this is an effect
  // and wants to re-subscribe if the collaborator is ever replaced, and both
  // callers memoise the object they pass.
  const collaborator = options.saves;
  useEffect(() => {
    const subscribe = collaborator && collaborator.onUnsaved;
    if (typeof subscribe !== 'function') return undefined;
    return subscribe(() => { reload(); });
  }, [collaborator, reload]);

  // ------------------------------------------------- optimistic changes ---
  //
  // Every one of these applies a change and returns its INVERSE, and the
  // inverse runs against the list as it stands when it is called rather than
  // putting a remembered copy back. Writes to different albums and different
  // tiles are in flight at the same time by design, so a copy taken before
  // this write started is missing whatever landed since, and restoring it
  // would quietly undo that too.

  // One shelf row (and the open album's own copy of it) changed, and the
  // change undone.
  const patchAlbum = useCallback((id, change) => {
    const source = albumsRef.current.find(row => sameAlbum(row.id, id))
      || (albumRef.current && sameAlbum(albumRef.current.id, id) ? albumRef.current : null);
    const was = {};
    Object.keys(change).forEach(field => { was[field] = source ? source[field] : undefined; });

    const put = (fields) => {
      const patch = (row) => (row && sameAlbum(row.id, id) ? { ...row, ...fields } : row);
      applyAlbums(albumsRef.current.map(patch));
      if (albumRef.current && sameAlbum(albumRef.current.id, id)) applyAlbum(patch(albumRef.current));
    };
    put(change);
    return () => put(was);
  }, [applyAlbums, applyAlbum]);

  // The shelf row's count moved by `delta`, and its cover kept honest.
  //
  // For the open album the cover is derived from the tiles we hold, so it is
  // right after every add and every remove. For an album that is not open we
  // have no tiles: a cover is filled in if it had none, and left alone
  // otherwise rather than guessed at. Both are undone by re-deriving, so the
  // inverse never clobbers a cover another write set meanwhile.
  const recount = useCallback((id, delta, image) => {
    const settle = (step) => {
      const row = albumsRef.current.find(r => sameAlbum(r.id, id));
      if (!row) return;
      const count = Math.max(0, (row.item_count || 0) + step);
      let cover = row.cover_image_path;
      if (opened(id)) cover = coverOf(itemsRef.current);
      else if (step > 0 && !cover && image) cover = image;
      patchAlbum(id, { item_count: count, cover_image_path: cover });
    };
    settle(delta);
    return () => settle(-delta);
  }, [opened, patchAlbum]);

  // --------------------------------------------------------- the queue ---
  //
  // One write at a time PER THING WRITTEN, not one write at a time overall.
  // The global flag useSaves started with dropped clicks the moment the same
  // control existed in four places, and an album page has a tile per item and
  // a shelf besides. The keys are:
  //
  //   album:<id>            rename, options, delete       — one album's row
  //   item:<album>:<key>    add, remove                   — one tile
  //   order:<album>         reorder                       — one arrangement
  //
  // What the flag was protecting is real but it is per key: the optimistic
  // change means a second press on the SAME thing reads the state the first
  // one moved and would send the opposite write against a row the server has
  // not heard of. So a repeat on a key already in flight is neither sent
  // alongside it nor dropped — it is held, one deep, and run when the write in
  // front of it lands. One deep, because three presses are two states and the
  // middle one is not a state anybody asked to end up in.
  //
  // `createAlbum` is deliberately not in here: it has no id to key on until
  // the server mints one, and two creates of one name are settled by the
  // server's 409 rather than by a queue.
  const inFlight = useRef(new Set());
  const queued = useRef(new Map());

  // EVERY `run` below applies its own optimistic change, and applies it when
  // it runs rather than when it was made. That is not a detail of where the
  // lines sit.
  //
  // A press held behind one that fails is dropped: it was queued against a
  // state the server never reached. If it had already applied its change,
  // that change would be left standing with its undo thrown away — and the
  // failed press's rollback does not cover it, because these inverses are
  // RELATIVE. `recount(+1)` is undone by `settle(-1)`; two +1s against one -1
  // is one too many, and the shelf reads one higher than the album holds for
  // the rest of the session. Applied inside the run, a dropped press never
  // applied anything and there is nothing of it to undo.
  //
  // The first press of a burst is unaffected: `run()` is called synchronously
  // here, before this function's first await, so the reader still sees the
  // change in the same tick they pressed in.
  const serialise = useCallback(async (key, run) => {
    if (inFlight.current.has(key)) {
      queued.current.set(key, run);
      return true;        // it will run; a failure surfaces through `error`
    }
    inFlight.current.add(key);
    let ok = true;
    try {
      let next = run;
      while (next) {
        // eslint-disable-next-line no-await-in-loop
        ok = await next();
        if (!ok) {
          // The burst failed here. Whatever was held behind it is dropped
          // unrun, which is exactly what makes this safe: it has changed
          // nothing, and this press's own rollback restores the list to what
          // the server still holds.
          queued.current.delete(key);
          break;
        }
        next = queued.current.get(key) || null;
        queued.current.delete(key);
      }
    } finally {
      inFlight.current.delete(key);
    }
    return ok;
  }, []);

  // One write, its answer read one way. `undo` is the inverse of the
  // optimistic change and it is run here and nowhere else, so no operation can
  // be written that forgets it.
  const writeThrough = useCallback(async (
    id, send, undo,
    {
      refusalMeansDone = false, forgetOn404 = true,
      unknownIf = () => false, askOnThrow = false,
    } = {},
  ) => {
    // Neither applied nor undone: the server may have made this change and
    // may not, and only the server can say. Everything optimistic is left
    // where it is and the truth is read back over it.
    const askTheServer = (err, { andTheStar = false } = {}) => {
      console.error('Could not tell what the album write did:', err);
      reload();
      // The save half is not ours to decide either. See NO_SAVES.
      if (andTheStar && typeof saves.current.reload === 'function') saves.current.reload();
      if (alive.current) setError(err);
      return null;
    };

    let answer;
    try {
      answer = await send();
    } catch (err) {
      console.error('Could not change album:', err);
      // A throw is not proof the write did not happen — the request may have
      // been served, the row written, and the connection lost on the way
      // back. Where that matters (the add, which SAVES the thing as well as
      // filing it) rolling back would leave a dark star over a row that is
      // saved, so the caller asks for the truth instead.
      if (askOnThrow) return askTheServer(err, { andTheStar: true });
      undo();
      if (alive.current) setError(err);
      return null;
    }
    if (!wrote(answer, { refusalMeansDone })) {
      const err = reasonOf(answer);
      console.error('Could not change album:', err);
      undo();
      if (alive.current) setError(err);
      if (forgetOn404 && answer && answer.status === 404) forget(id);
      return null;
    }
    // A 2xx nobody could read, or one whose body does not carry what this
    // caller has to have off it. See `unread`: not a success, not a failure.
    if (unread(answer) || unknownIf(answer)) {
      return askTheServer(
        reasonOf({ message: 'The server did not say what it did' }),
        { andTheStar: askOnThrow },
      );
    }
    if (alive.current) setError(null);
    return answer;
  }, [forget, reload]);

  // ------------------------------------------------- the album itself ---

  // Not optimistic, and the one write here that is not.
  //
  // An album's id is the server's to mint, and both callers want it back: the
  // library navigates into the album it just made, and the picker adds to it.
  // A tile with a made-up id is a link to nowhere, and reconciling one is more
  // machinery than the wait is worth for an action that happens once.
  const createAlbum = useCallback(async (name, opts = {}) => {
    try {
      const answer = await AlbumsAPI.createAlbum(name, opts);
      if (!wrote(answer)) {
        const err = reasonOf(answer);      // 409: this user already has one
        console.error('Could not create album:', err);
        if (alive.current) setError(err);
        return null;
      }
      const made = answer.album || null;
      if (!made) return null;
      // The counts are defaulted before the spread, so the server's own values
      // win if it ever sends them: a new album must have the same shape on the
      // shelf as a listed one, or the first render reads undefined.
      applyAlbums([{ item_count: 0, cover_image_path: null, ...made }, ...albumsRef.current]);
      if (alive.current) setError(null);
      return made;
    } catch (err) {
      console.error('Could not create album:', err);
      if (alive.current) setError(err);
      return null;
    }
  }, [applyAlbums]);

  const renameAlbum = useCallback((id, name) => serialise(`album:${id}`, async () => {
    const undo = patchAlbum(id, { name });
    return Boolean(await writeThrough(id, () => AlbumsAPI.renameAlbum(id, name), undo));
  }), [patchAlbum, serialise, writeThrough]);

  // Only what is passed is sent, and only what is passed is changed here:
  // changing the sort must not reset the layout on the way past, at either end.
  const setAlbumOptions = useCallback((id, opts = {}) => {
    const change = {};
    if (opts.layoutMode !== undefined) change.layout_mode = opts.layoutMode;
    if (opts.sortBy !== undefined) change.sort_by = opts.sortBy;
    if (!Object.keys(change).length) return Promise.resolve(true);

    return serialise(`album:${id}`, async () => {
      // Read when this runs, not when it was asked for: a held press reads
      // the sort the write in front of it actually left behind.
      const sortChanged = change.sort_by !== undefined
        && albumRef.current && sameAlbum(albumRef.current.id, id)
        && albumRef.current.sort_by !== change.sort_by;
      const undo = patchAlbum(id, change);
      const answer = await writeThrough(id, () => AlbumsAPI.setAlbumOptions(id, opts), undo);
      if (!answer) return false;
      // The order itself is the server's: 'designer' and 'season' are an ORDER
      // BY over columns the client does not hold for every kind. So a sort
      // that changed is one more read, rather than a re-sort here that would
      // be right for looks and wrong for saved views.
      if (sortChanged) await loadItems();
      return true;
    });
  }, [patchAlbum, serialise, writeThrough, loadItems]);

  // Deletes the album, NOT the favourites in it. The other button — the one
  // that un-saves — is useSaves' `toggle`, and the two must never be wired to
  // the same control.
  //
  // The open album's tiles are deliberately left on screen: the page that
  // deleted it is navigating away, and blanking it first is a flash of an
  // empty album on the way out. The shelf row goes at once, because that is
  // what the reader is looking at.
  const deleteAlbum = useCallback((id) => serialise(`album:${id}`, async () => {
    const before = albumsRef.current;
    const at = before.findIndex(row => sameAlbum(row.id, id));
    if (at < 0) return false;
    applyAlbums(before.filter(row => !sameAlbum(row.id, id)));
    const undo = () => {
      const rows = albumsRef.current;
      if (rows.some(row => sameAlbum(row.id, id))) return;   // something put it back
      const back = [...rows];
      back.splice(Math.min(at, back.length), 0, before[at]);
      applyAlbums(back);
    };
    return Boolean(await writeThrough(id, () => AlbumsAPI.deleteAlbum(id), undo));
  }), [applyAlbums, serialise, writeThrough]);

  // -------------------------------------------------- what is in one ---

  // `thing` is either something already saved — a row of `useSaves.saves`,
  // which carries the favourite id the server needs — or a target that may not
  // be saved at all, in the shape useSaves takes. An id decides which.
  //
  // Everything below comes off one object, read once. The look write is
  // positional and two of its three arguments are urls, so a triple assembled
  // out of two shows names a row that exists and files the wrong photograph
  // under the right album. Nothing here may reach for a season or a collection
  // by any other name.
  const addToAlbum = useCallback((id, thing) => {
    if (!thing) return Promise.resolve(false);
    const alreadySaved = thing.id !== null && thing.id !== undefined;
    const target = alreadySaved ? null : thing;
    const row = alreadySaved ? thing : { ...rowOfTarget(thing), id: null };
    const key = itemKeyOf(row);
    if (!key) return Promise.resolve(false);      // it names nothing

    const send = () => {
      if (alreadySaved) return AlbumsAPI.addSavedToAlbum(id, thing.id);
      const t = target;
      const kind = t.kind || 'look';
      if (kind === 'show') {
        return AlbumsAPI.addShowToAlbum(id, t.season, t.collection, t.imagePath || '');
      }
      if (kind === 'view') {
        // Sent as the filters this client keyed it on, not as they arrived:
        // saving through one rule and reading through another is how a view
        // becomes two rows.
        return AlbumsAPI.addViewToAlbum(id, canonicalFilters(t.filters), t.name || '');
      }
      return AlbumsAPI.addLookToAlbum(id, t.season, t.collection, t.look, t.imagePath || '');
    };

    return serialise(`item:${id}:${key}`, async () => {
      // ---- the optimistic half, and it is two halves ----
      //
      // Inside the run, so that a press dropped behind a failure applied
      // nothing. See `serialise`: `recount`'s inverse is relative, so a change
      // applied by a run that never executes is a count that is permanently
      // one out.
      //
      // A tile that has no favourite id yet is marked, and the mark is what
      // both the reconcile and the rollback find it by. Not its content key:
      // the same look may already be in this album, and a rollback that
      // removed it by content would take the tile the reader put there last
      // week.
      const mark = `pending:${key}:${Date.now()}:${Math.random()}`;
      const duplicate = opened(id)
        && itemsRef.current.some(r => r.id !== null && r.id !== undefined && r.id === row.id);

      let dropTile = () => {};
      if (opened(id) && !duplicate) {
        applyItems([...itemsRef.current, { ...row, pending: mark }]);
        dropTile = () => applyItems(itemsRef.current.filter(r => r.pending !== mark));
      }
      const undoCount = duplicate ? () => {} : recount(id, +1, row.image_path);

      // The save half. Only moved if it is ours to move: a star already lit
      // was lit by somebody else, and putting it out on our failure would
      // leave a dark star over a saved row.
      const lighting = Boolean(target) && !saves.current.isSaved(target);
      if (lighting) saves.current.setSaved(target, true);
      const undoStar = lighting ? () => saves.current.setSaved(target, false) : () => {};

      const undo = () => { dropTile(); undoCount(); undoStar(); };

      // `forgetOn404` is off here and only here: this endpoint answers 404 for
      // an album that is not yours AND for a favourite id that is not yours,
      // and dropping the album off the shelf for the second would be a wrong
      // answer to a right refusal.
      const answer = await writeThrough(id, send, undo, {
        forgetOn404: false,
        // An add that does not come back with an id and an `added` is
        // unknown, not a success: there is nothing to stamp the tile with and
        // no way to tell "filed" from "was already there".
        unknownIf: (a) => !addAnswered(a),
        // And a dropped connection is not proof it did not happen. This
        // endpoint saves the favourite and files it in one transaction, so
        // rolling back would put out a star over a row that is saved.
        askOnThrow: true,
      });
      if (!answer) return false;

      // Both halves landed. What the server reports is which of them it had to
      // do — `added: false` is "it was already in this album", which is the
      // state that was asked for and not a failure, but our count was one too
      // high for it, so that half of the optimistic change is undone.
      if (answer.added === false) {
        undoCount();
        const held = itemsRef.current.some(
          r => r.pending !== mark && r.id !== null && r.id !== undefined
            && r.id === answer.favourite_id);
        if (held) dropTile();                       // we drew it twice
        else applyItems(itemsRef.current.map(
          r => (r.pending === mark ? { ...r, id: answer.favourite_id, pending: undefined } : r)));
        return true;
      }
      // The tile gets the id the server gave the favourite, which is what
      // `removeFromAlbum` and `reorderAlbum` name it by from here on.
      applyItems(itemsRef.current.map(
        r => (r.pending === mark ? { ...r, id: answer.favourite_id, pending: undefined } : r)));
      return true;
    });
  }, [opened, applyItems, recount, serialise, writeThrough]);

  // Takes it out of the album. It stays saved.
  const removeFromAlbum = useCallback((id, favouriteId) => {
    // The queue key is the only thing read before the run: it names which
    // write this queues behind, and it must be the same for two presses on
    // one tile whether or not the first has already taken the tile off screen.
    const held = itemsRef.current.find(row => row.id === favouriteId);
    const key = held ? itemKeyOf(held) : `#${favouriteId}`;

    return serialise(`item:${id}:${key}`, async () => {
      // Applied here and not above: a press dropped behind a failure must
      // have changed nothing. See `serialise`.
      const before = itemsRef.current;
      const at = before.findIndex(row => row.id === favouriteId);

      let putBack = () => {};
      if (at >= 0) {
        applyItems(before.filter(row => row.id !== favouriteId));
        putBack = () => {
          const rows = itemsRef.current;
          if (rows.some(row => row.id === favouriteId)) return;  // something put it back
          const back = [...rows];
          back.splice(Math.min(at, back.length), 0, before[at]);
          applyItems(back);
        };
      }
      const undoCount = recount(id, -1);
      const undo = () => { putBack(); undoCount(); };

      // See `wrote`: a 200 saying "Not in that album" is the state that was
      // asked for, reached before it was asked. The tile stays gone.
      return Boolean(
        await writeThrough(id, () => AlbumsAPI.removeFromAlbum(id, favouriteId), undo,
          { refusalMeansDone: true }),
      );
    });
  }, [applyItems, recount, serialise, writeThrough]);

  // The whole arrangement in one request, first to last — N requests for one
  // drag is N chances to arrive out of order.
  //
  // Two drags racing is the same hazard one level up, and the answer is the
  // queue: a reorder while a reorder is out is held, one deep, and sent when
  // the first lands, so the server is never asked for two orders at once and
  // the order that sticks is the last one the reader made. If the first fails,
  // the held one is dropped and the rollback puts back the order from before
  // the first — which is the order the server still holds. An interleaving of
  // the two is not an order anybody asked for and cannot be reached from here.
  const reorderAlbum = useCallback((id, favouriteIds) => {
    const ids = favouriteIds || [];
    if (!opened(id)) {
      // No tiles held for it, so nothing to reorder optimistically and nothing
      // to undo. The write still goes, and the next load reads the result.
      return serialise(`order:${id}`, async () => Boolean(
        await writeThrough(id, () => AlbumsAPI.reorderAlbum(id, ids), () => {}),
      ));
    }
    // THE ONE optimistic change that is applied outside the run, and the
    // reason is that its inverse is absolute where `recount`'s is relative.
    //
    // `applyOrder` states a whole order over the list as it stands; undoing a
    // reorder is stating the previous whole order, so the first drag's
    // rollback puts back the order the server still holds WHATEVER a dropped
    // drag behind it did to the tiles meanwhile. A count moved by +1 is not
    // like that: two +1s against one -1 is one too many, which is why every
    // other operation here applies inside the run.
    //
    // And a drag is direct manipulation. The tiles have to move under the
    // reader's hand, including the second drag of a burst — waiting a round
    // trip to show it is the one place where "applied when it runs" would be
    // felt as the control not working.
    const was = itemsRef.current.map(row => row.id);
    applyItems(applyOrder(itemsRef.current, ids));
    const undo = () => applyItems(applyOrder(itemsRef.current, was));

    return serialise(`order:${id}`, async () => Boolean(
      await writeThrough(id, () => AlbumsAPI.reorderAlbum(id, ids), undo),
    ));
  }, [opened, applyItems, serialise, writeThrough]);

  return {
    albums, album, items,
    loading, itemsLoading, error,
    reload,
    createAlbum, renameAlbum, setAlbumOptions, deleteAlbum,
    addToAlbum, removeFromAlbum, reorderAlbum,
  };
}

export default useAlbums;
