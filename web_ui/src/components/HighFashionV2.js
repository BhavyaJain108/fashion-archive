import React, { useState, useEffect, useCallback, useRef } from 'react';
import { FashionArchiveAPI } from '../services/api';
import TopBar from './TopBar';
import './HighFashionV2.css';

// Garment category — firstVIEW's `s_n` filter. Exactly one is always
// selected: "All" mixed Ready-to-Wear and Couture shows of the same
// designer into rows that looked like repeats.
const GARMENT_TYPES = [
  { value: 'Ready-to-Wear', label: 'Ready-to-Wear' },
  { value: 'Haute Couture', label: 'Haute Couture' },
  { value: 'Swim', label: 'Swim' },
];

// Shoot type — firstVIEW's `s_t`. This is what actually caused the
// duplicates: one show is catalogued several times, once per shoot, and the
// list showed all of them under the same brand name. Picking exactly one
// shoot removes the repeats without hiding anything — the other shoots are
// one click away.
const SHOOT_TYPES = [
  { value: 'Runway Collection', label: 'Collection' },
  { value: 'Runway Details', label: 'Details' },
  { value: 'Runway Atmosphere', label: 'Atmosphere' },
  { value: 'Backstage Beauty and Fashion', label: 'Backstage' },
  { value: 'Lookbook', label: 'Lookbook' },
  { value: 'Bridal Collection', label: 'Bridal' },
];

// Seasons are shown abbreviated so all four fit one row of a 280px column.
const SEASON_LABELS = {
  'Fall / Winter': 'F/W',
  'Spring / Summer': 'S/S',
};

