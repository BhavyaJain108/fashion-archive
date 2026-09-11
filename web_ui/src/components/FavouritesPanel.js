import React, { useState, useEffect, useMemo, useRef } from 'react';
import TopBar from './TopBar';
import { FashionArchiveAPI } from '../services/api';
import './FavouritesPanel.css';

// The sidebar's first row: every favourite, rather than one collection.
const ALL = '__all__';

function collectionKey(fav) {
  return `${fav.collection.designer}::${fav.season.name}`;
}

function FavouritesPanel({ currentPage, onPageSwitch, currentUser, onLogout }) {
  const [favourites, setFavourites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({});

  // Was App-level state written by the old MenuBar's View menu. It orders
  // the sidebar: RECENT by when a look was saved, BY COLLECTION by designer.
  const [groupMode, setGroupMode] = useState('view-all');
  const [selectedKey, setSelectedKey] = useState(ALL);
  const [viewMode, setViewMode] = useState('single');
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
      console.error('FavouritesPanel: Error loading favourites:', error);
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

  const collections = useMemo(() => {
    const byKey = new Map();

    favourites.forEach(fav => {
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
  }, [favourites, groupMode]);

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

    const all = [...favourites];
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
  }, [favourites, collections, effectiveSelectedKey, groupMode]);

  // Safety net only: the normal removal path (handleRemove) computes the
  // in-range index itself, in the same tick as the favourites update, so
  // this should be a no-op on that path. Kept in case some other caller
  // shrinks the list without going through handleRemove.
  useEffect(() => {
    setSelectedIndex(i => (visible.length === 0 ? 0 : Math.min(i, visible.length - 1)));
  }, [visible.length]);

  // Center the active thumbnail in the strip — same approach as
  // HighFashionV2's thumb strip, which faces the identical problem: the
  // strip's scrollbar is hidden, so without this, arrowing past the visible
  // width moves the active thumb off-screen with no visual cue that more
  // thumbs exist off to the side.
  useEffect(() => {
    if (activeThumbRef.current && thumbStripRef.current) {
      const strip = thumbStripRef.current;
      const thumb = activeThumbRef.current;
      const stripRect = strip.getBoundingClientRect();
      const thumbRect = thumb.getBoundingClientRect();

      const scrollLeft = thumb.offsetLeft - (stripRect.width / 2) + (thumbRect.width / 2);
      strip.scrollTo({ left: scrollLeft, behavior: 'smooth' });
    }
  }, [selectedIndex]);

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

  const handleRemove = async (favourite) => {
    try {
      const result = await FashionArchiveAPI.removeFavourite(
        favourite.season.url,
        favourite.collection.url,
        favourite.look.number
      );
      if (result.success) {
        // Land the cursor in range in the same tick as the removal, rather
        // than waiting for the passive clamp effect above to catch up a
        // render later — that one-render gap is exactly what let `current`
        // go null and unmount/remount the single-view subtree when the last
        // item was removed. React 18's automatic batching folds this
        // setSelectedIndex and the setFavourites below into one render.
        const newLength = visible.length - 1;
        setSelectedIndex(i => (newLength <= 0 ? 0 : Math.min(i, newLength - 1)));
        setFavourites(prev => prev.filter(f => f.id !== favourite.id));
        loadStats();
      }
    } catch (error) {
      console.error('Error removing favourite:', error);
    }
  };

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
          <span className="headline">Loading favourites</span>
        </div>
      </div>
    );
  }

  if (favourites.length === 0) {
    return (
      <div className="ar-page">
        {chrome}
        <div className="ar-empty">
          <span className="headline">No favourites</span>
          <span>Open a collection and save a look to see it here</span>
        </div>
      </div>
    );
  }

  const current = visible[selectedIndex] || null;

  return (
    <div className="ar-page">
      {chrome}

      <div className="ar-content">
        <div className="ar-sidebar">
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
                <span className="name">All favourites</span>
                <span className="sub">{favourites.length} looks</span>
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
        </div>

        <div className="fav-main">
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

          {visible.length === 0 ? (
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
                        alt={`Look ${fav.look.number}`}
                        loading="lazy"
                      />
                    </div>
                    <span className="look-num">{String(fav.look.number).padStart(2, '0')}</span>
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
                      alt={`Look ${current.look.number}`}
                      onError={(e) => {
                        e.target.alt = 'Image not found';
                        e.target.style.background = '#f5f5f5';
                      }}
                    />
                  </div>
                  <div className="fav-image-info">
                    <span className="fav-look-label">
                      LOOK {String(current.look.number).padStart(2, '0')}
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
                        alt={`Look ${fav.look.number}`}
                        loading="lazy"
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}

          <div className="ar-status-bar">
            <span>
              {current
                ? <>{current.collection.designer} / <span className="active">{current.season.name}</span></>
                : `${stats.total_favourites || favourites.length} looks`}
            </span>
            <span>
              {current && (
                <>
                  LOOK <span className="active">{String(current.look.number).padStart(2, '0')}</span>
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

export default FavouritesPanel;
