import React from 'react';
import { cleanDesignerName } from '../../shared/lib/designerName';

// The list of shows under the filters, and its header.
//
// Presentational: every value and every handler is a prop. `listLoading`
// arrives already resolved (designer mode reads a different loading flag from
// the archive list), and `designerRows` is here only for the "shown/loaded"
// count the fallback path puts in the header.
function ShowList({
  designerMode,
  searchText,
  exitDesigner,
  visibleCollections,
  indexReady,
  cursor,
  designerRows,
  handleListScroll,
  listLoading,
  listError,
  selectedCollection,
  handleCollectionSelect,
  designerLoading,
  loadingMore,
}) {
  return (
    <>
        {/* Collections */}
        <div className="hf2-collections-area">
          <div className="hf2-collections-header">
            {designerMode || searchText ? (
              <>
                <button type="button" className="hf2-designer-exit" onClick={exitDesigner}>
                  ← Archive
                </button>
                <span className="hf2-designer-name"
                      title={designerMode ? designerMode.name : `Search: ${searchText}`}>
                  {designerMode ? designerMode.name : `“${searchText}”`}
                </span>
              </>
            ) : (
              <span>Shows</span>
            )}
            {visibleCollections.length > 0 && (
              <span className="count">
                {indexReady
                  // Exact, and the whole point of holding the archive: the
                  // list can say how many shows match, not how many it has
                  // managed to fetch so far.
                  ? cursor.total.toLocaleString()
                  : designerMode && visibleCollections.length !== designerRows.length
                    ? `${visibleCollections.length}/${designerRows.length}`
                    : `${visibleCollections.length}${cursor.hasMore ? '+' : ''}`}
              </span>
            )}
          </div>
          <div className="hf2-collections-scroll" onScroll={handleListScroll}>
            {listLoading && visibleCollections.length === 0 ? (
              <div className="hf2-collections-loading">Loading…</div>
            ) : listError ? (
              <div className="hf2-collections-error">
                <span>Could not load shows</span>
                <span className="detail">{listError}</span>
              </div>
            ) : visibleCollections.length === 0 ? (
              <div className="hf2-collections-empty">
                {designerMode
                  ? `${designerMode.name} has no shows matching these filters`
                  : 'No shows match these filters'}
              </div>
            ) : (
              <>
                {visibleCollections.map((col, idx) => (
                  <div
                    key={col.collection_id || col.url}
                    className={`hf2-collection-item ${col.url === selectedCollection?.url ? 'selected' : ''}`}
                    onClick={() => handleCollectionSelect(col)}
                  >
                    <span className="num">{String(idx + 1).padStart(3, '0')}</span>
                    <span className="body">
                      <span className="name">{cleanDesignerName(col.designer)}</span>
                      {/* Abbreviated to fit the column; the tooltip has it in
                          full for the rows where the tail still gets cut. */}
                      {col.subtitle && (
                        <span className="sub" title={col.subtitle}>{col.subtitle}</span>
                      )}
                    </span>
                  </div>
                ))}
                {designerMode && designerLoading && (
                  <div className="hf2-collections-more">Loading more…</div>
                )}
                {!designerMode && cursor.hasMore && (
                  <div className="hf2-collections-more">
                    {loadingMore ? 'Loading more…' : 'Scroll for more'}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
    </>
  );
}

export default ShowList;
