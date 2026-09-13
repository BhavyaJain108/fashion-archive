import React from 'react';
import { FashionArchiveAPI } from '../../shared/api';
import { lookAlt } from '../../shared/lib/lookLabel';

// The horizontal thumbnail strip in single view. Presentational: every value
// is a prop, and it holds no state of its own. The centring effect (which
// scrolls the strip so the active thumb stays in view) stays in the parent,
// which is why the two refs come in as props rather than being created here.
function ThumbStrip({
  images,
  currentImageIndex,
  onSelect,
  isFavourite,
  stripRef,
  activeThumbRef,
  extractLookNumber,
  expectedCount = 0,
  isStale = false,
  // True once the stream has finished delivering for this collection,
  // however many looks that turned out to be — a look that fails to
  // download does not fail the stream, it is just never coming, and a
  // ghost slot drawn for it would pulse forever. Defaults to false so a
  // caller that has not wired the flag through yet keeps today's ghosts.
  streamComplete = false,
}) {
  // The looks the stream has promised and not yet delivered, drawn as empty
  // slots. The strip is then its final width from the first photograph, and
  // the show visibly fills in rather than appearing all at once.
  //
  // Gated on !isStale, not clamped at zero. During the stale window
  // `expectedCount` has already been reset to the count of the show that was
  // ASKED for while `images` still holds the previous show's photographs, so
  // the subtraction is meaningless in both directions: negative before the
  // new meta arrives, and a different show's total after it. Clamping hides
  // the negative and leaves the other half of the lie standing — the
  // previous show's twelve thumbnails with the new show's thirty-eight
  // slots behind them, under the new show's name. Gating is the only version
  // where the strip and the status bar describe the same show.
  //
  // Also gated on !streamComplete: once the stream itself has said it is
  // done, whatever arrived is final. `expectedCount` can still sit above
  // `images.length` — a look that failed to download is not coming — and a
  // ghost drawn for it would be a placeholder for a photograph that will
  // never land.
  const ghostCount = !isStale && !streamComplete && expectedCount > images.length
    ? expectedCount - images.length
    : 0;

  return (
          <div className="hf2-thumb-strip-container">
            <div className="hf2-thumb-strip" ref={stripRef}>
              {images.map((imgPath, idx) => (
                <div
                  key={imgPath}
                  ref={idx === currentImageIndex ? activeThumbRef : null}
                  className={`hf2-thumb ${idx === currentImageIndex ? 'active' : ''} ${
                    isFavourite(extractLookNumber(imgPath, idx)) ? 'kept' : ''}`}
                  onClick={() => onSelect(idx)}
                >
                  <img
                    src={FashionArchiveAPI.getImageUrl(imgPath)}
                    alt={lookAlt(extractLookNumber(imgPath, idx))}
                  />
                </div>
              ))}
              {/* A ghost carries .hf2-thumb itself rather than its own copy of
                  44x60, so it is by construction the exact box the photograph
                  will move into and nothing shifts sideways when one lands.
                  It holds no image, no handler and no tabindex: there is
                  nothing there to choose yet, so it is inert and out of the
                  tab order, and aria-hidden keeps thirty-eight empty divs out
                  of a screen reader's way. */}
              {Array.from({ length: ghostCount }, (_, i) => (
                <div
                  key={`ghost-${i}`}
                  className="hf2-thumb hf2-thumb-ghost"
                  aria-hidden="true"
                />
              ))}
            </div>
          </div>
  );
}

export default ThumbStrip;
