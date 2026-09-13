import React, { useState, useEffect, useCallback, useRef } from 'react';
import { FashionArchiveAPI } from '../../shared/api';
import { getRoute } from '../../app/router';
import {
  EMPTY_FILTERS, showId, showSlug, clickAction,
  initialUrlSync, deepLinkStarted, deepLinkSettled, deepLinkAbandoned,
  routeChanged, manualLook, urlWrite, lookToApply,
} from './showUrl';
import { useRoute } from '../../shared/hooks/useRoute';
import { usePersistentState } from '../../shared/hooks/usePersistentState';
import { prepare as prepareDesigners, search as searchDesigners } from '../../shared/lib/designerSearch';
import { migrateLegacySidebarOpen } from './legacySidebar';
import TopBar from '../../shared/ui/TopBar';
import Filters, { GARMENT_TYPES } from './Filters';
import ShowList from './ShowList';
import Viewer from './Viewer';
import StatusBar from './StatusBar';
import { videoSeasonName } from './seasonName';
import './HighFashionPage.css';

// Which filters the "Clear N filters" badge counts. Derived from
// EMPTY_FILTERS, which is derived from FILTER_KEYS in routes.js, so an
// eighth filter counts the day it is added rather than the day somebody
// notices this list is a stale copy.
//
// Gender is the exception: it is never empty in archive mode — it defaults
// to Women — so counting it would put the badge at 1 on a view with nothing
// chosen and make "Whole archive" unreachable.
const COUNTED_FILTER_KEYS = Object.keys(EMPTY_FILTERS).filter(k => k !== 'gender');

// The only two values Viewer branches on. A restored value that is anything
// else — an old build's spelling, a hand-edited devtools value — must not
// render a blank pane, so it falls back to the same default a first-time
// visitor gets.
export function normalizeViewMode(value) {
  return value === 'grid' ? 'grid' : 'single';
}

// Why a lookup failed, in the button and in its tooltip. These are
// different problems and only one of them is about this show.
function videoFailureLabel(result) {
  if (!result) return { label: 'NO VIDEO', detail: 'No runway video found.' };
  if (result.notConfigured) {
    return { label: 'NO API KEY',
             detail: 'The server has no YouTube API key configured, so video '
                   + 'lookup is switched off. This is a server setting, not '
                   + 'a missing video.' };
  }
  if (result.quotaExhausted) {
    return { label: 'QUOTA SPENT',
             detail: result.error || 'Today\'s YouTube quota is spent. '
                   + 'Videos already found still play; new lookups resume '
                   + 'tomorrow.' };
  }
  return { label: 'NO VIDEO', detail: result.error || 'No runway video found.' };
}

