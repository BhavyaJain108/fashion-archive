import React, { useState, useEffect, useCallback, useRef } from 'react';
import { FashionArchiveAPI } from '../services/api';
import { prepare as prepareDesigners, search as searchDesigners } from '../lib/designerSearch';
import TopBar from './TopBar';
import './HighFashionV2.css';

// Garment category — firstVIEW's `s_n` filter. Optional, like every filter
// but gender: left unset, Ready-to-Wear, Couture and Swim all appear, and
// each row says which it is.
const GARMENT_TYPES = [
  { value: 'Ready-to-Wear', label: 'Ready-to-Wear' },
  { value: 'Haute Couture', label: 'Haute Couture' },
  { value: 'Swim', label: 'Swim' },
];

// Shoot type — firstVIEW's `s_t`. One show is catalogued several times, once
// per shoot, which is why the list used to look full of duplicates. They are
// genuinely different shoots of the same show, so the fix is to label them —
// the shoot type rides in each row's subtext — rather than to hide all but
// one, which is what forcing a single choice here amounted to.
const SHOOT_TYPES = [
  { value: 'Runway Collection', label: 'Collection' },
  { value: 'Runway Details', label: 'Details' },
  { value: 'Runway Atmosphere', label: 'Atmosphere' },
  { value: 'Backstage Beauty and Fashion', label: 'Backstage' },
  { value: 'Lookbook', label: 'Lookbook' },
  { value: 'Bridal Collection', label: 'Bridal' },
];

// Seasons are shown abbreviated: the subtext carries five other fields.
const SEASON_LABELS = {
  'Fall / Winter': 'F/W',
  'Spring / Summer': 'S/S',
};

// Jumping by initial is the only way firstVIEW offers to reach a designer
// directly, and with the whole archive in one list it is the difference
// between finding Yohji Yamamoto and scrolling for a very long time.
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