function HighFashionV2({ currentPage = 'high-fashion', onPageSwitch, onLogout, currentUser }) {
  // Hierarchy state
  const [parsedSeasons, setParsedSeasons] = useState({});
  const [selectedYear, setSelectedYear] = useState(null);
  const [selectedSeason, setSelectedSeason] = useState(null);
  const [selectedGender, setSelectedGender] = useState(null);
  // Garment category and shoot type: independent of the year/season/gender
  // hierarchy, and always exactly one of each.
  const [selectedType, setSelectedType] = useState('Ready-to-Wear');
  const [selectedShootType, setSelectedShootType] = useState('Runway Collection');

  // Collections state
  const [collections, setCollections] = useState([]);
  const [selectedCollection, setSelectedCollection] = useState(null);
  const [collectionsLoading, setCollectionsLoading] = useState(false);

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
  }, []);

  // Drop any in-flight work when the component goes away.
  useEffect(() => () => {
    if (collectionsAbort.current) collectionsAbort.current.abort();
    if (imagesAbort.current) imagesAbort.current.abort();
  }, []);

  // Park the year strip on the selected year. Only the scrolling facet
  // needs this — the others show every option at once, so there is nothing
  // to scroll into view.
  const filtersRef = useRef(null);
  useEffect(() => {
    const root = filtersRef.current;
    if (!root) return;
    root.querySelectorAll('.hf2-filter-items.scroll-x').forEach(strip => {
      const chip = strip.querySelector('.hf2-chip.selected');
      if (!chip) return;
      // Measure with rects: offsetLeft is relative to the nearest positioned
      // ancestor, which is not the strip, and gave a wrong offset.
      const s = strip.getBoundingClientRect();
      const c = chip.getBoundingClientRect();
      const delta = (c.left + c.width / 2) - (s.left + s.width / 2);
      strip.scrollTo({ left: strip.scrollLeft + delta, behavior: 'smooth' });
    });
  }, [parsedSeasons, selectedYear]);
  const [viewMode, setViewMode] = useState('single'); // 'single' or 'grid'

  // Video state
  const [videoData, setVideoData] = useState(null);
  const [videoState, setVideoState] = useState('idle'); // 'idle', 'loading', 'ready', 'error'
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

  // Selection handlers
  const handleYearSelect = (year) => {
    abortCollections();
    abortImages();
    setSelectedYear(year);
    setSelectedSeason(null);
    setSelectedGender(null);
    setSelectedCollection(null);
    setCollections([]);
    setCollectionsLoading(false);
    setImages([]);
    setImagesLoading(false);
    setExpectedLookCount(0);
  };

  const handleSeasonSelect = (season) => {
    abortCollections();
    abortImages();
    setSelectedSeason(season);
    setSelectedGender(null);
    setSelectedCollection(null);
    setCollections([]);
    setCollectionsLoading(false);
    setImages([]);
    setImagesLoading(false);
    setExpectedLookCount(0);
  };

  const handleGenderSelect = (gender) => {
    abortCollections();
    abortImages();
    setSelectedGender(gender);
    setSelectedCollection(null);
    setCollections([]);
    setImages([]);
    setExpectedLookCount(0);
  };

  const handleTypeSelect = (type) => {
    abortCollections();
    abortImages();
    setSelectedType(type);
    setSelectedCollection(null);
    setCollections([]);
    setImages([]);
    setExpectedLookCount(0);
  };

  const handleShootTypeSelect = (shootType) => {
    abortCollections();
    abortImages();
    setSelectedShootType(shootType);
    setSelectedCollection(null);
    setCollections([]);
    setImages([]);
    setExpectedLookCount(0);
  };

  // Collections load whenever the full filter set is satisfied. Driving this
  // from an effect rather than the gender handler means changing the garment
  // category re-queries too, without duplicating the streaming logic.
  useEffect(() => {
    const seasonData = parsedSeasons[selectedYear]?.[selectedSeason]?.[selectedGender];
    if (!seasonData) return;

    const controller = new AbortController();
    collectionsAbort.current = controller;
    let cancelled = false;

    setCollectionsLoading(true);
    (async () => {
      try {
        await FashionArchiveAPI.streamCollections(
          seasonData.url,
          ({ collections, complete }) => {
            // A late frame from a superseded stream must not repopulate the list.
            if (cancelled || collectionsAbort.current !== controller) return;
            setCollections(collections);
            if (!complete) setCollectionsLoading(false);
          },
          controller.signal,
          { category: selectedType || undefined, shootType: selectedShootType || undefined },
        );
      } catch (error) {
        if (error.name === 'AbortError' || cancelled) return;
        console.error('Failed to load collections:', error);
        setCollections([]);
      } finally {
        if (!cancelled) setCollectionsLoading(false);
      }
    })();

    return () => { cancelled = true; controller.abort(); };
  }, [parsedSeasons, selectedYear, selectedSeason, selectedGender, selectedType, selectedShootType]);

  const handleCollectionSelect = async (collection) => {
    if (imagesLoading) return;

    setSelectedCollection(collection);
    setImages([]);
    setCurrentImageIndex(0);
    setImagesLoading(true);

    // Reset video state for new collection
    setVideoData(null);
    setVideoState('idle');
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
    try {
      const seasonName = parsedSeasons[selectedYear]?.[selectedSeason]?.[selectedGender]?.name || '';
      const result = await FashionArchiveAPI.downloadVideo(
        selectedCollection.designer,
        seasonName
      );
      if (result && result.embedUrl) {
        setVideoData(result);
        setVideoState('ready');
        setShowVideo(true);
      } else {
        setVideoState('error');
      }
    } catch (error) {
      console.error('Failed to find video:', error);
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
  // each year/season/gender available or not; combinations firstVIEW has
  // nothing for (Men before ~2000, most Men Cruise) are shown greyed and
  // unclickable rather than hidden, so the shape of the archive stays visible.
  const hasAny = (node) => {
    if (!node) return false;
    return Object.values(node).some(v =>
      v && typeof v === 'object' && ('available' in v ? v.available : hasAny(v)));
  };

  const years = Object.keys(parsedSeasons).sort((a, b) => b - a);
  const seasons = selectedYear ? Object.keys(parsedSeasons[selectedYear] || {}).sort() : [];

  const yearEnabled = (y) => hasAny(parsedSeasons[y]);
  const seasonEnabled = (sn) => hasAny(parsedSeasons[selectedYear]?.[sn]);
  const genderEnabled = (g) =>
    parsedSeasons[selectedYear]?.[selectedSeason]?.[g]?.available !== false;

  // Garment types available for the current year/season/gender.
  const currentCombo = parsedSeasons[selectedYear]?.[selectedSeason]?.[selectedGender];
  const typeEnabled = (value) => {
    if (!value) return true;                       // "All"
    const cats = currentCombo?.categories;
    if (!cats) return true;                        // no catalog yet
    return (cats[value] || 0) > 0;
  };
  const genders = selectedYear && selectedSeason
    ? Object.keys(parsedSeasons[selectedYear]?.[selectedSeason] || {}).sort()
    : [];

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
          {/* Navigation Row */}
        {/* Filters. The control follows the option set: a scroller only
            where the options cannot all be shown. */}
        <div className="hf2-filters" ref={filtersRef}>
          <div className="hf2-filter-row">
            <div className="hf2-filter-items scroll-x">
              {years.length === 0
                ? <span className="hf2-filter-empty">Loading…</span>
                : years.map(year => (
                    <button
                      key={year}
                      type="button"
                      className={`hf2-chip ${String(year) === String(selectedYear) ? 'selected' : ''}`}
                      disabled={!yearEnabled(year)}
                      onClick={() => handleYearSelect(year)}
                    >{year}</button>
                  ))}
            </div>
          </div>

          <div className={`hf2-filter-row ${!selectedYear ? 'disabled' : ''}`}>
            <div className="hf2-filter-items row">
              {!selectedYear
                ? <span className="hf2-filter-empty">Select a year</span>
                : seasons.map(season => (
                    <button
                      key={season}
                      type="button"
                      title={season}
                      className={`hf2-chip ${season === selectedSeason ? 'selected' : ''}`}
                      disabled={!seasonEnabled(season)}
                      onClick={() => handleSeasonSelect(season)}
                    >{SEASON_LABELS[season] || season}</button>
                  ))}
            </div>
          </div>

          {/* Gender is two mutually exclusive values, so it gets a split bar
              rather than a row of small text: the chosen half is filled. */}
          <div className={`hf2-filter-row ${!selectedSeason ? 'disabled' : ''}`}>
            {!selectedSeason
              ? <div className="hf2-filter-items row">
                  <span className="hf2-filter-empty">Select a season</span>
                </div>
              : <div className="hf2-segmented">
                  {genders.map(g => (
                    <button
                      key={g}
                      type="button"
                      className={`hf2-segment ${g === selectedGender ? 'selected' : ''}`}
                      disabled={!genderEnabled(g)}
                      onClick={() => handleGenderSelect(g)}
                    >{g}</button>
                  ))}
                </div>}
          </div>

          <div className="hf2-filter-row">
            <div className="hf2-filter-items row">
              {GARMENT_TYPES.map(t => (
                <button
                  key={t.value}
                  type="button"
                  className={`hf2-chip ${t.value === selectedType ? 'selected' : ''}`}
                  disabled={!typeEnabled(t.value)}
                  onClick={() => handleTypeSelect(t.value)}
                >{t.label}</button>
              ))}
            </div>
          </div>

          <div className="hf2-filter-row">
            <div className="hf2-filter-items wrap">
              {SHOOT_TYPES.map(t => (
                <button
                  key={t.value}
                  type="button"
                  title={t.value}
                  className={`hf2-chip ${t.value === selectedShootType ? 'selected' : ''}`}
                  onClick={() => handleShootTypeSelect(t.value)}
                >{t.label}</button>
              ))}
            </div>
          </div>
        </div>

        {/* Collections */}
        <div className="hf2-collections-area">
          <div className="hf2-collections-header">
            <span>Collections</span>
            {collections.length > 0 && <span className="count">{collections.length}</span>}
          </div>
          <div className="hf2-collections-scroll">
            {collectionsLoading ? (
              <div className="hf2-collections-loading">Loading...</div>
            ) : !selectedGender ? (
              <div className="hf2-collections-empty">Select year, season, and type</div>
            ) : collections.length === 0 ? (
              <div className="hf2-collections-empty">No collections found</div>
            ) : (
              collections.map((col, idx) => (
                <div
                  key={col.url}
                  className={`hf2-collection-item ${col.url === selectedCollection?.url ? 'selected' : ''}`}
                  onClick={() => handleCollectionSelect(col)}
                >
                  <span className="num">{String(idx + 1).padStart(3, '0')}</span>
                  <span className="body">
                    <span className="name">{cleanDesignerName(col.designer)}</span>
                    {col.subtitle && <span className="sub">{col.subtitle}</span>}
                  </span>
                </div>
              ))
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
          <button
            className={`hf2-video-btn ${showVideo ? 'active' : ''} ${videoState}`}
            onClick={() => {
              if (videoState === 'idle') {
                handleVideoSearch();
              } else if (videoState === 'ready') {
                setShowVideo(!showVideo);
              } else if (videoState === 'error') {
                setVideoState('idle');
              }
            }}
            disabled={videoState === 'loading'}
          >
            {videoState === 'loading' ? 'SEARCHING...' :
             videoState === 'error' ? 'NOT FOUND' :
             showVideo ? 'HIDE VIDEO' : 'VIDEO'}
          </button>
        </div>
      )}


      {/* Status Bar */}
      <div className="hf2-status-bar">
        <span className="hf2-status-path">
          {selectedYear && <>{selectedYear}</>}
          {selectedSeason && <> / {selectedSeason}</>}
          {selectedGender && <> / {selectedGender}</>}
          {selectedCollection && (
            <> / <span className="active">{cleanDesignerName(selectedCollection.designer)}</span></>
          )}
          {!selectedYear && 'No selection'}
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
