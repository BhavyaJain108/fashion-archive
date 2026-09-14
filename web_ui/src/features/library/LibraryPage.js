import React, { useState, useEffect, useMemo, useRef } from 'react';
import TopBar from '../../shared/ui/TopBar';
import { FashionArchiveAPI } from '../../shared/api';
import { slugify } from '../../app/routes';
import { cleanDesignerName } from '../../shared/lib/designerName';
import { usePersistentState } from '../../shared/hooks/usePersistentState';
import { useAlbums } from '../../shared/hooks/useAlbums';
import AlbumPicker from '../../shared/ui/AlbumPicker';
import { lookLabel, lookAlt } from '../../shared/lib/lookLabel';
import { filterPairs, kindOf, showIdOf } from '../../shared/lib/savedRow';
import {
  normalizeGroupMode, normalizeKind, normalizeViewMode,
} from '../../shared/lib/preferences';
import './LibraryPage.css';

// The sidebar's first row: every favourite, rather than one collection.
const ALL = '__all__';

// How many rows one page of a pane is. The same number `useSaves` uses, and
// for the same reason: a page that does not fill the window is a scroll that
// loads twice before the reader has seen anything.
const PAGE_SIZE = 200;

// A pane before its first page has landed. `total` is zero rather than
// unknown, so the sidebar counts read zero while loading rather than NaN.
const EMPTY_PANE = {
  rows: [], total: 0, hasMore: false, cursor: null, loadingMore: false,
};
const EMPTY_PANES = { look: EMPTY_PANE, show: EMPTY_PANE, view: EMPTY_PANE };

// The three kinds, in the order the sidebar lists them, with what to call
// them and what to say when a reader has none of that kind. The empty text
// is the whole of Step 5: a reader with looks and no views has never seen a
// view and cannot be expected to guess, so the pane says what one is and
// where it comes from rather than going blank.
const KINDS = [
  {
    kind: 'look',
    label: 'Looks',
    empty: 'No saved looks',
    hint: 'Open a show and press the star on a photograph to keep it here.',
  },
  {
    kind: 'show',
    label: 'Shows',
    empty: 'No saved shows',
    hint: 'A show is a whole collection. Press the star on a row in the '
        + 'archive list to keep the run, not one photograph of it.',
  },
  {
    kind: 'view',
    label: 'Views',
    empty: 'No saved views',
    // A designer is deliberately not in this list. A saved view is its
    // filters, `designer` is not one of them, and the star in the filter bar
    // is disabled in designer mode for that reason — so naming a designer
    // here taught the one move that does not work.
    hint: 'A view is a set of filters — a year, a season, a city. Narrow '
        + 'the archive down to what you want to come back to and press '
        + 'Save this view.',
  },
];

function collectionKey(fav) {
  return `${fav.collection.designer}::${fav.season.name}`;
}

