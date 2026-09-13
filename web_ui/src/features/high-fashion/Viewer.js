import React from 'react';
import { FashionArchiveAPI } from '../../shared/api';
import { lookLabel, lookAlt } from '../../shared/lib/lookLabel';
import ThumbStrip from './ThumbStrip';
import VideoPanel from './VideoPanel';

// The looks themselves: the single view, the grid, the thumbnail strip, and
// the floating controls that switch between them.
//
// The controls row is part of this component rather than of the page because
// it is what `viewMode` is for — the same state decides which container is
// drawn and which button reads as active. It is `position: fixed`, so where
// it sits in the tree does not decide where it sits on screen.
//
// Presentational: every value and every handler is a prop, including
// `isFavourite`, which is asked per tile rather than precomputed.
function Viewer({
  images,
  imagesLoading,
  imagesStale,
  imagesError,
  currentImageIndex,
  setCurrentImageIndex,
  currentLookNumber,
  extractLookNumber,
  selectedCollection,
  viewMode,
  setViewMode,
  selectImageFromGrid,
  isFavourite,
  toggleFavourite,
  thumbStripRef,
  activeThumbRef,
  // Video
  showVideo,
  setShowVideo,
  videoData,
  videoState,
  setVideoState,
  videoError,
  setVideoError,
  handleVideoSearch,
  videoHeight,
  isPlaying,
  currentTime,
  duration,
  playerContainerRef,
  handleResizeStart,
  togglePlay,
  seekTo,
  formatTime,
  getQualityLabel,
}) {
  return (
    <>
      {/* Main Area */}
      {/* Dimmed, not emptied. `imagesStale` means the looks below belong to
          the show that was open a moment ago and the one being opened has
          nothing to put there yet — so it is marked rather than taken away.
          It is only worth marking when there is something on screen: the
          first show of a session is stale too, and dimming its "Loading
          images..." helps nobody. */}
      <div className={`hf2-main ${imagesStale && images.length > 0 ? 'stale' : ''}`}>
        {/* The placeholder is for an empty pane only. It used to be shown
            whenever a stream was running, which is exactly what blanked the
            show you were reading the moment you clicked another one. */}
        {images.length === 0 ? (
          <div className="hf2-placeholder">
            {imagesError ? 'Could not load this show'
             : imagesLoading ? 'Loading images...'
             : selectedCollection ? 'No images found'
             : 'Select a collection to view looks'}
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
                    alt={lookAlt(currentLookNumber)}
                  />
                </div>
                <div className="hf2-image-info">
                  <span className="hf2-look-label">{lookLabel(currentLookNumber)}</span>
                  {/* Keeping a look was possible in the database and in the API
                      from the start, and nowhere on the screen. */}
                  <button
                    type="button"
                    className={`hf2-fav-btn ${isFavourite(currentLookNumber) ? 'on' : ''}`}
                    onClick={() => toggleFavourite(currentLookNumber, images[currentImageIndex])}
                    title={isFavourite(currentLookNumber)
                      ? 'Remove from favourites (F)'
                      : 'Keep this look (F)'}
                    aria-pressed={isFavourite(currentLookNumber)}
                  >
                    {isFavourite(currentLookNumber) ? '★' : '☆'}
                  </button>
                  <span className="hf2-look-count">{currentImageIndex + 1} / {images.length}</span>
                </div>
              </div>

              {/* Video Side */}
              {showVideo && videoData && (
                <VideoPanel
                  videoHeight={videoHeight}
                  isPlaying={isPlaying}
                  currentTime={currentTime}
                  duration={duration}
                  playerContainerRef={playerContainerRef}
                  onResizeStart={handleResizeStart}
                  onTogglePlay={togglePlay}
                  onSeek={seekTo}
                  formatTime={formatTime}
                  getQualityLabel={getQualityLabel}
                />
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
                    className={`hf2-grid-item ${idx === currentImageIndex ? 'selected' : ''} ${
                      isFavourite(lookNum) ? 'kept' : ''}`}
                    onClick={() => selectImageFromGrid(idx)}
                  >
                    <div className="hf2-grid-image-wrapper">
                      <img
                        src={FashionArchiveAPI.getImageUrl(imgPath)}
                        alt={lookAlt(lookNum)}
                        loading="lazy"
                      />
                    </div>
                    <span className="look-num">{lookLabel(lookNum)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Horizontal Thumbnail Strip - spans full width in single view */}
        {viewMode === 'single' && images.length > 0 && (
          <ThumbStrip
            images={images}
            currentImageIndex={currentImageIndex}
            onSelect={setCurrentImageIndex}
            isFavourite={isFavourite}
            stripRef={thumbStripRef}
            activeThumbRef={activeThumbRef}
            extractLookNumber={extractLookNumber}
          />
        )}
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
    </>
  );
}

export default Viewer;
