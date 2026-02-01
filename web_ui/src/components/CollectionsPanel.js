import React from 'react';

function CollectionsPanel({ collections, selectedCollection, onCollectionSelect, seasonTitle, isLoading, loadingProgress }) {
  return (
    <div className="mac-panel collections-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Dynamic Title - matches tkinter behavior */}
      <div className="mac-label title">
        {seasonTitle || 'Collections'}
      </div>

      {/* Loading Progress (matches tkinter stream_collections_update) */}
      {isLoading && (
        <div style={{ padding: '4px 8px', fontSize: '11px', color: '#666' }}>
          Loading page {loadingProgress.page}... {loadingProgress.total} collections found
        </div>
      )}

      {/* Collections List - matches tkinter streaming updates */}
      <div className="mac-listbox mac-scrollbar" style={{ flex: 1, margin: '8px 0' }}>
        {collections.length === 0 && !isLoading ? (
          <div className="mac-listbox-item">No collections found</div>
        ) : collections.length === 0 && isLoading ? (
          <div className="mac-listbox-item">Loading collections...</div>
        ) : (
          collections.map((collection, index) => (
            <div
              key={`${collection.url}-${index}`}
              className={`mac-listbox-item ${selectedCollection?.url === collection.url ? 'selected' : ''}`}
              onClick={() => onCollectionSelect(collection)}
            >
              📁 {collection.designer}
            </div>
          ))
        )}
        
        {/* Show loading indicator at bottom while streaming */}
        {isLoading && collections.length > 0 && (
          <div className="mac-listbox-item" style={{ fontStyle: 'italic', opacity: 0.7 }}>
            Loading more collections...
          </div>
        )}
      </div>
    </div>
  );
}

export default CollectionsPanel;