// `navigate` arrives as a prop — App's own `go` — and is never imported from
// app/router. Everything this page does that is not a fetch is a navigation,
// so importing it would make the page untestable without stubbing a module and
// unmountable anywhere App is not.
function LibraryPage({
  currentPage, onPageSwitch, currentUser, onLogout, navigate,
}) {
  // ── The shelf, a page at a time, per kind ────────────────────────────
  //
  // Three pages rather than one, and that is not an accident of the panes.
  // The three kinds are interleaved by date on the server, so ONE paged fetch
  // would fill the first page with whatever the reader saved most recently —
  // a reader with four hundred looks and three views would see an empty Views
  // pane until they had paged through every look, for three rows. Each pane
  // asks for its own kind, which the endpoint has always taken, so each pane's
  // first page is that pane's first page.
  //
  // `total` is the server's count of the whole kind, not of what is loaded:
  // the sidebar counts with it, and counting the loaded rows would have the
  // library claim the reader has as many saves as are currently drawn.
  //
  // `cursor` is the server's opaque bookmark, passed back untouched. Paging is
  // by cursor and not by offset because this is the page that unsaves rows out
  // of the very list it is paging through — see `favourites.list_page`.
  const [panes, setPanes] = useState(EMPTY_PANES);
  const [loading, setLoading] = useState(true);

  // Why there is nothing to show, when the reason is not "you have kept
  // nothing". `loadPanes` used to catch, log and leave `EMPTY_PANES`, so a
  // dead session or a 500 rendered as "No saved looks" over the hint about
  // pressing the star — the worst available answer, because it tells a reader
  // with four hundred saves that they have none, on the page whose only job
  // is to hold them, and then instructs them to start again.
  const [panesError, setPanesError] = useState(null);

  // Which of the three kinds is on screen. The page holds looks, shows and
  // views now, and they are three different things to look at rather than
  // three sections of one list — a saved view has no photograph and a saved
  // show has no look number, so nothing about the look gallery fits them.
  const [kind, setKind] = usePersistentState('library-kind', 'look', {
    deserialize: (raw) => normalizeKind(JSON.parse(raw)),
  });

  // Was App-level state written by the old MenuBar's View menu. It orders
  // the sidebar: RECENT by when a look was saved, BY COLLECTION by designer.
  const [groupMode, setGroupMode] = usePersistentState('library-group-mode', 'view-all', {
    deserialize: (raw) => normalizeGroupMode(JSON.parse(raw)),
  });
  const [selectedKey, setSelectedKey] = useState(ALL);
  const [viewMode, setViewMode] = usePersistentState('library-view-mode', 'single', {
    deserialize: (raw) => normalizeViewMode(JSON.parse(raw)),
  });
  const [selectedIndex, setSelectedIndex] = useState(0);

  // The shelf, and only the shelf — no album id, so the hook holds the rows
  // and nothing's contents. It is the way IN to an album; the way out is the
  // album page's own Back, and both are navigate + buildRoute.
  //
  // No `{ saves }` collaborator here, and that is not an omission. The
  // collaborator exists so that adding an UNSAVED thing can light its star;
  // everything on this page is saved already, by definition — it is the list
  // of saved things — so every add from here goes by favourite id and
  // changes nothing about what is saved. The archive page, where a thing may
  // not be saved yet, is where the collaborator is passed.
  const {
    albums, createAlbum, addToAlbum, reload: reloadAlbums, error: albumsError,
  } = useAlbums();

  // What is ticked, by favourite id. Ids and not indices: the panes re-sort
  // and re-filter under the selection, and an index would follow whatever
  // landed in that slot.
  const [picked, setPicked] = useState(() => new Set());
  const [pickerOpen, setPickerOpen] = useState(false);
  const [albumBusy, setAlbumBusy] = useState(false);

  const thumbStripRef = useRef(null);
  const activeThumbRef = useRef(null);

  useEffect(() => {
    loadPanes();
    // Mount only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // One pane's first page, replacing whatever it held. Used on mount and
  // nowhere else — a reload of one kind is `loadPanes`.
  const loadPane = async (which) => {
    const page = await FashionArchiveAPI.getFavouritesPage(
      { kind: which, limit: PAGE_SIZE });
    return {
      rows: page.favourites,
      total: page.total,
      hasMore: page.hasMore,
      cursor: page.nextCursor,
      loadingMore: false,
    };
  };

  const loadPanes = async () => {
    try {
      setLoading(true);
      const [look, show, view] = await Promise.all(KINDS.map(k => loadPane(k.kind)));
      setPanes({ look, show, view });
      setPanesError(null);
    } catch (error) {
      console.error('LibraryPage: Error loading favourites:', error);
      // The panes are left as they were rather than emptied: on a reload that
      // failed, what is on screen is still the truth as of the last one.
      setPanesError(error);
    } finally {
      setLoading(false);
    }
  };

  // The next page of one pane, appended.
  //
  // The guard is on the pane's CURSOR rather than on `hasMore`, and the cursor
  // is cleared before the request goes out: `hasMore` is state and lags a
  // render, so two quick presses would both see it true and the same page
  // would land twice. A failure puts the cursor back, so the control the
  // reader pressed stays pressable rather than becoming the end of their
  // library.
  const loadMoreOf = async (which) => {
    const from = (panes[which] || {}).cursor;
    if (!from) return;
    setPanes(prev => ({
      ...prev, [which]: { ...prev[which], cursor: null, loadingMore: true },
    }));
    try {
      const page = await FashionArchiveAPI.getFavouritesPage(
        { kind: which, limit: PAGE_SIZE, cursor: from });
      setPanes(prev => ({
        ...prev,
        [which]: {
          // Appended to what is there NOW: a row unsaved while this page was
          // in flight has already gone, and rebuilding from a snapshot taken
          // before the request would put it back.
          rows: [...prev[which].rows, ...page.favourites],
          total: page.total,
          hasMore: page.hasMore,
          cursor: page.nextCursor,
          loadingMore: false,
        },
      }));
    } catch (error) {
      console.error('LibraryPage: Error loading more favourites:', error);
      setPanes(prev => ({
        ...prev, [which]: { ...prev[which], cursor: from, loadingMore: false },
      }));
    }
  };

  // GET /api/favourites/stats is no longer read here, and the counts did not
  // get worse for it. Every count this page shows is now `panes[kind].total`,
  // which is the same COUNT(*) narrowed the same way and arrives with the page
  // it describes — where the stats call was a second request whose answer
  // could be a moment older than the rows beside it. The endpoint is still
  // there; nothing in this build asks it.

  const looks = panes.look.rows;
  const shows = panes.show.rows;
  const views = panes.view.rows;

  // Every loaded row, of every kind. Read by the selection and by nothing
  // else: a ticked row has to be findable by id whichever pane it was ticked
  // in, and only rows that are loaded can have been ticked.
  const favourites = useMemo(
    () => [...panes.look.rows, ...panes.show.rows, ...panes.view.rows],
    [panes],
  );

  const collections = useMemo(() => {
    const byKey = new Map();

    looks.forEach(fav => {
      const key = collectionKey(fav);
      if (!byKey.has(key)) {
        byKey.set(key, {
          key,
          designer: fav.collection.designer,
          season: fav.season.name,
          items: [],
          latest: 0,
        });
      }
      const group = byKey.get(key);
      group.items.push(fav);
      const added = new Date(fav.date_added).getTime();
      if (added > group.latest) group.latest = added;
    });

    const groups = [...byKey.values()];
    groups.forEach(g => g.items.sort((a, b) => a.look.number - b.look.number));
    groups.sort((a, b) => (
      groupMode === 'by-collection'
        ? a.designer.toLowerCase().localeCompare(b.designer.toLowerCase())
        : b.latest - a.latest
    ));
    return groups;
  }, [looks, groupMode]);

  // A selected collection can vanish out from under selectedKey — its last
  // favourite gets removed while the sidebar row is still "selected". Rather
  // than trust every caller that shrinks `favourites` to also reconcile
  // selectedKey, derive the key actually used for filtering fresh on every
  // render: if it doesn't name a surviving group, treat it as ALL. This is
  // what both `visible` and the sidebar highlight read below, so a vanished
  // selection falls back to "all favourites" no matter how it vanished.
  const effectiveSelectedKey = (selectedKey !== ALL && !collections.some(g => g.key === selectedKey))
    ? ALL
    : selectedKey;

  const visible = useMemo(() => {
    if (effectiveSelectedKey !== ALL) {
      const group = collections.find(g => g.key === effectiveSelectedKey);
      return group ? group.items : [];
    }

    const all = [...looks];
    if (groupMode === 'by-collection') {
      all.sort((a, b) => {
        const byDesigner = a.collection.designer.toLowerCase()
          .localeCompare(b.collection.designer.toLowerCase());
        return byDesigner !== 0 ? byDesigner : a.look.number - b.look.number;
      });
    } else {
      all.sort((a, b) => new Date(b.date_added) - new Date(a.date_added));
    }
    return all;
  }, [looks, collections, effectiveSelectedKey, groupMode]);

  // Safety net only: the normal removal path (handleRemove) computes the
  // in-range index itself, in the same tick as the favourites update, so
  // this should be a no-op on that path. Kept in case some other caller
  // shrinks the list without going through handleRemove.
  useEffect(() => {
    setSelectedIndex(i => (visible.length === 0 ? 0 : Math.min(i, visible.length - 1)));
  }, [visible.length]);

  // Center the active thumbnail in the strip — same approach as
  // HighFashionPage's thumb strip, which faces the identical problem: the
  // strip's scrollbar is hidden, so without this, arrowing past the visible
  // width moves the active thumb off-screen with no visual cue that more
  // thumbs exist off to the side.
  useEffect(() => {
    if (activeThumbRef.current && thumbStripRef.current) {
      const strip = thumbStripRef.current;
      const thumb = activeThumbRef.current;
      // Measure with rects, not thumb.offsetLeft: offsetLeft is relative to
      // the nearest positioned ancestor, and Favourites has none above the
      // strip (unlike HighFashionPage's .hf2-main), so it fell through to
      // <body> and picked up the sidebar's width as part of the offset.
      const s = strip.getBoundingClientRect();
      const t = thumb.getBoundingClientRect();
      const delta = (t.left + t.width / 2) - (s.left + s.width / 2);
      strip.scrollTo({ left: strip.scrollLeft + delta, behavior: 'smooth' });
    }
    // Re-centre whenever the strip is (re)shown, not just when the index
    // moves within it — switching back to single view, or to a different
    // collection, remounts the strip at scroll position 0 with no other
    // signal that selectedIndex is unchanged. Also re-centre when the
    // number of visible thumbs changes: removing a look upstream of the
    // selection shifts every thumb after it left by one slot width without
    // moving selectedIndex, so visible.length is the only signal that fires.
  }, [selectedIndex, viewMode, effectiveSelectedKey, visible.length]);

  const handleSelectKind = (next) => {
    setKind(next);
    setSelectedIndex(0);
    // The selection is cleared on the way out of a pane. An album holds all
    // three kinds, so carrying it across would work — but the bar would then
    // say "3 selected" over a pane showing none of them, and the reader
    // would be adding things they cannot see.
    setPicked(new Set());
  };

  // ── The selection, and putting it in an album ─────────────────────────
  //
  // A tick box on the thing itself, and a bar that appears when anything is
  // ticked. Not a mode to enter first: the boxes are always there, so adding
  // one thing is one tick and one press rather than three.

  const togglePicked = (favouriteId) => {
    setPicked(prev => {
      const next = new Set(prev);
      if (next.has(favouriteId)) next.delete(favouriteId);
      else next.add(favouriteId);
      return next;
    });
  };

  // The rows themselves, in the order the library holds them. Derived every
  // render rather than stored beside the ids: a row that has been unsaved
  // since it was ticked is simply not in `favourites` any more, so it cannot
  // be added to an album by a stale copy of itself.
  const pickedRows = favourites.filter(fav => picked.has(fav.id));

  // What a tick box is called. Every one of them names its own row, because
  // a reader who cannot see the screen has nothing else to tell twenty
  // identical boxes apart.
  const pickLabel = (fav) => {
    const k = kindOf(fav);
    if (k === 'view') return (fav.view || {}).name || 'saved view';
    const designer = cleanDesignerName((fav.collection || {}).designer || '');
    if (k === 'show') return `${designer} ${(fav.season || {}).name || ''}`.trim();
    return `${designer} ${lookLabel((fav.look || {}).number)}`.trim();
  };

  const pickBox = (fav) => (
    <input
      type="checkbox"
      className="lib-pick"
      checked={picked.has(fav.id)}
      onChange={() => togglePicked(fav.id)}
      // A tile is clickable and a card opens a show; ticking is neither.
      onClick={(e) => e.stopPropagation()}
      aria-label={`Select ${pickLabel(fav)}`}
    />
  );

  // Every ticked row into one album, one at a time.
  //
  // Each of these is already saved and carries its favourite id, so the add
  // goes by id and the endpoint files a row that exists — no second copy of
  // anything, and nothing about what is saved changes.
  //
  // Sequential rather than all at once, so a failure is attributable: the
  // ones before it landed, the selection is kept, and the panel stays open
  // with the reason under it.
  const fillAlbum = async (albumId) => {
    const rows = pickedRows;
    if (!rows.length || albumId === null || albumId === undefined) return false;
    let all = true;
    for (const row of rows) {
      // eslint-disable-next-line no-await-in-loop
      const ok = await addToAlbum(albumId, row);
      if (!ok) all = false;
    }
    return all;
  };

  const addPickedToAlbum = async (albumId) => {
    setAlbumBusy(true);
    const ok = await fillAlbum(albumId);
    setAlbumBusy(false);
    if (!ok) return;
    setPicked(new Set());
    setPickerOpen(false);
  };

  // An album made and filled in one press. Two requests, because the id is
  // the server's to mint — and if the name is taken the 409 stops it here,
  // with the panel still open and the selection still ticked.
  const createAlbumAndAdd = async (name) => {
    setAlbumBusy(true);
    const made = await createAlbum(name);
    const ok = made ? await fillAlbum(made.id) : false;
    setAlbumBusy(false);
    if (!ok) return;
    setPicked(new Set());
    setPickerOpen(false);
  };

  const handleSelectCollection = (key) => {
    setSelectedKey(key);
    setSelectedIndex(0);
  };

  const handleGroupMode = (mode) => {
    setGroupMode(mode);
    setSelectedIndex(0);
  };

  const handlePrev = () => {
    if (visible.length === 0) return;
    setSelectedIndex(i => (i > 0 ? i - 1 : visible.length - 1));
  };

  const handleNext = () => {
    if (visible.length === 0) return;
    setSelectedIndex(i => (i < visible.length - 1 ? i + 1 : 0));
  };

  // ── Unsaving, for all three kinds ─────────────────────────────────────
  //
  // THE destructive act of this feature, and the only one that is. It takes
  // the thing out of the library and, by the cascade on `album_items`, out of
  // every album it was in. Nothing puts it back.
  //
  // The other one — `removeFromAlbum`, on the album page — takes a tile out
  // of one album and leaves the favourite exactly where it was; putting it
  // back is one press of the same picker. So this button is the one that says
  // UNSAVE and carries `ar-btn-danger`, and that button says REMOVE FROM
  // ALBUM and carries no colour at all. They are told apart by what they are
  // called and by the one token this design language reserves.
  //
  // One function, because there is one hazard and it is the same in three
  // places. `removeFavourite(seasonUrl, collectionUrl, lookNumber)` is
  // positional and two of its three arguments are URLs, so a triple
  // assembled out of two different rows names a row that exists, deletes
  // it, and reports success — no error, no failing build, somebody else's
  // favourite gone.
  //
  // So every argument below comes off `r`, one row, read once, in the one
  // expression that sends it. Nothing here may reach for a season, a
  // collection, a look number or a filter set by any other name.
  //
  // Saving a show and saving a look of that show are separate rows with
  // separate keys on the server — kind is part of every delete — so removing
  // one cannot touch the other.
  const handleRemove = async (favourite) => {
    const r = favourite;
    const k = kindOf(r);
    try {
      const result = k === 'show'
        ? await FashionArchiveAPI.removeShowFavourite(
          (r.season || {}).url || '', (r.collection || {}).url)
        : k === 'view'
          ? await FashionArchiveAPI.removeViewFavourite((r.view || {}).filters || {})
          : await FashionArchiveAPI.removeFavourite(
            (r.season || {}).url || '', (r.collection || {}).url, (r.look || {}).number);

      if (!result || !result.success) return;

      if (k === 'look') {
        // Land the cursor in range in the same tick as the removal, rather
        // than waiting for the passive clamp effect above to catch up a
        // render later — that one-render gap is exactly what let `current`
        // go null and unmount/remount the single-view subtree when the last
        // item was removed. React 18's automatic batching folds this
        // setSelectedIndex and the setPanes below into one render.
        const newLength = visible.length - 1;
        setSelectedIndex(i => (newLength <= 0 ? 0 : Math.min(i, newLength - 1)));
      }
      // By id, and out of that kind's pane only, so the row that goes is the
      // row that was deleted and not another row of the same designer, the
      // same season, or the same kind. `total` comes down with it: the
      // sidebar counts with the server's number, and the server has one fewer
      // now than when it last said.
      setPanes(prev => ({
        ...prev,
        [k]: {
          ...prev[k],
          rows: prev[k].rows.filter(f => f.id !== r.id),
          total: Math.max(0, prev[k].total - 1),
        },
      }));
      // A row that has just been unsaved cannot be ticked for an album.
      setPicked(prev => {
        if (!prev.has(r.id)) return prev;
        const next = new Set(prev);
        next.delete(r.id);
        return next;
      });
      // The cascade, from this side of it.
      //
      // `album_items` is ON DELETE CASCADE on the favourite, so unsaving
      // something takes it out of every album it was in — one statement, in
      // the database, and the client is never asked. What the client still
      // owes is the second reading of it: the shelf in the sidebar is
      // showing `item_count` per album, and those counts were true before
      // this delete and are not after. Without this re-read the sidebar goes
      // on claiming four items in an album that now holds three, and the
      // reader only finds out by opening it.
      reloadAlbums();
    } catch (error) {
      console.error('Error removing favourite:', error);
    }
  };

  // ── Opening, for the two kinds that are somewhere else ────────────────
  //
  // Both of these are a URL and nothing else. A saved show is a show on the
  // archive page; a saved view is the archive page with those filters
  // applied. Both are addresses the archive already understands — shareable,
  // bookmarkable, and reachable with Back — so they are written with
  // buildRoute (inside navigate) rather than handed across as state.

  const openShow = (favourite) => {
    const r = favourite;
    // `showIdOf`, which is the column the server stored, falling back to the
    // url only for a row saved before that column existed. This page used to
    // parse the url itself and the album grid did not, so one saved show
    // opened from an album tile and did nothing at all from the library tile
    // beside it — two spellings of one rule, which is the thing
    // `collection_id` was added to end.
    const id = showIdOf(r.collection);
    if (!id) return;
    navigate({
      page: 'high-fashion',
      collectionId: id,
      // Decoration only — parseRoute never reads it back. See routes.js.
      slug: slugify(
        cleanDesignerName((r.collection || {}).designer || ''),
        (r.season || {}).name
      ),
    });
  };

  const openView = (favourite) => {
    const r = favourite;
    navigate({ page: 'high-fashion', filters: (r.view || {}).filters || {} });
  };

  // An album is an address like everything else on this page. buildRoute
  // spells it /library/albums/<id>, App draws AlbumGrid for it, and Back
  // there comes straight back here.
  const openAlbum = (albumRow) => {
    navigate({ page: 'album', albumId: albumRow.id });
  };

  // What every one of this page's states puts at the top. It was the top bar
  // plus a strip of recently viewed shows; the recents now live in a drawer
  // at the foot of the High Fashion sidebar, next to the list they are a way
  // back into, so what is left here is the bar.
  const chrome = (
    <TopBar
      currentPage={currentPage}
      onPageSwitch={onPageSwitch}
      currentUser={currentUser}
      onLogout={onLogout}
    />
  );

  if (loading) {
    return (
      <div className="ar-page">
        {chrome}
        <div className="ar-loading">
          <span className="headline">Loading library</span>
        </div>
      </div>
    );
  }

  // Said as a failure, with the way out of it. The empty states below mean
  // the reader has kept nothing of that kind; this one means we never found
  // out, and the two must not be spelled the same way.
  if (panesError) {
    return (
      <div className="ar-page">
        {chrome}
        <div className="ar-empty lib-error">
          <span className="headline">Your library could not be read</span>
          <span className="lib-empty-hint">
            Nothing has been lost — this is the page failing to fetch it, not
            the library failing to hold it.
          </span>
          <span className="lib-error-detail">
            {String(panesError.message || panesError)}
          </span>
          <button
            type="button"
            className="ar-btn lib-retry"
            onClick={() => loadPanes()}
          >Try again</button>
        </div>
      </div>
    );
  }

  const spec = KINDS.find(k => k.kind === kind) || KINDS[0];
  // The server's counts, not the loaded ones. A pane shows a page of its rows
  // and its whole count, which is the only pair that is true of both: counting
  // the drawn rows would tell a reader with four hundred looks that they have
  // two hundred.
  const counts = {
    look: panes.look.total, show: panes.show.total, view: panes.view.total,
  };
  const savedTotal = counts.look + counts.show + counts.view;
  const pane = panes[kind] || EMPTY_PANE;

  // There is no page-wide "you have nothing" state any more. A reader with
  // looks and no views is not empty, and a reader with nothing at all is
  // better served by the same three panes telling them what each kind is
  // than by one line that names only one of them.
  const emptyPane = (
    <div className="ar-empty">
      <span className="headline">{spec.empty}</span>
      <span className="lib-empty-hint">{spec.hint}</span>
    </div>
  );

  const current = visible[selectedIndex] || null;

  return (
    <div className="ar-page">
      {chrome}

      <div className="ar-content">
        <div className="ar-sidebar">
          <div className="ar-section-header">
            <span>Library</span>
            <span className="count">{savedTotal}</span>
          </div>

          {/* The grouping by kind. Always all three rows, with their counts,
              so a kind a reader has none of is still visible as a thing they
              could have — clicking it is how they find out what it is. */}
          <div className="lib-kinds">
            {KINDS.map(k => (
              <div
                key={k.kind}
                className={`ar-list-item lib-kind ${k.kind === kind ? 'selected' : ''}`}
                onClick={() => handleSelectKind(k.kind)}
              >
                <span className="body">
                  <span className="name">{k.label}</span>
                </span>
                <span className="count">{counts[k.kind]}</span>
              </div>
            ))}
          </div>

          {/* The grouping the page already had. It orders looks by collection
              and nothing else, so it belongs to the looks pane and appears
              with it rather than sitting dead above the other two. */}
          {kind === 'look' && (
            <>
              <div className="fav-mode-row">
                <button
                  className={`ar-chip ${groupMode === 'view-all' ? 'selected' : ''}`}
                  onClick={() => handleGroupMode('view-all')}
                >Recent</button>
                <button
                  className={`ar-chip ${groupMode === 'by-collection' ? 'selected' : ''}`}
                  onClick={() => handleGroupMode('by-collection')}
                >By collection</button>
              </div>

              <div className="ar-section-header">
                <span>Collections</span>
                <span className="count">{collections.length}</span>
              </div>

              <div className="ar-sidebar-scroll ar-scroll">
                <div
                  className={`ar-list-item fav-collection ${effectiveSelectedKey === ALL ? 'selected' : ''}`}
                  onClick={() => handleSelectCollection(ALL)}
                >
                  <span className="num">—</span>
                  <span className="body">
                    <span className="name">All looks</span>
                    <span className="sub">{counts.look} looks</span>
                  </span>
                </div>

                {collections.map((group, idx) => (
                  <div
                    key={group.key}
                    className={`ar-list-item fav-collection ${group.key === effectiveSelectedKey ? 'selected' : ''}`}
                    onClick={() => handleSelectCollection(group.key)}
                  >
                    <span className="num">{String(idx + 1).padStart(3, '0')}</span>
                    <span className="body">
                      <span className="name">{group.designer}</span>
                      <span className="sub">{group.season} · {group.items.length}</span>
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}

          {/* The albums, at the foot of the sidebar — the same place the
              archive page puts its recents drawer, and for the same reason:
              it is a way somewhere else rather than a control over what is
              on screen, so it must not push the pane's own list around. */}
          <div className="lib-albums">
            <div className="ar-section-header">
              <span>Albums</span>
              <span className="count">{albums.length}</span>
            </div>
            <div className="lib-albums-scroll ar-scroll">
              {albums.length === 0 ? (
                <div className="lib-albums-empty">No albums yet</div>
              ) : albums.map(albumRow => (
                <div
                  key={albumRow.id}
                  className="ar-list-item lib-album"
                  onClick={() => openAlbum(albumRow)}
                >
                  <span className="body">
                    <span className="name">{albumRow.name}</span>
                  </span>
                  <span className="count">{albumRow.item_count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="fav-main">
          {kind === 'look' && (
            <div className="fav-controls">
              <div className="fav-view-toggle">
                <button
                  className={`ar-btn ${viewMode === 'single' ? 'active' : ''}`}
                  onClick={() => setViewMode('single')}
                >Single</button>
                <button
                  className={`ar-btn ${viewMode === 'grid' ? 'active' : ''}`}
                  onClick={() => setViewMode('grid')}
                >Grid</button>
              </div>
            </div>
          )}

          {/* ── Looks ────────────────────────────────────────────────── */}
          {kind === 'look' ? (
            looks.length === 0 ? emptyPane : visible.length === 0 ? (
              <div className="ar-empty">
                <span className="headline">Nothing in this collection</span>
              </div>
            ) : viewMode === 'grid' ? (
              <div className="fav-grid-container ar-scroll">
                <div className="fav-grid">
                  {visible.map((fav, idx) => (
                    <div
                      key={fav.id}
                      className={`fav-grid-item ${idx === selectedIndex ? 'selected' : ''}`}
                      onClick={() => { setSelectedIndex(idx); setViewMode('single'); }}
                    >
                      <div className="fav-grid-image">
                        <img
                          src={FashionArchiveAPI.getImageUrl(fav.image_path)}
                          alt={lookAlt(fav.look.number)}
                          loading="lazy"
                        />
                        {pickBox(fav)}
                      </div>
                      <span className="look-num">{lookLabel(fav.look.number)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : current ? (
              <div className="fav-single">
                <div className="fav-single-content">
                  {visible.length > 1 && (
                    <button className="fav-arrow prev" onClick={handlePrev}>‹</button>
                  )}

                  <div className="fav-image-side">
                    <div className="fav-image-frame">
                      <img
                        src={FashionArchiveAPI.getImageUrl(current.image_path)}
                        alt={lookAlt(current.look.number)}
                        onError={(e) => {
                          e.target.alt = 'Image not found';
                          e.target.style.background = '#f5f5f5';
                        }}
                      />
                    </div>
                    <div className="fav-image-info">
                      <span className="fav-look-label">
                        {pickBox(current)}
                        {lookLabel(current.look.number)}
                      </span>
                      <span className="fav-look-meta">
                        <span className="fav-added">
                          Added {new Date(current.date_added).toLocaleDateString()}
                        </span>
                        <button
                          className="ar-btn ar-btn-danger fav-remove"
                          onClick={() => handleRemove(current)}
                          title="Take it out of the library. It leaves every album with it."
                        >Unsave</button>
                      </span>
                    </div>
                  </div>

                  {visible.length > 1 && (
                    <button className="fav-arrow next" onClick={handleNext}>›</button>
                  )}
                </div>

                <div className="fav-thumb-strip-container">
                  <div className="fav-thumb-strip" ref={thumbStripRef}>
                    {visible.map((fav, idx) => (
                      <div
                        key={fav.id}
                        ref={idx === selectedIndex ? activeThumbRef : null}
                        className={`fav-thumb ${idx === selectedIndex ? 'active' : ''}`}
                        onClick={() => setSelectedIndex(idx)}
                      >
                        <img
                          src={FashionArchiveAPI.getImageUrl(fav.image_path)}
                          alt={lookAlt(fav.look.number)}
                          loading="lazy"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : null

          /* ── Shows ──────────────────────────────────────────────────
             A saved show is a run, not a photograph of one, so it is drawn
             as a designer and a season. Before this it came through the look
             gallery and rendered as a look with no number and no image. */
          ) : kind === 'show' ? (
            shows.length === 0 ? emptyPane : (
              <div className="lib-cards-container ar-scroll">
                <div className="lib-cards">
                  {shows.map(fav => (
                    <div key={fav.id} className="lib-show-card">
                      {pickBox(fav)}
                      <button
                        type="button"
                        className="lib-show-open"
                        onClick={() => openShow(fav)}
                        disabled={!showIdOf(fav.collection)}
                        title={showIdOf(fav.collection)
                          ? 'Open this show'
                          : 'This show has no address to open'}
                      >
                        <span className="lib-show-image">
                          {fav.image_path ? (
                            <img
                              src={FashionArchiveAPI.getImageUrl(fav.image_path)}
                              alt={cleanDesignerName((fav.collection || {}).designer || '')}
                              loading="lazy"
                            />
                          ) : null}
                        </span>
                        <span className="lib-show-name">
                          {cleanDesignerName((fav.collection || {}).designer || '')}
                        </span>
                        <span className="lib-show-season">
                          {(fav.season || {}).name || ''}
                        </span>
                      </button>
                      <button
                        className="ar-btn ar-btn-danger fav-remove"
                        onClick={() => handleRemove(fav)}
                        title="Take it out of the library. It leaves every album with it."
                      >Unsave</button>
                    </div>
                  ))}
                </div>
              </div>
            )

          /* ── Views ──────────────────────────────────────────────────
             A saved view IS its filters. Opening one is the archive page
             carrying them in the query string — an address, so it is
             shareable and Back walks out of it. */
          ) : (
            views.length === 0 ? emptyPane : (
              <div className="lib-views-container ar-scroll">
                {views.map(fav => (
                  <div key={fav.id} className="lib-view-row">
                    {pickBox(fav)}
                    <button
                      type="button"
                      className="lib-view-open"
                      onClick={() => openView(fav)}
                    >
                      <span className="lib-view-name">
                        {(fav.view || {}).name || 'Saved view'}
                      </span>
                      <span className="lib-view-filters">
                        {filterPairs((fav.view || {}).filters).length === 0 ? (
                          <span className="lib-filter">Everything</span>
                        ) : filterPairs((fav.view || {}).filters).map(([label, value]) => (
                          <span className="lib-filter" key={label}>
                            <span className="k">{label}</span>
                            <span className="v">{value}</span>
                          </span>
                        ))}
                      </span>
                    </button>
                    <button
                      className="ar-btn ar-btn-danger fav-remove"
                      onClick={() => handleRemove(fav)}
                      title="Take it out of the library. It leaves every album with it."
                    >Unsave</button>
                  </div>
                ))}
              </div>
            )
          )}

          {/* The rest of this pane.

              A control rather than a scroll listener, and deliberately. The
              looks pane is a single-image view with a thumb strip most of the
              time — there is no page scroll to hang a sentinel on — so a
              scroll trigger would have to be three different triggers for
              three different panes, two of which would fire on a strip the
              reader is arrowing through rather than on a list they are
              reading to the end of. One button, in one place, saying how many
              are left, works the same in all three.

              It says the number because "Load more" over a library of four
              hundred is a control with no end in sight; "Load 200 more of
              412" is a fact about how much is left. */}
          {pane.hasMore && (
            <div className="lib-more">
              <button
                type="button"
                className="ar-btn ar-btn-block lib-more-btn"
                onClick={() => loadMoreOf(kind)}
                disabled={pane.loadingMore}
              >
                {pane.loadingMore
                  ? 'Loading…'
                  : `Load more — ${pane.rows.length} of ${pane.total} shown`}
              </button>
            </div>
          )}

          {/* What is ticked, and the one thing to do with it. It appears only
              when something is ticked, directly above the status bar — the
              foot of the pane is where this page already puts what it is
              telling you about the pane, and a bar that is always there would
              be a permanent strip of disabled controls. */}
          {picked.size > 0 && (
            <div className="lib-select-bar">
              <span className="lib-select-count">
                {picked.size} selected
              </span>
              <span className="lib-select-acts">
                <button
                  type="button"
                  className="ar-btn lib-add-to-album"
                  onClick={() => setPickerOpen(true)}
                >Add to album</button>
                <button
                  type="button"
                  className="ar-btn lib-clear-picked"
                  onClick={() => setPicked(new Set())}
                >Clear</button>
              </span>
            </div>
          )}

          <div className="ar-status-bar">
            <span>
              {/* The server's count for the kind, which is now the pane's own
                  `total` rather than a second reading out of `stats`. Two
                  numbers for one fact is two numbers that can disagree, and
                  the pane's is the one the paging keeps current. */}
              {kind === 'look'
                ? (current
                  ? <>{current.collection.designer} / <span className="active">{current.season.name}</span></>
                  : `${counts.look} looks`)
                : kind === 'show'
                  ? `${counts.show} shows`
                  : `${counts.view} views`}
            </span>
            <span>
              {kind === 'look' && current && (
                <>
                  <span className="active">{lookLabel(current.look.number)}</span>
                  {' · '}{selectedIndex + 1} of {visible.length}
                </>
              )}
            </span>
          </div>
        </div>
      </div>

      {/* The same panel the archive page opens. One picker, so "put this in
          an album" is one act wherever the reader starts it. No `choices`
          here: what is being added is what is ticked. */}
      {pickerOpen && (
        <AlbumPicker
          albums={albums}
          heading={`${picked.size} selected`}
          onPick={addPickedToAlbum}
          onCreate={createAlbumAndAdd}
          onClose={() => setPickerOpen(false)}
          busy={albumBusy}
          error={albumsError}
        />
      )}
    </div>
  );
}

export default LibraryPage;