// The season a video search should ask about, taken from the row rather
// than from the filters — with the filters empty there is no selected
// season to read, and the row has always known its own.
function videoSeasonName(collection) {
  if (!collection) return '';
  const { season, year } = collection;
  if (season && year) return `${season} ${year}`;
  return year ? String(year) : '';
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

function HighFashionV2({ currentPage = 'high-fashion', onPageSwitch, onLogout, currentUser }) {
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
  const [filters, setFilters] = useState({
    gender: 'Women',
    year: '',
    season: '',
    category: '',
    shootType: '',
    letter: '',
  });

  // Collections state. `cursor` is where the next window starts; the list is
  // a window on 900+ pages, not a list that was ever fully fetched.
  const [collections, setCollections] = useState([]);
  const [selectedCollection, setSelectedCollection] = useState(null);
  const [collectionsLoading, setCollectionsLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [cursor, setCursor] = useState({ nextPage: 0, hasMore: false });

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

  const [viewMode, setViewMode] = useState('single'); // 'single' or 'grid'

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
  const resizingRef = useRef(false);
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

  // Clean designer name
  const cleanDesignerName = (fullName) => {
    return fullName
      .replace(/\s+(Ready To Wear|Menswear|Couture|Men & Women)\s+.*/i, '')
      .replace(/\s+(Fall|Spring|Winter|Summer)\s+.*/i, '')
      .trim();
  };

  // Extract look number from filename
  const extractLookNumber = (path, fallbackIdx) => {
    const filename = path.split('/').pop() || '';
    const match = filename.match(/-(\d+)\./);
    return match ? parseInt(match[1]) : fallbackIdx + 1;
  };

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

  // What the dropdown shows: matches while typing, where you have been when
  // the box is empty.
  const shownSuggestions = query.trim() ? suggestions : recentDesigners;

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
    setDesignerRows([]);
    setSelectedCollection(null);
    setCollections([]);
    setImages([]);
    setExpectedLookCount(0);
    // The catalog has no "all genders" — a query without one returns a small
    // bucket of ungendered shows — so it has to become a real choice again.
    setFilters(prev => ({ ...prev, gender: prev.gender || 'Women' }));
  }, [abortCollections, abortImages]);

  // One designer's shows, streamed. Nine pages for a prolific designer, so
  // rows land as they arrive rather than after five seconds.
  useEffect(() => {
    if (!designerMode) return;

    const controller = new AbortController();
    collectionsAbort.current = controller;
    let cancelled = false;
    const isCurrent = () => !cancelled && collectionsAbort.current === controller;

    setDesignerLoading(true);
    (async () => {
      try {
        await FashionArchiveAPI.streamDesignerCollections(designerMode.id, {
          signal: controller.signal,
          onUpdate: ({ rows }) => {
            if (!isCurrent()) return;
            setDesignerRows(rows);
          },
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
  }, [designerMode]);

  const handleSearchKeyDown = (e) => {
    const options = shownSuggestions;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveSuggestion(i => Math.min(options.length - 1, i + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveSuggestion(i => Math.max(0, i - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      openDesigner(options[activeSuggestion]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      if (query) setQuery('');
      else if (designerMode) exitDesigner();
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
    setFilters(prev => ({ gender: prev.gender, year: '', season: '',
                          category: '', shootType: '', letter: '' }));
    setSelectedCollection(null);
    setCollections([]);
    setImages([]);
    setExpectedLookCount(0);
  };

  // The first window of the current filter set. Reruns whenever a filter
  // changes; the streaming means rows appear as each page lands rather than
  // after the whole window.
  useEffect(() => {
    // In designer mode the list comes from the designer query instead, and
    // the filters narrow what is already loaded rather than refetching.
    if (designerMode) return;

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
            // A late frame from a superseded stream must not repopulate the
            // list — clicking through filters faster than a window completes
            // used to leave the previous one writing into state.
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
  }, [filters, designerMode]);

  // The next window, appended. Called when the list is scrolled near its
  // end; `hasMore` comes from the server having handed back a full page.
  const loadMore = useCallback(async () => {
    if (designerMode) return;      // their whole history is already loaded
    if (loadingMore || collectionsLoading || !cursor.hasMore) return;
    const controller = collectionsAbort.current;
    setLoadingMore(true);
    try {
      const result = await FashionArchiveAPI.streamCatalog(filters, {
        startPage: cursor.nextPage,
        signal: controller ? controller.signal : undefined,
        onUpdate: ({ rows }) => {
          if (collectionsAbort.current !== controller) return;
          setCollections(prev => {
            // Append only what is new: a window is re-delivered in full on
            // each frame, and the same show can be listed twice by the site.
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
  }, [filters, cursor, loadingMore, collectionsLoading, designerMode]);

  const handleListScroll = (e) => {
    const el = e.currentTarget;
    // 400px of runway, so the next window is usually already in by the time
    // the reader reaches the bottom.
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 400) loadMore();
  };


  const handleCollectionSelect = async (collection) => {
    setSelectedCollection(collection);
    setImages([]);
    setCurrentImageIndex(0);
    setImagesLoading(true);

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

  // Navigation (no wraparound)
  const prevImage = useCallback(() => {
    if (images.length === 0) return;
    setCurrentImageIndex((prev) => Math.max(0, prev - 1));
  }, [images.length]);

  const nextImage = useCallback(() => {
    if (images.length === 0) return;
    setCurrentImageIndex((prev) => Math.min(images.length - 1, prev + 1));
  }, [images.length]);

  const selectImageFromGrid = (idx) => {
    setCurrentImageIndex(idx);
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
      if (images.length === 0) return;
      if (e.key === 'ArrowLeft') prevImage();
      else if (e.key === 'ArrowRight') nextImage();
      else if (e.key === 'g') setViewMode(v => v === 'grid' ? 'single' : 'grid');
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [images.length, prevImage, nextImage]);

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
          controls: 0,
          modestbranding: 1,
          rel: 0,
          showinfo: 0,
          fs: 0,
          iv_load_policy: 3,
          disablekb: 1,
          playsinline: 1,
          cc_load_policy: 0,
          origin: window.location.origin,
          vq: 'hd720',
        },
        events: {
          onReady: (e) => {
            setDuration(e.target.getDuration());
            // Get available qualities
            const available = e.target.getAvailableQualityLevels?.() || [];
            setAvailableQualities(available);
            // Load with preferred quality
            e.target.loadVideoById({
              videoId: videoData.videoId,
              suggestedQuality: 'hd720'
            });
            e.target.pauseVideo();
          },
          onStateChange: (e) => {
            setIsPlaying(e.data === window.YT.PlayerState.PLAYING);
            // Update actual quality when playing
            if (e.data === window.YT.PlayerState.PLAYING) {
              const actualQuality = e.target.getPlaybackQuality?.();
              if (actualQuality) setVideoQuality(actualQuality);
            }
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

  // Video quality
  const [videoQuality, setVideoQuality] = useState('hd720');
  const [availableQualities, setAvailableQualities] = useState([]);

  const cycleQuality = () => {
    if (!playerRef.current) return;

    // Get available qualities from YouTube
    const available = playerRef.current.getAvailableQualityLevels?.() || [];
    const validQualities = ['small', 'medium', 'large', 'hd720', 'hd1080', 'highres'];
    const filtered = validQualities.filter(q => available.includes(q));

    if (filtered.length === 0) return;

    const currentIdx = filtered.indexOf(videoQuality);
    const nextIdx = (currentIdx + 1) % filtered.length;
    const newQuality = filtered[nextIdx];

    // Get current time and playing state
    const currentTime = playerRef.current.getCurrentTime?.() || 0;
    const wasPlaying = isPlaying;

    // Set the quality
    setVideoQuality(newQuality);

    // Reload video at same position with new quality
    playerRef.current.loadVideoById({
      videoId: videoData.videoId,
      startSeconds: currentTime,
      suggestedQuality: newQuality
    });

    // Pause if wasn't playing
    if (!wasPlaying) {
      setTimeout(() => {
        playerRef.current?.pauseVideo?.();
      }, 100);
    }
  };

  const getQualityLabel = () => {
    const labels = {
      small: '240p',
      medium: '360p',
      large: '480p',
      hd720: '720p',
      hd1080: '1080p',
      highres: '1440p+'
    };
    return labels[videoQuality] || '720p';
  };

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

  const activeFilterCount = ['year', 'season', 'category', 'shootType', 'letter']
    .filter(k => filters[k]).length;

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

  const visibleCollections = designerMode
    ? designerRows.filter(r => matchesFilters(r))
    : collections;

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

  const designerYears = designerOptions('year', 'year')?.sort((a, b) => b - a);
  const designerSeasons = designerOptions('season', 'season')?.sort();
  const designerCategories = designerOptions('category', 'category');
  const designerShootTypes = designerOptions('shootType', 'shoot_type');

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
        {/* Sidebar */}
        <div className="hf2-sidebar">
        {/* Search. One box: type a designer, press Enter, get everything they
            ever showed. The archive list is organised by season, so a
            designer's own history across thirty years is the one view the
            filters below cannot produce at all. */}
        <div className="hf2-search">
          <input
            ref={searchInputRef}
            type="text"
            className="hf2-search-input"
            placeholder={designerIndex ? 'Search designers' : 'Search unavailable'}
            value={query}
            disabled={!designerIndex}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setSearchFocused(true)}
            // A click on a suggestion blurs the input first, so closing is
            // deferred a beat or the option is gone before it is chosen.
            onBlur={() => setTimeout(() => setSearchFocused(false), 120)}
            onKeyDown={handleSearchKeyDown}
            spellCheck={false}
            autoComplete="off"
          />
          {query && (
            <button type="button" className="hf2-search-clear"
                    onClick={() => { setQuery(''); searchInputRef.current?.focus(); }}>
              ✕
            </button>
          )}

          {searchFocused && shownSuggestions.length > 0 && (
            <div className="hf2-search-results">
              {!query.trim() && (
                <div className="hf2-search-heading">Recently opened</div>
              )}
              {shownSuggestions.map((d, i) => (
                <button
                  key={d.id}
                  type="button"
                  className={`hf2-search-option ${i === activeSuggestion ? 'active' : ''}`}
                  onMouseEnter={() => setActiveSuggestion(i)}
                  onMouseDown={(e) => e.preventDefault()}   // keep focus until the click lands
                  onClick={() => openDesigner(d)}
                >{d.name}</button>
              ))}
            </div>
          )}
          {searchFocused && query.trim() && shownSuggestions.length === 0 && (
            <div className="hf2-search-results">
              <div className="hf2-search-empty">No designer by that name</div>
            </div>
          )}
        </div>

        {/* Filters. Every one of them is optional and additive: the list
            below starts as the whole archive and each choice narrows it.
            One thin row per filter, left aligned, so five of them cost less
            height than a single scroll wheel did. */}
        <div className="hf2-filters">
          {/* Gender is the one filter the archive list cannot leave empty:
              firstVIEW has no "both", and a query without a gender returns a
              small bucket of ungendered shows rather than everything.
              In designer mode that constraint is gone — both genders are
              already loaded — so All appears and is the default. */}
          <div className="hf2-segmented">
            {(designerMode ? ['', 'Women', 'Men'] : ['Women', 'Men']).map(g => (
              <button
                key={g || 'all'}
                type="button"
                className={`hf2-segment ${g === filters.gender ? 'selected' : ''}`}
                onClick={() => setFilter('gender', g)}
              >{g || 'All'}</button>
            ))}
          </div>

          <label className="hf2-facet">
            <span className="hf2-facet-label">Year</span>
            <select
              className={`hf2-facet-select ${filters.year ? 'set' : ''}`}
              value={filters.year}
              onChange={(e) => setFilter('year', e.target.value)}
            >
              <option value="">All years</option>
              {(designerYears || years).map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>

          <label className="hf2-facet">
            <span className="hf2-facet-label">Season</span>
            <select
              className={`hf2-facet-select ${filters.season ? 'set' : ''}`}
              value={filters.season}
              onChange={(e) => setFilter('season', e.target.value)}
            >
              <option value="">All seasons</option>
              {(designerSeasons || seasonsAvailable).map(sn => (
                <option key={sn} value={sn}>{SEASON_LABELS[sn] || sn}</option>
              ))}
            </select>
          </label>

          <label className="hf2-facet">
            <span className="hf2-facet-label">Type</span>
            <select
              className={`hf2-facet-select ${filters.category ? 'set' : ''}`}
              value={filters.category}
              onChange={(e) => setFilter('category', e.target.value)}
            >
              <option value="">All types</option>
              {GARMENT_TYPES.filter(t => (designerCategories || categoriesAvailable)
                                             .includes(t.value)).map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </label>

          <label className="hf2-facet">
            <span className="hf2-facet-label">Shoot</span>
            <select
              className={`hf2-facet-select ${filters.shootType ? 'set' : ''}`}
              value={filters.shootType}
              onChange={(e) => setFilter('shootType', e.target.value)}
            >
              <option value="">All shoots</option>
              {SHOOT_TYPES.filter(t => !designerShootTypes
                                       || designerShootTypes.includes(t.value)).map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </label>

          <label className={`hf2-facet ${designerMode ? 'hidden' : ''}`}>
            <span className="hf2-facet-label">Brand</span>
            <select
              className={`hf2-facet-select ${filters.letter ? 'set' : ''}`}
              value={filters.letter}
              onChange={(e) => setFilter('letter', e.target.value)}
            >
              <option value="">A–Z</option>
              {LETTERS.map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </label>

          <button
            type="button"
            className="hf2-filter-clear"
            onClick={clearFilters}
            disabled={activeFilterCount === 0}
          >
            {activeFilterCount === 0
              ? 'Whole archive'
              : `Clear ${activeFilterCount} filter${activeFilterCount > 1 ? 's' : ''}`}
          </button>
        </div>

        {/* Collections */}
        <div className="hf2-collections-area">
          <div className="hf2-collections-header">
            {designerMode ? (
              <>
                <button type="button" className="hf2-designer-exit" onClick={exitDesigner}>
                  ← Archive
                </button>
                <span className="hf2-designer-name" title={designerMode.name}>
                  {designerMode.name}
                </span>
              </>
            ) : (
              <span>Shows</span>
            )}
            {visibleCollections.length > 0 && (
              <span className="count">
                {/* In designer mode the filtered count is stated against the
                    whole, so narrowing never looks like their work vanished. */}
                {designerMode && visibleCollections.length !== designerRows.length
                  ? `${visibleCollections.length}/${designerRows.length}`
                  : `${visibleCollections.length}${!designerMode && cursor.hasMore ? '+' : ''}`}
              </span>
            )}
          </div>
          <div className="hf2-collections-scroll" onScroll={handleListScroll}>
            {listLoading && visibleCollections.length === 0 ? (
              <div className="hf2-collections-loading">Loading…</div>
            ) : listError ? (
              <div className="hf2-collections-error">
                <span>Could not load shows</span>
                <span className="detail">{listError}</span>
              </div>
            ) : visibleCollections.length === 0 ? (
              <div className="hf2-collections-empty">
                {designerMode
                  ? `${designerMode.name} has no shows matching these filters`
                  : 'No shows match these filters'}
              </div>
            ) : (
              <>
                {visibleCollections.map((col, idx) => (
                  <div
                    key={col.collection_id || col.url}
                    className={`hf2-collection-item ${col.url === selectedCollection?.url ? 'selected' : ''}`}
                    onClick={() => handleCollectionSelect(col)}
                  >
                    <span className="num">{String(idx + 1).padStart(3, '0')}</span>
                    <span className="body">
                      <span className="name">{cleanDesignerName(col.designer)}</span>
                      {/* Abbreviated to fit the column; the tooltip has it in
                          full for the rows where the tail still gets cut. */}
                      {col.subtitle && (
                        <span className="sub" title={col.subtitle}>{col.subtitle}</span>
                      )}
                    </span>
                  </div>
                ))}
                {designerMode && designerLoading && (
                  <div className="hf2-collections-more">Loading more…</div>
                )}
                {!designerMode && cursor.hasMore && (
                  <div className="hf2-collections-more">
                    {loadingMore ? 'Loading more…' : 'Scroll for more'}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* Main Area */}
      <div className="hf2-main">
        {imagesLoading ? (
          <div className="hf2-placeholder">Loading images...</div>
        ) : images.length === 0 ? (
          <div className="hf2-placeholder">
            {selectedCollection ? 'No images found' : 'Select a collection to view looks'}
          </div>
        ) : viewMode === 'single' ? (
          <div className={`hf2-single-container ${showVideo && videoData ? 'with-video' : ''}`}>
            {/* Main Content Area */}
            <div className="hf2-single-content">
              {/* Image Side */}
              <div className="hf2-image-side">
                <div className="hf2-image-frame">
                  <img
                    src={FashionArchiveAPI.getImageUrl(images[currentImageIndex])}
                    alt={`Look ${currentLookNumber}`}
                  />
                </div>
                <div className="hf2-image-info">
                  <span className="hf2-look-label">LOOK {String(currentLookNumber).padStart(2, '0')}</span>
                  <span className="hf2-look-count">{currentImageIndex + 1} / {images.length}</span>
                </div>
              </div>

              {/* Video Side */}
              {showVideo && videoData && (
                <div className="hf2-video-side">
                  {/* Resizable video area */}
                  <div className="hf2-video-resizable">
                    {/* Top resize bar */}
                    <div className="hf2-resize-bar" onMouseDown={(e) => handleResizeStart(e, 'top')} />

                    {/* Video container with overflow hidden */}
                    <div className="hf2-video-wrapper" style={{ height: videoHeight }}>
                      <div className="hf2-video-frame">
                        <div ref={playerContainerRef} className="hf2-youtube-player" />
                      </div>
                    </div>

                    {/* Bottom resize bar */}
                    <div className="hf2-resize-bar" onMouseDown={(e) => handleResizeStart(e, 'bottom')} />
                  </div>

                  {/* Fixed controls at bottom */}
                  <div className="hf2-video-controls">
                    <button className="hf2-play-btn" onClick={togglePlay}>
                      {isPlaying ? '❚❚' : '▶'}
                    </button>
                    <div className="hf2-progress-bar" onClick={seekTo}>
                      <div
                        className="hf2-progress-fill"
                        style={{ width: `${duration ? (currentTime / duration) * 100 : 0}%` }}
                      />
                    </div>
                    <span className="hf2-time">
                      {formatTime(currentTime)} / {formatTime(duration)}
                    </span>
                    <button className="hf2-quality-btn" onClick={cycleQuality}>
                      {getQualityLabel()}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : null}

        {/* Grid View */}
        {viewMode === 'grid' && images.length > 0 && (
          <div className="hf2-grid-container">
            <div className="hf2-grid-view">
              {images.map((imgPath, idx) => {
                const lookNum = extractLookNumber(imgPath, idx);
                return (
                  <div
                    key={imgPath}
                    className={`hf2-grid-item ${idx === currentImageIndex ? 'selected' : ''}`}
                    onClick={() => selectImageFromGrid(idx)}
                  >
                    <div className="hf2-grid-image-wrapper">
                      <img
                        src={FashionArchiveAPI.getImageUrl(imgPath)}
                        alt={`Look ${lookNum}`}
                        loading="lazy"
                      />
                    </div>
                    <span className="look-num">{String(lookNum).padStart(2, '0')}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Horizontal Thumbnail Strip - spans full width in single view */}
        {viewMode === 'single' && images.length > 0 && (
          <div className="hf2-thumb-strip-container">
            <div className="hf2-thumb-strip" ref={thumbStripRef}>
              {images.map((imgPath, idx) => (
                <div
                  key={imgPath}
                  ref={idx === currentImageIndex ? activeThumbRef : null}
                  className={`hf2-thumb ${idx === currentImageIndex ? 'active' : ''}`}
                  onClick={() => setCurrentImageIndex(idx)}
                >
                  <img
                    src={FashionArchiveAPI.getImageUrl(imgPath)}
                    alt={`Look ${extractLookNumber(imgPath, idx)}`}
                  />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      </div>

      {/* View Toggle & Video Button */}
      {images.length > 0 && (
        <div className="hf2-controls">
          <div className="hf2-view-toggle">
            <button
              className={`hf2-view-btn ${viewMode === 'single' ? 'active' : ''}`}
              onClick={() => setViewMode('single')}
            >
              SINGLE
            </button>
            <button
              className={`hf2-view-btn ${viewMode === 'grid' ? 'active' : ''}`}
              onClick={() => setViewMode('grid')}
            >
              GRID
            </button>
          </div>
          {/* The label changes length as the state changes, and the bar is
              pinned to the right edge — so the text sits in a fixed-width
              slot. Without it, clicking VIDEO grew the button leftwards and
              shoved SINGLE/GRID across the screen mid-search. */}
          <button
            className={`hf2-video-btn ${showVideo ? 'active' : ''} ${videoState}`}
            title={videoState === 'error' && videoError ? videoError.detail : undefined}
            onClick={() => {
              if (videoState === 'idle') {
                handleVideoSearch();
              } else if (videoState === 'ready') {
                setShowVideo(!showVideo);
              } else if (videoState === 'error') {
                // Retry: the reason may have been the server's, not this show's.
                setVideoError(null);
                setVideoState('idle');
                handleVideoSearch();
              }
            }}
            disabled={videoState === 'loading'}
          >
            <span className="hf2-video-btn-label">
              {videoState === 'loading' ? 'SEARCHING' :
               videoState === 'error' ? (videoError?.label || 'NO VIDEO') :
               showVideo ? 'HIDE VIDEO' : 'VIDEO'}
            </span>
          </button>
        </div>
      )}


      {/* Status Bar */}
      <div className="hf2-status-bar">
        <span className="hf2-status-path">
          {selectedCollection ? (
            <>
              {videoSeasonName(selectedCollection)}
              {selectedCollection.gender && <> / {selectedCollection.gender}</>}
              {' / '}
              <span className="active">{cleanDesignerName(selectedCollection.designer)}</span>
            </>
          ) : (
            <>
              {filters.gender}
              {filters.year && <> / {filters.year}</>}
              {filters.season && <> / {filters.season}</>}
              {filters.category && <> / {filters.category}</>}
            </>
          )}
        </span>
        <span className="hf2-status-look">
          {images.length > 0 && (
            <>LOOK <span className="active">{String(currentLookNumber).padStart(2, '0')}</span> / {images.length}</>
          )}
        </span>
      </div>
    </div>
  );
}

export default HighFashionV2;
