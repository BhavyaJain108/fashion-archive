import React from 'react';
import { FashionArchiveAPI } from '../../shared/api';
import { cleanDesignerName } from '../../shared/lib/designerName';
import { lookLabel, lookCounter, lookAlt } from '../../shared/lib/lookLabel';
import { videoSeasonName } from './seasonName';
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
  imagesCollection,
  expectedCount,
  streamComplete,
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
  // What the reader is actually looking at, named. During the stale window
  // the status bar is naming the show that was asked for, so a failure
  // message that says only "could not load" leaves them unable to tell
  // which show the photographs under it belong to.
  const shownDesigner = imagesCollection
    && (imagesCollection.designer_name || imagesCollection.designer);
  const shownName = [
    shownDesigner ? cleanDesignerName(shownDesigner) : '',
    videoSeasonName(imagesCollection),
  ].filter(Boolean).join(' / ');

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
        {/* A failure with looks still on screen. The pane is not empty, so
            the placeholder below never runs, and before this there was no
            message anywhere: dimmed photographs, the other show's name in
            the status bar, and nothing to say the load had failed rather
            than still been running. On a failure the stale window never
            closes on its own, so "forever" was literal.

            It sits over the pane rather than inside its content because
            the dim is what it is explaining, and a child of a dimmed
            element cannot be less transparent than its parent. */}
        {imagesError && images.length > 0 && (
          <div className="hf2-stale-error ar-empty" role="alert">
            <span className="headline">Could not load this show</span>
            <span className="hf2-stale-error-sub">
              Still showing <span className="shown">{shownName || 'the previous show'}</span>
            </span>
          </div>
        )}

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
                {/* One number, not two. This row used to read
                    "LOOK 07 ☆ 3 / 12": the padded number parsed out of the
                    filename, and the position in the array, side by side and
                    both about the same photograph. When the word "LOOK" went
                    — it was a claim the data does not support, see
                    lookLabel.js — what was left was two bare numbers in two
                    formats, and a reader with no way to tell which was which.

                    The position is the half that survives, because it is the
                    half they can check: 3 of 12, against twelve thumbnails.
                    The filename number is an identifier, is frequently not
                    the designer's actual look number, and means nothing to
                    anyone reading it. It is not gone — it is still the
                    identity of every favourite, and the grid and the status
                    bar still print it — it just stops being a second
                    unexplained number beside this one. */}
                <div className="hf2-image-info">
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
                  {/* lookCounter, so this and the status bar are one
                      spelling of "n of m" rather than two that drift. */}
                  <span className="hf2-look-count">
                    {lookCounter(currentImageIndex + 1, images.length)}
                  </span>
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
            expectedCount={expectedCount}
            isStale={imagesStale}
            streamComplete={streamComplete}
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
