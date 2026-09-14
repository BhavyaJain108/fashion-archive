import React, { useState, useEffect, useMemo, useRef } from 'react';
import TopBar from '../../shared/ui/TopBar';
import { FashionArchiveAPI } from '../../shared/api';
import { navigate } from '../../app/router';
import { slugify } from '../../app/routes';
import { cleanDesignerName } from '../../shared/lib/designerName';
import { usePersistentState } from '../../shared/hooks/usePersistentState';
import { lookLabel, lookAlt } from '../../shared/lib/lookLabel';
import {
  normalizeGroupMode, normalizeKind, normalizeViewMode,
} from '../../shared/lib/preferences';
import './LibraryPage.css';

// The sidebar's first row: every favourite, rather than one collection.
const ALL = '__all__';

// What a row is, when the row is old enough not to say. Rows saved before
// kinds existed carry no `kind` at all, and the server reads those as looks.
export const kindOf = (row) => (row && row.kind) || 'look';

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
    hint: 'A view is a set of filters — a designer, a year, a city. Narrow '
        + 'the archive down to what you want to come back to and press '
        + 'Save this view.',
  },
];

// What each filter is called on screen. The keys are FILTER_KEYS from
// routes.js; the words are the ones the archive's own facets use, so a saved
// view reads the same here as it did where it was made.
const FILTER_LABELS = {
  letter: 'Brand',
  gender: 'Gender',
  year: 'Year',
  season: 'Season',
  category: 'Type',
  shootType: 'Shoot',
  city: 'City',
};

// firstVIEW's own collection id, pulled out of the collection url it is a
// query parameter of (`…/collection_images.php?id=1234&list=all`).
//
// It is the only part of a saved show a route can be built from — see
// routes.js, where a show URL is /hf/<slug>/<collectionId> and the id is the
// only authoritative segment. A crawled row whose url carries no id is not
// openable, and this answers null rather than building /hf/<slug>/undefined.
export function collectionIdOf(collection) {
  const match = /[?&](?:id|collection)=(\d+)(?:&|$)/
    .exec(String((collection || {}).url || ''));
  return match ? match[1] : null;
}

function collectionKey(fav) {
  return `${fav.collection.designer}::${fav.season.name}`;
}

// A saved view's filters as [label, value] pairs, in the order FILTER_LABELS
// names them rather than whatever order the object arrived in — two readers
// who saved the same view must see the same line.
function filterPairs(filters) {
  const f = filters || {};
  return Object.keys(FILTER_LABELS)
    .filter(key => f[key])
    .map(key => [FILTER_LABELS[key], String(f[key])]);
}

function LibraryPage({ currentPage, onPageSwitch, currentUser, onLogout }) {
  const [favourites, setFavourites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({});

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

  const thumbStripRef = useRef(null);
  const activeThumbRef = useRef(null);

  useEffect(() => {
    loadFavourites();
    loadStats();
  }, []);

  const loadFavourites = async () => {
    try {
      setLoading(true);
      const favs = await FashionArchiveAPI.getFavourites();
      setFavourites(favs);
    } catch (error) {
      console.error('LibraryPage: Error loading favourites:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadStats = async () => {
    try {
      setStats(await FashionArchiveAPI.getFavouriteStats());
    } catch (error) {
      console.error('Error loading stats:', error);
    }
  };

  // One list per kind, off the one response. `counts` is read by the sidebar
  // rows, which must show a count for a kind that is not on screen.
  const byKind = useMemo(() => {
    const out = { look: [], show: [], view: [] };
    favourites.forEach(fav => {
      const k = kindOf(fav);
      if (out[k]) out[k].push(fav);
    });
    return out;
  }, [favourites]);

  const looks = byKind.look;
  const shows = byKind.show;
  const views = byKind.view;

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

  // ── Removal, for all three kinds ──────────────────────────────────────
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
        // setSelectedIndex and the setFavourites below into one render.
        const newLength = visible.length - 1;
        setSelectedIndex(i => (newLength <= 0 ? 0 : Math.min(i, newLength - 1)));
      }
      // By id, so the row that goes is the row that was deleted and not
      // another row of the same designer, the same season, or the same kind.
      setFavourites(prev => prev.filter(f => f.id !== r.id));
      loadStats();
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
    const id = collectionIdOf(r.collection);
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

  const spec = KINDS.find(k => k.kind === kind) || KINDS[0];
  const counts = { look: looks.length, show: shows.length, view: views.length };

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
            <span className="count">{favourites.length}</span>
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
                    <span className="sub">{looks.length} looks</span>
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
                        {lookLabel(current.look.number)}
                      </span>
                      <span className="fav-look-meta">
                        <span className="fav-added">
                          Added {new Date(current.date_added).toLocaleDateString()}
                        </span>
                        <button
                          className="ar-btn fav-remove"
                          onClick={() => handleRemove(current)}
                        >Remove</button>
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
                      <button
                        type="button"
                        className="lib-show-open"
                        onClick={() => openShow(fav)}
                        disabled={!collectionIdOf(fav.collection)}
                        title={collectionIdOf(fav.collection)
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
                        className="ar-btn fav-remove"
                        onClick={() => handleRemove(fav)}
                      >Remove</button>
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
                      className="ar-btn fav-remove"
                      onClick={() => handleRemove(fav)}
                    >Remove</button>
                  </div>
                ))}
              </div>
            )
          )}

          <div className="ar-status-bar">
            <span>
              {kind === 'look'
                ? (current
                  ? <>{current.collection.designer} / <span className="active">{current.season.name}</span></>
                  : `${stats.looks !== undefined ? stats.looks : looks.length} looks`)
                : kind === 'show'
                  ? `${stats.shows !== undefined ? stats.shows : shows.length} shows`
                  : `${stats.views !== undefined ? stats.views : views.length} views`}
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
    </div>
  );
}

export default LibraryPage;
