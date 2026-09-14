import React from 'react';
import { FashionArchiveAPI } from '../../shared/api';
import { lookAlt } from '../../shared/lib/lookLabel';
import { pendingLooks } from './pendingLooks';

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
  // One empty slot per look the stream has promised and not yet delivered,
  // so the strip is its final width from the first photograph and the show
  // visibly fills in rather than appearing all at once.
  //
  // The count comes from pendingLooks, which is also what the status bar
  // turns into the word "arriving" — the two are the same sentence, and
  // were the same arithmetic written out twice with nothing keeping them
  // that way. Every reason the answer is zero is stated there.
  const ghostCount = pendingLooks({
    imagesLength: images.length, expectedCount, isStale, streamComplete,
  });

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
