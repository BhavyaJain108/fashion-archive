import React from 'react';

// The video panel in single view: the resizable YouTube embed plus its
// controls. Presentational: every value is a prop, and it holds no state of
// its own — the player itself, the resize drag, play/pause and seeking all
// live in the parent.
function VideoPanel({
  videoHeight,
  isPlaying,
  currentTime,
  duration,
  playerContainerRef,
  onResizeStart,
  onTogglePlay,
  onSeek,
  formatTime,
  getQualityLabel,
}) {
  return (
                <div className="hf2-video-side">
                  {/* Resizable video area */}
                  <div className="hf2-video-resizable">
                    {/* Top resize bar */}
                    <div className="hf2-resize-bar" onMouseDown={(e) => onResizeStart(e, 'top')} />

                    {/* Video container with overflow hidden */}
                    <div className="hf2-video-wrapper" style={{ height: videoHeight }}>
                      <div className="hf2-video-frame">
                        <div ref={playerContainerRef} className="hf2-youtube-player" />
                        {/* Every piece of YouTube's UI that still shows with
                            controls off — the title bar, the share and watch
                            -later buttons, the pause overlay — appears in
                            response to hovering or clicking the iframe. This
                            takes those events, so none of it ever appears,
                            and passes the click to our own play control. */}
                        <div
                          className="hf2-video-shield"
                          onClick={onTogglePlay}
                          title={isPlaying ? 'Pause' : 'Play'}
                        />
                      </div>
                    </div>

                    {/* Bottom resize bar */}
                    <div className="hf2-resize-bar" onMouseDown={(e) => onResizeStart(e, 'bottom')} />
                  </div>

                  {/* Fixed controls at bottom */}
                  <div className="hf2-video-controls">
                    <button className="hf2-play-btn" onClick={onTogglePlay}>
                      {isPlaying ? '❚❚' : '▶'}
                    </button>
                    <div className="hf2-progress-bar" onClick={onSeek}>
                      <div
                        className="hf2-progress-fill"
                        style={{ width: `${duration ? (currentTime / duration) * 100 : 0}%` }}
                      />
                    </div>
                    <span className="hf2-time">
                      {formatTime(currentTime)} / {formatTime(duration)}
                    </span>
                    <span className="hf2-quality-readout"
                          title="What YouTube is serving. The embed API cannot set this.">
                      {getQualityLabel()}
                    </span>
                  </div>
                </div>
  );
}

export default VideoPanel;