function HighFashionPage({ currentPage = 'high-fashion', onPageSwitch, onLogout, currentUser }) {
  // What the archive holds, used only to keep dead options out of the
  // filters — a year with no shows for the chosen gender is not offered.
  const [parsedSeasons, setParsedSeasons] = useState({});

  // The filter set. Everything except gender is optional and starts empty,
  // so the list opens on the whole archive instead of on an instruction to
  // choose a year, then a season, then a gender before anything appears.
  //
  // Gender is the one axis that cannot be empty: a firstVIEW query with no
  // gender does not mean "everything", it returns a 34-row bucket of shows
  // catalogued with no gender at all.
  // The URL as it was when this page mounted. Read through useState's lazy
  // initialiser, which runs exactly once — useRef's argument is eager, so
  // useRef(getRoute()) re-read the URL on every render and read as reactive
  // when the intent is mount-only.
  const [arrivedOn] = useState(getRoute);

  const [filters, setFilters] = useState(() => ({
    ...EMPTY_FILTERS,
    // Left empty once the archive is held locally — see the effect below.
    gender: 'Women',
    // The URL wins over the defaults on first load, so a shared or
    // bookmarked filtered view opens filtered rather than opening on
    // everything and correcting itself.
    ...arrivedOn.filters,
  }));

  // Whether the link that opened this page named a gender. The effect below
  // widens the default 'Women' to everything once the local index is ready;
  // a link that says gender=Men meant it, and must not be widened.
  const genderFromUrl = Boolean(arrivedOn.filters.gender);

  const [route, go] = useRoute();
  // Who may write the address bar, and which look a link is still trying to
  // reach — one value, in showUrl.js, because the interesting part is the
  // sequence of states rather than any one of them. Declared here rather
  // than beside the two effects that use it, because handleCollectionSelect
  // reads it and is defined above those.
  // The URL the page mounted on goes in with it: the first-write guard is
  // there to protect that one URL, and routeChanged below retires the guard
  // the moment the address bar stops showing it.
  const urlSync = useRef(
    initialUrlSync(window.location.pathname + window.location.search));

  // Collections state. `cursor` is where the next window starts; the list is
  // a window on 900+ pages, not a list that was ever fully fetched.
  const [collections, setCollections] = useState([]);
  const [selectedCollection, setSelectedCollection] = useState(null);
  const [collectionsLoading, setCollectionsLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [cursor, setCursor] = useState({ nextPage: 0, nextOffset: 0, hasMore: false, total: 0 });

  // Search. The index is every designer firstVIEW lists, fetched once and
  // matched in the browser — see lib/designerSearch.js for why locally.
  const [designerIndex, setDesignerIndex] = useState(null);
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [activeSuggestion, setActiveSuggestion] = useState(0);
  const [searchFocused, setSearchFocused] = useState(false);
  const [recentDesigners, setRecentDesigners] = useState([]);

  // Designer mode. A designer's shows come from a different query that
  // ignores year, season and gender entirely, so this is their whole working
  // life in one list — and the filters narrow it here rather than refetching.
  const [designerMode, setDesignerMode] = useState(null);   // {id, name}

  // Is the archive held locally? When it is, the list is a query against our
  // own rows; when it is not, it falls back to crawling firstVIEW.
  const [indexReady, setIndexReady] = useState(false);

  // The sidebar folds away, because sometimes the point is the photograph and
  // not the list. Remembered per browser: it is a working preference, not
  // something worth a round trip. `migrateLegacySidebarOpen` reads this
  // app's pre-Task-3 storage format (a bare 'open'/'closed' string at a
  // bare, non-namespaced key) so a value saved before this change still
  // opens to the sidebar state the user left it in.
  const [sidebarOpen, setSidebarOpen] = usePersistentState('sidebarOpen', migrateLegacySidebarOpen);

  const toggleSidebar = useCallback(() => {
    setSidebarOpen(open => !open);
  }, [setSidebarOpen]);
  const [serverFacets, setServerFacets] = useState(null);
  // A committed search, as opposed to what is being typed. Pressing Enter on
  // no suggestion searches the shows themselves.
  const [searchText, setSearchText] = useState('');
  const [showMatches, setShowMatches] = useState({ rows: [], total: 0 });
  // A show chosen from the dropdown, opened once its list has loaded.
  const [pendingShow, setPendingShow] = useState(null);
  const [designerRows, setDesignerRows] = useState([]);
  const [designerLoading, setDesignerLoading] = useState(false);
  const searchInputRef = useRef(null);
  // A failed request and an empty result are different answers. Showing
  // "no shows match these filters" for a dropped connection or an expired
  // session reads as an empty archive, which is the wrong thing to believe.
  const [listError, setListError] = useState(null);

  // Images state
  const [images, setImages] = useState([]);
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [imagesLoading, setImagesLoading] = useState(false);
  // Total looks reported by the stream's meta event, before files land —
  // lets the UI show "12 / 153" while the rest download.
  const [expectedLookCount, setExpectedLookCount] = useState(0);

  // In-flight streams. Clicking through years/seasons/shows faster than a
  // stream completes used to leave the old one running, so a previous
  // show's images kept landing in state after you'd selected another —
  // which looked like two different shows sharing the same pictures.
  const collectionsAbort = useRef(null);
  const imagesAbort = useRef(null);

  const abortCollections = useCallback(() => {
    if (collectionsAbort.current) collectionsAbort.current.abort();
    collectionsAbort.current = null;
  }, []);

  const abortImages = useCallback(() => {
    if (imagesAbort.current) imagesAbort.current.abort();
    imagesAbort.current = null;
    // Clear the flag here rather than in the aborted request's finally: that
    // guards on isCurrent(), which is false exactly because we just aborted,
    // so the flag stayed true forever and every later click was ignored.
    setImagesLoading(false);
    setExpectedLookCount(0);
  }, []);

  // Drop any in-flight work when the component goes away.
  useEffect(() => () => {
    if (collectionsAbort.current) collectionsAbort.current.abort();
    if (imagesAbort.current) imagesAbort.current.abort();
  }, []);

  // Anything a stored value could hold that isn't one of these two branches
  // Viewer actually renders would produce a blank pane, so restored values
  // are validated against the set the component handles rather than trusted.
  const [viewMode, setViewMode] = usePersistentState('hf-view-mode', 'single', {
    deserialize: (raw) => normalizeViewMode(JSON.parse(raw)),
  }); // 'single' or 'grid'

  // Video state
  const [videoData, setVideoData] = useState(null);
  const [videoState, setVideoState] = useState('idle'); // 'idle', 'loading', 'ready', 'error'
  // Why a lookup failed. "No video for this show" and "the server has no
  // YouTube key" are different problems, and collapsing both into NOT FOUND
  // is what made a missing key in production look like an empty archive.
  const [videoError, setVideoError] = useState(null);
  const [showVideo, setShowVideo] = useState(false);
  const [videoHeight, setVideoHeight] = useState(300);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // Refs
  const thumbStripRef = useRef(null);
  const activeThumbRef = useRef(null);
  const playerRef = useRef(null);
  const playerContainerRef = useRef(null);
  const timeUpdateRef = useRef(null);

  // Build hierarchy from seasons: year -> season -> gender -> season object.
  //
  // /api/seasons returns year, season and gender as separate fields, so
  // there is nothing to parse out of the label. The old string-sniffing
  // version dropped every pre-2000 year, collapsed Prefall into Fall,
  // discarded Cruise, and matched "Women" on the substring "men".
  const buildHierarchy = useCallback((seasons) => {
    const hierarchy = {};
    seasons.forEach(season => {
      const { year, season: seasonType, gender } = season;
      if (!year || !seasonType || !gender) return;

      if (!hierarchy[year]) hierarchy[year] = {};
      if (!hierarchy[year][seasonType]) hierarchy[year][seasonType] = {};
      hierarchy[year][seasonType][gender] = season;
    });
    return hierarchy;
  }, []);

  // Load seasons on mount
  useEffect(() => {
    const loadSeasons = async () => {
      try {
        const seasons = await FashionArchiveAPI.getSeasons();
        const hierarchy = buildHierarchy(seasons);
        setParsedSeasons(hierarchy);
      } catch (error) {
        console.error('Failed to load seasons:', error);
      }
    };
    loadSeasons();
  }, [buildHierarchy]);

  // Extract look number from filename
  const extractLookNumber = (path, fallbackIdx) => {
    const filename = path.split('/').pop() || '';
    const match = filename.match(/-(\d+)\./);
    return match ? parseInt(match[1]) : fallbackIdx + 1;
  };

  useEffect(() => {
    FashionArchiveAPI.getIndexStatus().then(status => {
      const ready = (status?.shows || 0) > 0;
      setIndexReady(ready);
      // Gender was only ever required because firstVIEW cannot answer a
      // query without one. Our own rows can, so the archive opens on
      // everything rather than on half of it.
      if (ready && !genderFromUrl) setFilters(prev => ({ ...prev, gender: '' }));
    });
  }, [genderFromUrl]);

  // The designer index, once. Failure is not fatal — the archive still
  // browses, the search box just says it cannot search.
  useEffect(() => {
    let cancelled = false;
    FashionArchiveAPI.getDesigners().then(designers => {
      if (cancelled) return;
      setDesignerIndex(designers ? prepareDesigners(designers) : null);
    });
    return () => { cancelled = true; };
  }, []);

  // Designers you have actually opened, offered when the box is empty. Taken
  // from the recents table rather than from what you have typed, so it
  // reflects where you have been rather than what you searched for and
  // abandoned.
  useEffect(() => {
    if (!designerIndex) return;
    let cancelled = false;
    FashionArchiveAPI.getRecents().then(rows => {
      if (cancelled) return;
      const byName = new Map(designerIndex.map(d => [d._n, d]));
      const out = [];
      const seen = new Set();
      for (const row of rows || []) {
        const match = byName.get(
          (row.designer || '').toLowerCase().normalize('NFD')
            .replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9 ]/g, ' ')
            .replace(/\s+/g, ' ').trim());
        if (!match || seen.has(match.id)) continue;
        seen.add(match.id);
        out.push(match);
        if (out.length >= 6) break;
      }
      setRecentDesigners(out);
    });
    return () => { cancelled = true; };
  }, [designerIndex]);

  useEffect(() => {
    if (!designerIndex) { setSuggestions([]); return; }
    setSuggestions(query.trim() ? searchDesigners(designerIndex, query, 8) : []);
    setActiveSuggestion(0);
  }, [query, designerIndex]);

  const openDesigner = useCallback((designer) => {
    if (!designer) return;
    abortCollections();
    abortImages();
    setDesignerMode({ id: designer.id, name: designer.name });
    setDesignerRows([]);
    setQuery('');
    setSuggestions([]);
    setSearchFocused(false);
    if (searchInputRef.current) searchInputRef.current.blur();
    setSelectedCollection(null);
    setCollections([]);
    setImages([]);
    setExpectedLookCount(0);
    // Their whole history is in hand, so gender stops being a required
    // choice here and starts as "all" — showing half a designer's work by
    // default would be a strange way to answer "show me everything they did".
    setFilters(prev => ({ ...prev, gender: '', letter: '' }));
  }, [abortCollections, abortImages]);

  const exitDesigner = useCallback(() => {
    abortCollections();
    abortImages();
    setDesignerMode(null);
    setSearchText('');
    setDesignerRows([]);
    setSelectedCollection(null);
    setCollections([]);
    setImages([]);
    setExpectedLookCount(0);
    // The catalog has no "all genders" — a query without one returns a small
    // bucket of ungendered shows — so it has to become a real choice again.
    setFilters(prev => ({ ...prev, gender: prev.gender || 'Women' }));
  }, [abortCollections, abortImages]);

  // Shows whose text matches what is being typed. Only possible because the
  // archive is held locally: firstVIEW can search designer names and nothing
  // else, so "chanel fw25" had no query to be.
  useEffect(() => {
    if (!indexReady || !query.trim()) { setShowMatches({ rows: [], total: 0 }); return; }
    let cancelled = false;
    // Debounced: typing is faster than a round trip, and every keystroke
    // firing a query would just queue responses that arrive out of order.
    const timer = setTimeout(() => {
      FashionArchiveAPI.searchShows(query, { limit: 6 }).then(result => {
        if (cancelled || !result?.success) return;
        setShowMatches({ rows: result.shows || [], total: result.total || 0 });
      }).catch(() => {});
    }, 140);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [query, indexReady]);

  // One list for the keyboard to walk: designers first, because picking one
  // opens their whole history, then the shows that matched, then a way to
  // see every match rather than the first six.
  const suggestionList = (() => {
    if (!query.trim()) {
      return recentDesigners.map(d => ({ kind: 'designer', designer: d, key: `d${d.id}` }));
    }
    const out = suggestions.slice(0, 4)
      .map(d => ({ kind: 'designer', designer: d, key: `d${d.id}` }));
    for (const row of showMatches.rows) {
      out.push({ kind: 'show', show: row, key: `s${row.collection_id}` });
    }
    if (showMatches.total > showMatches.rows.length) {
      out.push({ kind: 'all', key: 'all', total: showMatches.total });
    }
    return out;
  })();

  const chooseSuggestion = useCallback((item) => {
    if (!item) return;
    if (item.kind === 'designer') { openDesigner(item.designer); return; }

    // A show or "everything that matched": both leave designer mode, since
    // the results are no longer one designer's.
    setDesignerMode(null);
    setSearchText(query);
    setQuery('');
    setSuggestions([]);
    setSearchFocused(false);
    if (searchInputRef.current) searchInputRef.current.blur();
    if (item.kind === 'show') setPendingShow(item.show);
  }, [query, openDesigner]);

  const handleSearchKeyDown = (e) => {
    const options = suggestionList;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveSuggestion(i => Math.min(options.length - 1, i + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveSuggestion(i => Math.max(0, i - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      chooseSuggestion(options[activeSuggestion]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      if (query) setQuery('');
      else if (designerMode || searchText) exitDesigner();
      else e.currentTarget.blur();
    }
  };

  // Changing any filter restarts the list from the top. Filters are
  // additive: setting one narrows the query, clearing it widens it again,
  // and none of them is a prerequisite for any other.
  const setFilter = (key, value) => {
    abortCollections();
    abortImages();
    setFilters(prev => {
      const next = { ...prev, [key]: value };
      // Season is the only pair with a real dependency: a year that has no
      // Cruise show should not stay stuck on Cruise when you switch to it.
      if (key === 'year' && value && next.season) {
        const has = parsedSeasons[value]?.[next.season]?.[next.gender]?.available;
        if (has === false) next.season = '';
      }
      return next;
    });
    setSelectedCollection(null);
    setCollections([]);
    setImages([]);
    setExpectedLookCount(0);
  };

  const clearFilters = () => {
    abortCollections();
    abortImages();
    setFilters(prev => ({ ...EMPTY_FILTERS, gender: prev.gender }));
    setSelectedCollection(null);
    setCollections([]);
    setImages([]);
    setExpectedLookCount(0);
  };

  // How the list is loaded depends on whether the archive is held locally.
  //
  //   indexed  — one query against our own 55,700 rows. Instant, exact, and
  //              firstVIEW is not contacted at all.
  //   crawling — the old streaming crawl of their results pages, kept as the
  //              fallback so a database without the index is slow rather
  //              than empty.
  //
  // Indexed, the three things the list can show — the whole archive, one
  // designer's history, a search — stop being three mechanisms and become
  // one query with different arguments.
  useEffect(() => {
    if (!indexReady) return;

    const controller = new AbortController();
    collectionsAbort.current = controller;
    let cancelled = false;
    const isCurrent = () => !cancelled && collectionsAbort.current === controller;

    setCollectionsLoading(true);
    setListError(null);

    (async () => {
      try {
        const result = await FashionArchiveAPI.browseCatalog(
          { ...filters, designer: designerMode ? designerMode.name : undefined },
          { text: searchText || undefined, offset: 0, facets: true },
        );
        if (!isCurrent()) return;
        if (!result.success) throw new Error(result.error || 'Search failed');
        setCollections(result.collections || []);
        setServerFacets(result.facets || null);
        setCursor({ nextOffset: (result.collections || []).length,
                    hasMore: !!result.hasMore, total: result.total || 0 });
      } catch (error) {
        if (error.name === 'AbortError' || cancelled) return;
        console.error('Failed to load collections:', error);
        setCollections([]);
        setListError(error.message || 'Could not reach the archive');
      } finally {
        if (isCurrent()) setCollectionsLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [indexReady, filters, designerMode, searchText]);

  // One designer's shows, streamed — the fallback path only. With the index
  // a designer is just another filter on the query above.
  useEffect(() => {
    if (indexReady || !designerMode) return;

    const controller = new AbortController();
    collectionsAbort.current = controller;
    let cancelled = false;
    const isCurrent = () => !cancelled && collectionsAbort.current === controller;

    setDesignerLoading(true);
    (async () => {
      try {
        await FashionArchiveAPI.streamDesignerCollections(designerMode.id, {
          signal: controller.signal,
          onUpdate: ({ rows }) => { if (isCurrent()) setDesignerRows(rows); },
        });
      } catch (error) {
        if (error.name === 'AbortError' || cancelled) return;
        console.error('Failed to load designer:', error);
        setListError(error.message || 'Could not reach the archive');
      } finally {
        if (isCurrent()) setDesignerLoading(false);
      }
    })();

    return () => { cancelled = true; controller.abort(); };
  }, [indexReady, designerMode]);

  // The streaming crawl of firstVIEW — the fallback when the archive is not
  // held locally.
  useEffect(() => {
    if (indexReady || designerMode) return;

    const controller = new AbortController();
    collectionsAbort.current = controller;
    let cancelled = false;
    const isCurrent = () => !cancelled && collectionsAbort.current === controller;

    setCollectionsLoading(true);
    setCursor({ nextPage: 0, hasMore: false });
    setListError(null);

    (async () => {
      try {
        const result = await FashionArchiveAPI.streamCatalog(filters, {
          startPage: 0,
          signal: controller.signal,
          onUpdate: ({ rows }) => {
            if (!isCurrent()) return;
            setCollections(rows);
            setCollectionsLoading(false);
          },
        });
        if (isCurrent()) {
          setCursor({ nextPage: result.nextPage, hasMore: result.hasMore });
        }
      } catch (error) {
        if (error.name === 'AbortError' || cancelled) return;
        console.error('Failed to load collections:', error);
        setCollections([]);
        setListError(error.message || 'Could not reach the archive');
      } finally {
        if (isCurrent()) setCollectionsLoading(false);
      }
    })();

    return () => { cancelled = true; controller.abort(); };
  }, [indexReady, filters, designerMode]);

  // The next page. Indexed, that is an offset; crawling, it is the next
  // window of results pages.
  const loadMore = useCallback(async () => {
    if (loadingMore || collectionsLoading || !cursor.hasMore) return;

    if (indexReady) {
      setLoadingMore(true);
      try {
        const result = await FashionArchiveAPI.browseCatalog(
          { ...filters, designer: designerMode ? designerMode.name : undefined },
          { text: searchText || undefined, offset: cursor.nextOffset },
        );
        if (!result.success) return;
        setCollections(prev => {
          const seen = new Set(prev.map(r => r.collection_id));
          return [...prev, ...(result.collections || [])
            .filter(r => !seen.has(r.collection_id))];
        });
        setCursor(c => ({ ...c,
          nextOffset: c.nextOffset + (result.collections || []).length,
          hasMore: !!result.hasMore }));
      } catch (error) {
        console.error('Failed to load more:', error);
      } finally {
        setLoadingMore(false);
      }
      return;
    }

    if (designerMode) return;      // their whole history is already loaded
    const controller = collectionsAbort.current;
    setLoadingMore(true);
    try {
      const result = await FashionArchiveAPI.streamCatalog(filters, {
        startPage: cursor.nextPage,
        signal: controller ? controller.signal : undefined,
        onUpdate: ({ rows }) => {
          if (collectionsAbort.current !== controller) return;
          setCollections(prev => {
            const seen = new Set(prev.map(r => r.collection_id));
            return [...prev, ...rows.filter(r => !seen.has(r.collection_id))];
          });
        },
      });
      if (collectionsAbort.current === controller) {
        setCursor({ nextPage: result.nextPage, hasMore: result.hasMore });
      }
    } catch (error) {
      if (error.name !== 'AbortError') console.error('Failed to load more:', error);
    } finally {
      setLoadingMore(false);
    }
  }, [indexReady, filters, designerMode, searchText, cursor, loadingMore, collectionsLoading]);

  const handleListScroll = (e) => {
    const el = e.currentTarget;
    // 400px of runway, so the next page is usually already in by the time
    // the reader reaches the bottom.
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 400) loadMore();
  };


  // A show chosen from the search dropdown. Done in an effect rather than in
  // the click handler so it runs after the list has been replaced, and the
  // row it selects is the row the list is showing.
  useEffect(() => {
    if (!pendingShow) return;
    handleCollectionSelect(pendingShow);
    setPendingShow(null);
    // Deliberately only pendingShow: this fires on the pick, and
    // handleCollectionSelect is a new function every render, so listing it
    // would refire this effect forever.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingShow]);

  // `fromUrl` marks a show opened because the address bar already named it —
  // on first load, or on Back/Forward. That is a navigation the user has
  // already made, so it must not push a second history entry for it.
  const handleCollectionSelect = async (collection, { fromUrl = false } = {}) => {
    // pending: the show a deep link is already fetching. Clicking that row
    // is asking for the navigation already in progress, so it must not push
    // over the URL that started it. hasImages/imagesLoading separate "this
    // show is open and read" from "this show is open and the stream gave it
    // nothing" — the second is a retry, and re-clicking the row is the only
    // retry this page has ever had.
    const action = clickAction({
      clicked: collection,
      open: selectedCollection,
      pendingId: urlSync.current.pending,
      hasImages: images.length > 0,
      imagesLoading,
      fromUrl,
    });

    // Already the show on screen, or the show a link is still fetching.
    // Not a navigation, so: no history entry — a push of /hf/x/1 while
    // standing on /hf/x/1/7 left an entry Back could reach without changing
    // anything visible, and Back needed pressing twice — and no reset of the
    // viewer either. Clicking the row you are reading should not throw away
    // look 7 and refetch the whole stream.
    if (action === 'ignore') return;

    setSelectedCollection(collection);
    setImages([]);
    setCurrentImageIndex(0);
    setImagesLoading(true);

    if (action === 'open' || action === 'reload') {
      // A show chosen by hand supersedes any look a link was still waiting
      // to reach. A retry does not: it is the same entry being loaded again,
      // so the look it asked for is still the look the reader wants.
      if (action === 'open') urlSync.current = manualLook(urlSync.current);
      const id = showId(collection);
      // The one push in this page. Opening a show is a place you can come
      // back from; moving between looks is not, so every other write to the
      // address bar here replaces. That is what makes Back leave the show
      // rather than walk backwards through forty photographs. A reload
      // replaces for the same reason: the reader is standing on this entry
      // already, and a second copy of it in the history would be an entry
      // Back could reach without changing the screen.
      if (id) {
        go({
          page: 'high-fashion',
          slug: showSlug(collection),
          collectionId: id,
          filters,
        }, { replace: action === 'reload' });
      }
    }

    // Reset video state for new collection
    setVideoData(null);
    setVideoState('idle');
    setVideoError(null);
    setShowVideo(false);

    // NB: no cleanupDownloads() here — it rmtree'd the whole cache, so every
    // click re-downloaded shows that were already on disk.
    abortImages();
    const controller = new AbortController();
    imagesAbort.current = controller;
    const isCurrent = () => imagesAbort.current === controller;

    try {
      const paths = [];
      await FashionArchiveAPI.streamCollectionImages(collection.url, {
        signal: controller.signal,
        onMeta: (meta) => { if (isCurrent()) setExpectedLookCount(meta.count); },
        onImage: (img) => {
          // Images arrive in completion order; keep them in look order.
          if (!isCurrent()) return;
          paths[img.index] = img.path;
          setImages(paths.filter(Boolean));
          setImagesLoading(false);   // first image ends the spinner
        },
      });
    } catch (error) {
      if (error.name === 'AbortError') return;   // superseded by a newer click
      console.error('Failed to load images:', error);
      if (isCurrent()) setImages([]);
    } finally {
      if (isCurrent()) setImagesLoading(false);
    }
  };

  // ── The address bar ────────────────────────────────────────────────────
  //
  // Two effects pointing in opposite directions. They do not chase each
  // other because each has its own reason to stop:
  //
  //   URL → state stops when the id in the URL is already the show that is
  //   open. Every URL the second effect writes names the open show, so it
  //   can never re-open anything.
  //
  //   state → URL stops while a deep link is still being resolved. That is
  //   the one moment the URL is ahead of the state rather than behind it:
  //   on the first render of /hf/gucci/1234 nothing is open yet, and an
  //   unguarded write would replace the address bar with "/" and throw the
  //   link away before the fetch that resolves it came back.
  //
  //   That guard is spent the moment the deep link settles, with a row or
  //   without one — see deepLinkSettled in showUrl.js. It used to be left
  //   standing after a dead deep link, and the next unrelated write was
  //   quietly eaten in its place.
  //
  // Underneath both, navigate() refuses to push or notify when handed the
  // URL already shown, so a repeated write costs nothing and adds no history.
  // The bookkeeping the two of them share lives in showUrl.js, where the
  // sequences can be tested without a browser.

  // The address bar has left the URL the page mounted on, so the first-write
  // guard has done its job and is retired. Declared before both effects
  // below so that it runs first: state → URL must not read a guard that this
  // same commit should already have spent.
  //
  // The sequence this closes: arrive on /hf/x/1234/12, press Back to / before
  // the row fetch returns. URL → state's cleanup clears `pending` and its
  // re-run returns at !wanted; state → URL's deps never changed, so nothing
  // ever spent the guard, and the user's next filter change was swallowed by
  // it. `route` is a stable reference while the URL is unchanged — router.js
  // caches it — so this runs once per real navigation.
  useEffect(() => {
    urlSync.current = routeChanged(urlSync.current, {
      path: window.location.pathname + window.location.search,
    });
  }, [route]);

  // URL → state. First load, and Back/Forward.
  useEffect(() => {
    const wanted = route.collectionId;

    if (!wanted) {
      // The URL no longer names a show, so nothing should be open — this is
      // what makes Back leave the viewer instead of changing the address bar
      // and leaving the photographs on screen. Only a show that was itself
      // addressable is closed this way: a row with no usable id was never
      // written to the URL, so its absence there is not the user going back.
      if (selectedCollection && showId(selectedCollection)) {
        abortImages();
        setSelectedCollection(null);
        setImages([]);
        setExpectedLookCount(0);
      }
      return;
    }

    if (selectedCollection && showId(selectedCollection) === wanted) return;

    let cancelled = false;
    urlSync.current = deepLinkStarted(urlSync.current, {
      collectionId: wanted, imageNumber: route.imageNumber,
    });
    FashionArchiveAPI.browseCatalog({}, { limit: 1, collectionId: wanted })
      .then((res) => {
        if (cancelled) return;
        const col = (res?.collections || res?.rows || [])[0];
        // Settled either way, and that retires the first-write guard: it only
        // ever protected the URL the user arrived on, and this was that URL's
        // one chance. Leaving it standing on the no-row path is what made the
        // user's next filter change write nothing at all.
        urlSync.current = deepLinkSettled(urlSync.current, { found: Boolean(col) });
        // An id that names nothing leaves the archive on screen. There is no
        // show to open, and a 404 page for a mistyped number would be a
        // worse answer than the list.
        if (col) handleCollectionSelect(col, { fromUrl: true });
      })
      .catch((error) => {
        if (!cancelled) {
          urlSync.current = deepLinkSettled(urlSync.current, { found: false });
        }
        console.error('Could not open the show in the URL:', error);
      });

    return () => {
      cancelled = true;
      urlSync.current = deepLinkAbandoned(urlSync.current);
    };
    // Deliberately only the id. selectedCollection is read above but is not
    // a dependency: this effect answers "the URL changed", and re-running it
    // when a show opens is exactly the re-entry the guard exists to avoid.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.collectionId]);

  // state → URL. The address bar follows the viewer.
  useEffect(() => {
    // 'none' while a deep link is in flight, and on the very first
    // no-selection render: the URL as it arrived is not something to
    // correct, only a change made here is worth writing. 'show' carries the
    // look a link asked for until that look is reached, so /hf/x/1/12 does
    // not dip through /hf/x/1 and lose the shared look if the stream fails.
    const decided = urlWrite(urlSync.current, {
      hasSelection: Boolean(selectedCollection),
      imagesLength: images.length,
      currentIndex: currentImageIndex,
    });
    urlSync.current = decided.state;

    if (decided.target === 'none') return;

    if (decided.target === 'archive') {
      // The archive, carrying its filters so a filtered view is a link
      // somebody can send.
      go({ page: 'high-fashion', filters }, { replace: true });
      return;
    }

    const id = showId(selectedCollection);
    // Not addressable, so there is no URL to write. Leaving the address bar
    // alone is right here: writing "/" would make the effect above read it
    // back as "no show open" and close the show that is on screen.
    if (!id) return;

    go({
      page: 'high-fashion',
      slug: showSlug(selectedCollection),
      collectionId: id,
      // 1-based: the first look is /1. Null until a look is known, so the
      // URL never claims one that nothing has asked for.
      imageNumber: decided.imageNumber,
      filters,
    }, { replace: true });
    // images.length rather than images: the array identity changes on every
    // image that lands, and the URL only cares whether there is one.
  }, [selectedCollection, currentImageIndex, images.length, filters, go]);

  // The look a deep link named, applied once it has actually arrived.
  // Images stream in one at a time, so images.length grows: settling on the
  // first render would put a link to look 12 on look 1. expectedLookCount
  // comes from the stream's meta event and is how a link to look 200 of a
  // 40-look show knows to stop at 40 rather than wait forever.
  useEffect(() => {
    const { state, index } = lookToApply(urlSync.current, {
      imagesLength: images.length,
      expectedLookCount,
    });
    urlSync.current = state;
    // setCurrentImageIndex directly, not showLook: this is the link's own
    // look arriving, not a look chosen by hand.
    if (index !== null) setCurrentImageIndex(index);
  }, [images.length, expectedLookCount]);

  // Search for video
  const handleVideoSearch = async () => {
    if (!selectedCollection || videoState === 'loading') return;

    setVideoState('loading');
    setVideoError(null);
    try {
      const result = await FashionArchiveAPI.downloadVideo(
        selectedCollection.designer_name || selectedCollection.designer,
        videoSeasonName(selectedCollection),
        selectedCollection.gender || ''
      );
      if (result && result.embedUrl) {
        setVideoData(result);
        setVideoState('ready');
        setShowVideo(true);
      } else {
        setVideoError(videoFailureLabel(result));
        setVideoState('error');
      }
    } catch (error) {
      console.error('Failed to find video:', error);
      setVideoError({ label: 'LOOKUP FAILED', detail: String(error.message || error) });
      setVideoState('error');
    }
  };

  // Which looks this user has kept.
  //
  // Held as a set of "collection url|look number", loaded once, because the
  // question is asked of every thumbnail on screen — a request per look to
  // answer "is this one favourited" would be hundreds of requests to draw a
  // strip. Favourites are per user by construction: the endpoint reads the
  // session, so there is no user id to pass and no way to see anyone else's.
  const [favouriteKeys, setFavouriteKeys] = useState(() => new Set());
  const [favouriteBusy, setFavouriteBusy] = useState(false);

  const favouriteKey = (collectionUrl, lookNumber) => `${collectionUrl}|${lookNumber}`;

  const loadFavourites = useCallback(async () => {
    const rows = await FashionArchiveAPI.getFavourites();
    // The list endpoint nests these — collection.url and look.number, not the
    // flat column names the write side takes. Reading the flat names produced
    // "undefined|undefined" for every key, so nothing was ever marked as kept
    // after a reload while the writes themselves looked fine.
    setFavouriteKeys(new Set(
      (rows || [])
        .map(f => favouriteKey(f.collection?.url, f.look?.number))
        .filter(k => !k.startsWith('undefined'))));
  }, []);

  useEffect(() => { loadFavourites(); }, [loadFavourites]);

  const isFavourite = (lookNumber) =>
    !!selectedCollection
    && favouriteKeys.has(favouriteKey(selectedCollection.url, lookNumber));

  const toggleFavourite = useCallback(async (lookNumber, imagePath) => {
    if (!selectedCollection || favouriteBusy) return;
    const key = favouriteKey(selectedCollection.url, lookNumber);
    const had = favouriteKeys.has(key);

    // Move the marker first: keeping a look should feel instantaneous, and
    // the request is undone below if it turns out not to have worked.
    setFavouriteKeys(prev => {
      const next = new Set(prev);
      if (had) next.delete(key); else next.add(key);
      return next;
    });
    setFavouriteBusy(true);

    try {
      if (had) {
        await FashionArchiveAPI.removeFavourite(
          selectedCollection.season_url || '', selectedCollection.url, lookNumber);
      } else {
        await FashionArchiveAPI.addFavourite(
          {
            name: videoSeasonName(selectedCollection),
            url: selectedCollection.season_url || '',
            link_text: selectedCollection.subtitle || '',
          },
          {
            designer: selectedCollection.designer_name || selectedCollection.designer,
            url: selectedCollection.url,
          },
          { number: lookNumber, total: images.length },
          imagePath,
        );
      }
    } catch (error) {
      console.error('Could not change favourite:', error);
      setFavouriteKeys(prev => {          // put it back the way it was
        const next = new Set(prev);
        if (had) next.add(key); else next.delete(key);
        return next;
      });
    } finally {
      setFavouriteBusy(false);
    }
  }, [selectedCollection, favouriteKeys, favouriteBusy, images.length]);

  // Every look the reader chooses themselves goes through here — the arrows,
  // the thumbnail strip, the grid. It cancels any look a deep link was still
  // waiting to reach: without that, arrowing while /hf/x/1/12 loads yanks
  // them to look 12 the moment the twelfth image lands.
  const showLook = useCallback((next) => {
    urlSync.current = manualLook(urlSync.current);
    setCurrentImageIndex(next);
  }, []);

  // Navigation (no wraparound)
  const prevImage = useCallback(() => {
    if (images.length === 0) return;
    showLook((prev) => Math.max(0, prev - 1));
  }, [images.length, showLook]);

  const nextImage = useCallback(() => {
    if (images.length === 0) return;
    showLook((prev) => Math.min(images.length - 1, prev + 1));
  }, [images.length, showLook]);

  const selectImageFromGrid = (idx) => {
    showLook(idx);
    setViewMode('single');
  };

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Not while typing: 'g' in the search box used to toggle grid view, and
      // the arrows used to walk the looks instead of the suggestions.
      const el = e.target;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'
                 || el.tagName === 'SELECT' || el.isContentEditable)) return;
      if (e.key === '[') { toggleSidebar(); return; }
      if (images.length === 0) return;
      if (e.key === 'f' || e.key === 'F') {
        // Derived here rather than read from the render scope: this effect is
        // declared long before currentLookNumber is, and naming it in the
        // dependency array below would read it during render, before it
        // exists.
        const path = images[currentImageIndex];
        if (path) toggleFavourite(extractLookNumber(path, currentImageIndex), path);
        return;
      }
      if (e.key === 'ArrowLeft') prevImage();
      else if (e.key === 'ArrowRight') nextImage();
      else if (e.key === 'g') setViewMode(v => v === 'grid' ? 'single' : 'grid');
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [images, currentImageIndex, prevImage, nextImage, toggleSidebar, toggleFavourite, setViewMode]);

  // Center active thumbnail in strip
  useEffect(() => {
    if (activeThumbRef.current && thumbStripRef.current) {
      const strip = thumbStripRef.current;
      const thumb = activeThumbRef.current;
      const stripRect = strip.getBoundingClientRect();
      const thumbRect = thumb.getBoundingClientRect();

      const scrollLeft = thumb.offsetLeft - (stripRect.width / 2) + (thumbRect.width / 2);
      strip.scrollTo({ left: scrollLeft, behavior: 'smooth' });
    }
  }, [currentImageIndex]);

  // Load YouTube API
  useEffect(() => {
    if (!window.YT) {
      const tag = document.createElement('script');
      tag.src = 'https://www.youtube.com/iframe_api';
      const firstScript = document.getElementsByTagName('script')[0];
      firstScript.parentNode.insertBefore(tag, firstScript);
    }
  }, []);

  // Captions off, and kept off.
  //
  // cc_load_policy: 0 is not a way to force them off — only 1 is documented,
  // to force them on — so a viewer whose account has captions enabled gets
  // them burned over the runway regardless. Dropping the module is the part
  // that actually works, and it has to be repeated on play because the track
  // is chosen when playback starts.
  const silenceCaptions = (player) => {
    for (const module of ['captions', 'cc']) {
      try { player.unloadModule(module); } catch (e) { /* not loaded yet */ }
    }
  };

  // Ask for the best the video has.
  //
  // Whether YouTube listens is another matter: setPlaybackQuality is
  // deprecated and their player picks its own rate. Probing it here, a video
  // offering hd2160 sat at medium and would not move. So this asks, because
  // asking is free, and the read-out below reports what actually came back
  // rather than what we asked for.
  const requestBestQuality = (player) => {
    try {
      const levels = player.getAvailableQualityLevels?.() || [];
      const best = levels.find(l => l !== 'auto');
      if (best) player.setPlaybackQuality(best);
    } catch (e) { /* the API has been known to drop this entirely */ }
  };

  // Initialize YouTube player when video data changes
  useEffect(() => {
    if (!videoData || !showVideo || !playerContainerRef.current) return;

    const initPlayer = () => {
      if (playerRef.current) {
        playerRef.current.destroy();
      }

      playerRef.current = new window.YT.Player(playerContainerRef.current, {
        videoId: videoData.videoId,
        playerVars: {
          controls: 0,          // our controls, below
          modestbranding: 1,
          rel: 0,               // end screen stays on the same channel
          fs: 0,
          iv_load_policy: 3,    // no annotation cards
          disablekb: 1,
          playsinline: 1,
          cc_load_policy: 0,
          origin: window.location.origin,
          // No `vq` here. It is not a playerVar — it does nothing on the
          // embed — and what it expressed was a cap at 720p, which is the
          // opposite of what this should ask for.
        },
        events: {
          onReady: (e) => {
            setDuration(e.getDuration ? e.getDuration() : e.target.getDuration());
            silenceCaptions(e.target);
            requestBestQuality(e.target);
            setVideoQuality(e.target.getPlaybackQuality?.() || 'auto');
            e.target.pauseVideo();
          },
          onStateChange: (e) => {
            setIsPlaying(e.data === window.YT.PlayerState.PLAYING);
            if (e.data === window.YT.PlayerState.PLAYING) {
              // Both again on play: the caption track is chosen when
              // playback starts, so switching it off before then is too
              // early, and quality levels only exist once it has begun.
              silenceCaptions(e.target);
              requestBestQuality(e.target);
              setVideoQuality(e.target.getPlaybackQuality?.() || 'auto');
            }
            if (e.data === window.YT.PlayerState.ENDED) {
              // Park on the first frame rather than let the end screen and
              // its grid of thumbnails take over the panel.
              e.target.seekTo(0, true);
              e.target.pauseVideo();
            }
          },
          onPlaybackQualityChange: (e) => {
            setVideoQuality(e.target.getPlaybackQuality?.() || 'auto');
          },
        },
      });
    };

    if (window.YT && window.YT.Player) {
      initPlayer();
    } else {
      window.onYouTubeIframeAPIReady = initPlayer;
    }

    return () => {
      if (playerRef.current) {
        playerRef.current.destroy();
        playerRef.current = null;
      }
    };
  }, [videoData, showVideo]);

  // Update current time
  useEffect(() => {
    if (isPlaying) {
      timeUpdateRef.current = setInterval(() => {
        if (playerRef.current && playerRef.current.getCurrentTime) {
          setCurrentTime(playerRef.current.getCurrentTime());
        }
      }, 250);
    } else {
      clearInterval(timeUpdateRef.current);
    }
    return () => clearInterval(timeUpdateRef.current);
  }, [isPlaying]);

  // Video controls
  const togglePlay = () => {
    if (!playerRef.current) return;
    if (isPlaying) {
      playerRef.current.pauseVideo();
    } else {
      playerRef.current.playVideo();
    }
  };

  const seekTo = (e) => {
    if (!playerRef.current || !duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const percent = (e.clientX - rect.left) / rect.width;
    const time = percent * duration;
    playerRef.current.seekTo(time, true);
    setCurrentTime(time);
  };

  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // Resize handlers
  const handleResizeStart = (e, direction) => {
    e.preventDefault();
    const startY = e.clientY;
    const startHeight = videoHeight;
    const minHeight = 150;
    const maxHeight = 600;

    const handleMouseMove = (e) => {
      const delta = e.clientY - startY;
      // Top bar: drag up = increase, drag down = decrease
      // Bottom bar: drag down = increase, drag up = decrease
      const adjustedDelta = direction === 'top' ? -delta : delta;
      const newHeight = Math.max(minHeight, Math.min(maxHeight, startHeight + adjustedDelta));
      setVideoHeight(newHeight);
    };

    const handleMouseUp = () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  };

  // What the player is actually serving. Not a control: YouTube decides the
  // rate and ignores requests to change it, so a button that cycled through
  // "720p / 1080p" was reporting a preference the player had already
  // discarded. This says what is on screen.
  const [videoQuality, setVideoQuality] = useState('auto');

  const QUALITY_LABELS = {
    tiny: '144p', small: '240p', medium: '360p', large: '480p',
    hd720: '720p', hd1080: '1080p', hd1440: '1440p', hd2160: '4K',
    highres: '4K+', auto: 'AUTO', unknown: '—',
  };

  const getQualityLabel = () => QUALITY_LABELS[videoQuality] || 'AUTO';

  // Derived data
  // Only offer options that actually have shows. The coverage catalog marks
  // each year/season/gender available or not, so a year firstVIEW holds
  // nothing for under the chosen gender (Men before ~2000, most Men Cruise)
  // never becomes a filter that returns an empty list.
  const availableFor = (yearNode, gender) => {
    if (!yearNode) return false;
    return Object.values(yearNode).some(byGender => byGender?.[gender]?.available);
  };

  const years = Object.keys(parsedSeasons)
    .filter(y => availableFor(parsedSeasons[y], filters.gender))
    .sort((a, b) => b - a);

  // Seasons offered depend on the year when one is chosen, and otherwise on
  // the archive as a whole — the filters do not require an order.
  const seasonsAvailable = (() => {
    const out = new Set();
    const yearKeys = filters.year ? [filters.year] : Object.keys(parsedSeasons);
    for (const y of yearKeys) {
      const node = parsedSeasons[y];
      if (!node) continue;
      for (const [season, byGender] of Object.entries(node)) {
        if (byGender?.[filters.gender]?.available) out.add(season);
      }
    }
    return [...out].sort();
  })();

  // Categories offered, likewise: the union across whatever is still in
  // scope, so picking Haute Couture never lands on an empty list.
  const categoriesAvailable = (() => {
    const totals = {};
    const yearKeys = filters.year ? [filters.year] : Object.keys(parsedSeasons);
    for (const y of yearKeys) {
      const node = parsedSeasons[y];
      if (!node) continue;
      for (const [season, byGender] of Object.entries(node)) {
        if (filters.season && season !== filters.season) continue;
        const cats = byGender?.[filters.gender]?.categories;
        if (!cats) return GARMENT_TYPES.map(t => t.value);   // no catalog yet
        for (const [name, n] of Object.entries(cats)) {
          totals[name] = (totals[name] || 0) + n;
        }
      }
    }
    return GARMENT_TYPES.map(t => t.value).filter(v => (totals[v] || 0) > 0);
  })();

  const activeFilterCount = COUNTED_FILTER_KEYS.filter(k => filters[k]).length;

  // In designer mode every show is already here, so the filters are applied
  // in the browser: choosing 2003, or Men, is instant and costs no request.
  const matchesFilters = useCallback((row, except) => {
    const want = (key, value) =>
      except === key || !filters[key] || String(filters[key]) === String(value);
    return want('gender', row.gender)
      && want('year', row.year)
      && want('season', row.season)
      && want('category', row.category)
      && want('shootType', row.shoot_type);
  }, [filters]);

  // Indexed, the server already applied every filter, so the rows that came
  // back are the rows to show. Only the fallback path filters in the browser.
  const visibleCollections = (!indexReady && designerMode)
    ? designerRows.filter(r => matchesFilters(r))
    : collections;

  // Facet values, with exact counts, from the index. The coverage catalog
  // could only ever say "at least 20" — that is one results page — so this
  // is the first time the filters know what they are offering.
  const facetValues = (key) => serverFacets?.[key]?.map(f => f.value) ?? null;
  const facetCount = (key, value) =>
    serverFacets?.[key]?.find(f => String(f.value) === String(value))?.count ?? null;

  // Each dropdown lists what is reachable given the *other* filters, so no
  // combination in designer mode leads to an empty list. Picking Men on a
  // designer who never showed menswear in 2020 should not leave 2020 on
  // offer — that is the dead end the archive filters were built to avoid,
  // and it would be no better here.
  const designerOptions = (key, field) => {
    if (!designerMode) return null;
    const values = designerRows
      .filter(r => matchesFilters(r, key))
      .map(r => r[field])
      .filter(v => v !== null && v !== undefined && v !== '');
    return [...new Set(values)];
  };

  const designerYears = facetValues('year')?.slice().sort((a, b) => b - a)
    ?? designerOptions('year', 'year')?.sort((a, b) => b - a);
  const designerSeasons = facetValues('season')?.slice().sort()
    ?? designerOptions('season', 'season')?.sort();
  const designerCategories = facetValues('category')
    ?? designerOptions('category', 'category');
  const designerShootTypes = facetValues('shootType')
    ?? designerOptions('shootType', 'shoot_type');

  const listLoading = designerMode ? designerLoading : collectionsLoading;

  const currentLookNumber = images.length > 0
    ? extractLookNumber(images[currentImageIndex], currentImageIndex)
    : 0;

  return (
    <div className="hf2-container">
      <TopBar
        currentPage={currentPage}
        onPageSwitch={onPageSwitch}
        currentUser={currentUser}
        onLogout={onLogout}
      />

      {/* Content Area */}
      <div className="hf2-content">
        {/* The handle sits on the seam rather than inside the sidebar, so it
            is still there to pull once the sidebar has gone. */}
        <button
          type="button"
          className={`hf2-sidebar-handle ${sidebarOpen ? '' : 'closed'}`}
          onClick={toggleSidebar}
          title={sidebarOpen ? 'Hide the list' : 'Show the list'}
          aria-label={sidebarOpen ? 'Hide the list' : 'Show the list'}
        >
          {sidebarOpen ? '‹' : '›'}
        </button>

        {/* Sidebar */}
        <div className={`hf2-sidebar ${sidebarOpen ? '' : 'collapsed'}`}>
        <Filters
          searchInputRef={searchInputRef}
          designerIndex={designerIndex}
          query={query}
          setQuery={setQuery}
          searchFocused={searchFocused}
          setSearchFocused={setSearchFocused}
          handleSearchKeyDown={handleSearchKeyDown}
          suggestionList={suggestionList}
          activeSuggestion={activeSuggestion}
          setActiveSuggestion={setActiveSuggestion}
          chooseSuggestion={chooseSuggestion}
          indexReady={indexReady}
          designerMode={designerMode}
          filters={filters}
          setFilter={setFilter}
          years={years}
          designerYears={designerYears}
          seasonsAvailable={seasonsAvailable}
          designerSeasons={designerSeasons}
          categoriesAvailable={categoriesAvailable}
          designerCategories={designerCategories}
          designerShootTypes={designerShootTypes}
          facetValues={facetValues}
          facetCount={facetCount}
          clearFilters={clearFilters}
          activeFilterCount={activeFilterCount}
        />

        <ShowList
          designerMode={designerMode}
          searchText={searchText}
          exitDesigner={exitDesigner}
          visibleCollections={visibleCollections}
          indexReady={indexReady}
          cursor={cursor}
          designerRows={designerRows}
          handleListScroll={handleListScroll}
          listLoading={listLoading}
          listError={listError}
          selectedCollection={selectedCollection}
          handleCollectionSelect={handleCollectionSelect}
          designerLoading={designerLoading}
          loadingMore={loadingMore}
        />
      </div>

      <Viewer
        images={images}
        imagesLoading={imagesLoading}
        currentImageIndex={currentImageIndex}
        setCurrentImageIndex={showLook}
        currentLookNumber={currentLookNumber}
        extractLookNumber={extractLookNumber}
        selectedCollection={selectedCollection}
        viewMode={viewMode}
        setViewMode={setViewMode}
        selectImageFromGrid={selectImageFromGrid}
        isFavourite={isFavourite}
        toggleFavourite={toggleFavourite}
        thumbStripRef={thumbStripRef}
        activeThumbRef={activeThumbRef}
        showVideo={showVideo}
        setShowVideo={setShowVideo}
        videoData={videoData}
        videoState={videoState}
        setVideoState={setVideoState}
        videoError={videoError}
        setVideoError={setVideoError}
        handleVideoSearch={handleVideoSearch}
        videoHeight={videoHeight}
        isPlaying={isPlaying}
        currentTime={currentTime}
        duration={duration}
        playerContainerRef={playerContainerRef}
        handleResizeStart={handleResizeStart}
        togglePlay={togglePlay}
        seekTo={seekTo}
        formatTime={formatTime}
        getQualityLabel={getQualityLabel}
      />
      </div>


      {/* Status Bar */}
      <StatusBar
        selectedCollection={selectedCollection}
        filters={filters}
        imagesLength={images.length}
        currentLookNumber={currentLookNumber}
      />
    </div>
  );
}

export default HighFashionPage;
