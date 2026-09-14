import React from 'react';
import { cleanDesignerName } from '../../shared/lib/designerName';
import { videoSeasonName } from './seasonName';
import { lookLabel } from '../../shared/lib/lookLabel';
import { pendingLooks } from './pendingLooks';

// The bottom readout. Presentational: every value is a prop, and it holds no
// state of its own. The two label helpers are imported rather than passed in —
// they are pure module functions, and they were only ever props because they
// were not exported from anywhere.
//
// The one rule this component has: the name and the numbers describe the SAME
// show. They come from different places — the name from whichever show is
// selected, the numbers from whichever photographs are on screen — and for
// the whole of the stale window those are two different shows. The bar used
// to print the show you had asked for beside the count of the show you were
// still looking at: "Prada ... 34 / 40", where 34 of 40 was Gucci's. So the
// name follows the photographs (`imagesCollection`), and while a different
// show is on its way the counter slot says so instead of counting.
function StatusBar({
  selectedCollection,
  imagesCollection,
  filters,
  imagesLength,
  expectedCount = 0,
  currentLookNumber,
  isStale = false,
  // True once the stream has finished delivering for this collection,
  // however many looks that turned out to be. A look that fails to
  // download does not fail the stream — it is logged and skipped — so
  // `expectedCount` can sit above `imagesLength` forever with nothing else
  // ever coming. Defaults to false so a caller that has not wired the flag
  // through yet keeps today's "arriving".
  streamComplete = false,
}) {
  // Which show the reader is actually looking at. Before the first show of a
  // session has landed anything there are no photographs to belong to
  // anyone, and naming the one that was asked for is then the only answer
  // there is — and an honest one, because there are no numbers beside it.
  const shownCollection = imagesCollection || selectedCollection;

  // `expectedCount` is the selected show's total, from its stream's meta
  // event, which arrives BEFORE its first photograph. So during the stale
  // window it is already the new show's number while `currentLookNumber`
  // is still the old show's position — the two must never be printed
  // together, which is what !isStale buys. A count of 0 means meta has not
  // arrived at all, and "07 / 0" is worse than no counter — except once the
  // stream is complete, when there is nothing left to wait on and a total
  // of 0 is simply true.
  const counting = !isStale && (streamComplete || expectedCount > 0);

  // The denominator once the stream is done is what actually arrived, not
  // what it once promised: a look that failed to download is never coming,
  // and "12 / 38 arriving" forever is a lie about a stream that ended
  // minutes ago. Mid-flight, the promised total is still the honest one —
  // it is what "arriving" counts down to.
  const total = streamComplete ? imagesLength : expectedCount;

  // The same count the thumbnail strip draws as empty slots. This was an
  // independent formula that happened to agree with that one; it is now the
  // same call, so the word and the slots can only appear together.
  const arriving = pendingLooks({
    imagesLength, expectedCount, isStale, streamComplete,
  }) > 0;

  return (
      <div className="hf2-status-bar">
        <span className="hf2-status-path">
          {shownCollection ? (
            <>
              {videoSeasonName(shownCollection)}
              {shownCollection.gender && <> / {shownCollection.gender}</>}
              {' / '}
              <span className="active">{cleanDesignerName(shownCollection.designer)}</span>
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
          {counting && (
            // Two spans rather than lookCounter()'s single string, because
            // .hf2-status-look .active is what blackens the look you are on
            // against the grey of the total. The text is character for
            // character what lookCounter(currentLookNumber, expectedCount)
            // returns, and a test holds it to that.
            <>
              <span className="active">{lookLabel(currentLookNumber)}</span> / {total}
              {arriving && <> <span className="hf2-status-arriving">arriving</span></>}
            </>
          )}
          {isStale && shownCollection && (
            <span className="hf2-status-arriving">loading</span>
          )}
        </span>
      </div>
  );
}

export default StatusBar;
