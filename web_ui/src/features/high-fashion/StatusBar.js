import React from 'react';
import { cleanDesignerName } from '../../shared/lib/designerName';
import { videoSeasonName } from './seasonName';

// The bottom readout. Presentational: every value is a prop, and it holds no
// state of its own. The two label helpers are imported rather than passed in —
// they are pure module functions, and they were only ever props because they
// were not exported from anywhere.
function StatusBar({
  selectedCollection,
  filters,
  imagesLength,
  currentLookNumber,
}) {
  return (
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
          {imagesLength > 0 && (
            <>LOOK <span className="active">{String(currentLookNumber).padStart(2, '0')}</span> / {imagesLength}</>
          )}
        </span>
      </div>
  );
}

export default StatusBar;
