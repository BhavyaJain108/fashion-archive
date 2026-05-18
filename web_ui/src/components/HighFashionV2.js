import React, { useState, useEffect, useCallback, useRef } from 'react';
import { FashionArchiveAPI } from '../services/api';
import TopBar from './TopBar';
import './HighFashionV2.css';

function HighFashionV2({ currentPage = 'high-fashion', onPageSwitch, onLogout, currentUser }) {
  // Hierarchy state
  const [parsedSeasons, setParsedSeasons] = useState({});
  const [selectedYear, setSelectedYear] = useState(null);
  const [selectedSeason, setSelectedSeason] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState(null);

  // Collections state
  const [collections, setCollections] = useState([]);
  const [selectedCollection, setSelectedCollection] = useState(null);
  const [collectionsLoading, setCollectionsLoading] = useState(false);

  // Images state
  const [images, setImages] = useState([]);
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [imagesLoading, setImagesLoading] = useState(false);
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

  // Parse season name into components
  const parseSeason = useCallback((season) => {
    const name = season.name.toLowerCase();
    let year = null;
    let seasonType = null;
    let category = null;

    const yearMatch = name.match(/20\d{2}/);
    if (yearMatch) year = yearMatch[0];

    if (name.includes('fall') || name.includes('fw')) {
      seasonType = 'Fall';
    } else if (name.includes('spring') || name.includes('ss')) {
      seasonType = 'Spring';
    } else if (name.includes('resort')) {
      seasonType = 'Resort';
    }

    if (name.includes('ready to wear') || name.includes('rtw')) {
      category = 'RTW';
    } else if (name.includes('menswear') || name.includes('men')) {
      category = 'Menswear';
    } else if (name.includes('couture')) {
      category = 'Couture';
    }

    return { year, seasonType, category, original: season };
  }, []);

  // Build hierarchy from seasons
  const buildHierarchy = useCallback((seasons) => {
    const hierarchy = {};
    seasons.forEach(season => {
      const parsed = parseSeason(season);
      if (!parsed.year || !parsed.seasonType || !parsed.category) return;

      if (!hierarchy[parsed.year]) hierarchy[parsed.year] = {};
      if (!hierarchy[parsed.year][parsed.seasonType]) hierarchy[parsed.year][parsed.seasonType] = {};
      hierarchy[parsed.year][parsed.seasonType][parsed.category] = parsed.original;
    });
    return hierarchy;
  }, [parseSeason]);

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
    setSelectedYear(year);
    setSelectedSeason(null);
    setSelectedCategory(null);
    setSelectedCollection(null);
    setCollections([]);
    setImages([]);
  };

  const handleSeasonSelect = (season) => {
    setSelectedSeason(season);
    setSelectedCategory(null);
    setSelectedCollection(null);
    setCollections([]);
    setImages([]);
  };

  const handleCategorySelect = async (category) => {
    setSelectedCategory(category);
    setSelectedCollection(null);
    setImages([]);

    const seasonData = parsedSeasons[selectedYear]?.[selectedSeason]?.[category];
    if (!seasonData) return;

    setCollectionsLoading(true);
    try {
      const collectionsData = await FashionArchiveAPI.streamCollections(seasonData.url, () => {});
      setCollections(collectionsData || []);
    } catch (error) {
      console.error('Failed to load collections:', error);
      setCollections([]);
    } finally {
      setCollectionsLoading(false);
    }
  };

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

    try {
      await FashionArchiveAPI.cleanupDownloads();
      const imageData = await FashionArchiveAPI.downloadImages(collection);
      setImages(imageData.imagePaths || []);
    } catch (error) {
      console.error('Failed to load images:', error);
      setImages([]);
    } finally {
      setImagesLoading(false);
    }
  };

  // Search for video
  const handleVideoSearch = async () => {
    if (!selectedCollection || videoState === 'loading') return;

    setVideoState('loading');
    try {
      const seasonName = parsedSeasons[selectedYear]?.[selectedSeason]?.[selectedCategory]?.name || '';
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
  const years = Object.keys(parsedSeasons).sort((a, b) => b - a);
  const seasons = selectedYear ? Object.keys(parsedSeasons[selectedYear] || {}).sort() : [];
  const categories = selectedYear && selectedSeason
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
        <div className="hf2-nav-row">
          {/* Years */}
          <div className="hf2-nav-col">
            <div className="hf2-nav-header">Year</div>
            <div className="hf2-nav-list">
              {years.length === 0 ? (
                <div className="hf2-nav-empty">Loading...</div>
              ) : (
                years.map(year => (
                  <div
                    key={year}
                    className={`hf2-nav-item ${year === selectedYear ? 'selected' : ''}`}
                    onClick={() => handleYearSelect(year)}
                  >
                    {year}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Seasons */}
          <div className={`hf2-nav-col ${!selectedYear ? 'disabled' : ''}`}>
            <div className="hf2-nav-header">Season</div>
            <div className="hf2-nav-list">
              {!selectedYear ? (
                <div className="hf2-nav-empty">Select year</div>
              ) : (
                seasons.map(season => (
                  <div
                    key={season}
                    className={`hf2-nav-item ${season === selectedSeason ? 'selected' : ''}`}
                    onClick={() => handleSeasonSelect(season)}
                  >
                    {season}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Categories */}
          <div className={`hf2-nav-col ${!selectedSeason ? 'disabled' : ''}`}>
            <div className="hf2-nav-header">Type</div>
            <div className="hf2-nav-list">
              {!selectedSeason ? (
                <div className="hf2-nav-empty">Select season</div>
              ) : (
                categories.map(cat => (
                  <div
                    key={cat}
                    className={`hf2-nav-item ${cat === selectedCategory ? 'selected' : ''}`}
                    onClick={() => handleCategorySelect(cat)}
                  >
                    {cat}
                  </div>
                ))
              )}
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
            ) : !selectedCategory ? (
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
                  <span className="name">{cleanDesignerName(col.designer)}</span>
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
          {selectedCategory && <> / {selectedCategory}</>}
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
