import React from 'react';
import { FashionArchiveAPI } from '../../shared/api';

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
}) {
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
                    alt={`Look ${extractLookNumber(imgPath, idx)}`}
                  />
                </div>
              ))}
            </div>
          </div>
  );
}

export default ThumbStrip;
