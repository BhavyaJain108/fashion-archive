import React, { useState, useEffect } from 'react';
import { FashionArchiveAPI } from '../services/api';

function FavouritesPanel({ currentView }) {
  const [favourites, setFavourites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({});
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Apply view-specific sorting and filtering
  const getDisplayFavourites = () => {
    let displayFavourites = [...favourites];
    
    switch (currentView) {
      case 'view-all':
        // Sort by date added (latest to oldest)
        displayFavourites.sort((a, b) => new Date(b.date_added) - new Date(a.date_added));
        break;
      case 'by-collection':
        // Group by collection, then sort collections alphabetically
        displayFavourites.sort((a, b) => {
          const collectionA = a.collection.designer.toLowerCase();
          const collectionB = b.collection.designer.toLowerCase();
          if (collectionA !== collectionB) {
            return collectionA.localeCompare(collectionB);
          }
          // Within same collection, sort by look number
          return a.look.number - b.look.number;
        });
        break;
      default:
        // Keep original order
        break;
    }
    
    return displayFavourites;
  };

  // Get grouped collections for by-collection view
  const getGroupedCollections = () => {
    if (currentView !== 'by-collection') return [];
    
    const displayFavourites = getDisplayFavourites();
    const groups = [];
    let currentCollection = null;
    let currentGroup = null;
    
    displayFavourites.forEach((favourite, index) => {
      const collectionKey = `${favourite.collection.designer}-${favourite.season.name}`;
      
      if (collectionKey !== currentCollection) {
        // Start new collection group
        currentCollection = collectionKey;
        currentGroup = {
          collection: favourite.collection,
          season: favourite.season,
          items: [],
          startIndex: index
        };
        groups.push(currentGroup);
      }
      
      currentGroup.items.push({
        ...favourite,
        originalIndex: index
      });
    });
    
    return groups;
  };

  const displayFavourites = getDisplayFavourites();

  // Load favourites on component mount
  useEffect(() => {
    loadFavourites();
    loadStats();
  }, []);

  const loadFavourites = async () => {
    try {
      console.log('FavouritesPanel: Starting to load favourites...');
      setLoading(true);
      const favs = await FashionArchiveAPI.getFavourites();
      console.log('FavouritesPanel: Received favourites:', favs);
      console.log('FavouritesPanel: Favourites length:', favs.length);
      setFavourites(favs);
      if (favs.length > 0 && selectedIndex >= favs.length) {
        setSelectedIndex(0);
      }
    } catch (error) {
      console.error('FavouritesPanel: Error loading favourites:', error);
    } finally {
      setLoading(false);
      console.log('FavouritesPanel: Loading complete');
    }
  };

  const loadStats = async () => {
    try {
      const stats = await FashionArchiveAPI.getFavouriteStats();
      setStats(stats);
    } catch (error) {
      console.error('Error loading stats:', error);
    }
  };

  const removeFavourite = async (favourite) => {
    try {
      const result = await FashionArchiveAPI.removeFavourite(
        favourite.season.url,
        favourite.collection.url,
        favourite.look.number
      );
      
      if (result.success) {
        // Remove from local state
        const newFavourites = favourites.filter(f => f.id !== favourite.id);
        setFavourites(newFavourites);
        
        // Adjust selected index if needed
        if (selectedIndex >= newFavourites.length && newFavourites.length > 0) {
          setSelectedIndex(newFavourites.length - 1);
        } else if (newFavourites.length === 0) {
          setSelectedIndex(0);
        }
        
        loadStats(); // Refresh stats
      }
    } catch (error) {
      console.error('Error removing favourite:', error);
    }
  };

  // Navigation handlers
  const handlePrevFavourite = () => {
    if (displayFavourites.length > 0) {
      const newIndex = selectedIndex > 0 ? selectedIndex - 1 : displayFavourites.length - 1;
      setSelectedIndex(newIndex);
    }
  };

  const handleNextFavourite = () => {
    if (displayFavourites.length > 0) {
      const newIndex = selectedIndex < displayFavourites.length - 1 ? selectedIndex + 1 : 0;
      setSelectedIndex(newIndex);
    }
  };

  const handleGallerySelect = (index) => {
    setSelectedIndex(index);
  };

  if (loading) {
    return (
      <div className="columns-container">
        <div style={{ 
          display: 'flex', 
          height: '100vh', 
          paddingTop: '40px',
          alignItems: 'center',
          justifyContent: 'center'
        }}>
          <div className="loading">
            <div className="mac-label">Loading favourites...</div>
          </div>
        </div>
      </div>
    );
  }

  if (favourites.length === 0) {
    return (
      <div className="columns-container">
        <div style={{ 
          display: 'flex', 
          height: '100vh', 
          paddingTop: '40px',
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'column',
          gap: '20px'
        }}>
          <div className="mac-panel" style={{ 
            padding: '40px',
            textAlign: 'center',
            maxWidth: '600px'
          }}>
            <div style={{ fontSize: '48px', marginBottom: '20px' }}>🤍</div>
            <div style={{ fontSize: '18px', color: '#666', marginBottom: '10px' }}>
              No favourites yet
            </div>
            <div style={{ fontSize: '14px', color: '#999' }}>
              Browse High Fashion collections and click the heart button to save your favourite looks here
            </div>
          </div>
        </div>
      </div>
    );
  }

  const currentFavourite = displayFavourites[selectedIndex];

  return (
    <div className="columns-container">
      {/* Title Bar */}
      <div className="mac-title-bar" style={{ 
        position: 'fixed', 
        top: '20px', 
        left: 0, 
        right: 0, 
        zIndex: 100 
      }}>
        My Favourites - {stats.total_favourites || 0} looks from {stats.unique_designers || 0} designers
      </div>

      {/* Split Layout */}
      <div style={{ display: 'flex', height: '100vh', paddingTop: '40px' }}>
        
        {/* Left: Gallery */}
        <div className="column" style={{ width: '50%' }}>
          <div className="mac-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            {/* Gallery Grid */}
            <div className="mac-scrollbar" style={{ 
              flex: 1,
              padding: '8px',
              overflowY: 'auto'
            }}>
              {currentView === 'by-collection' ? (
                // Collection-grouped view
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  {getGroupedCollections().map((group, groupIndex) => (
                    <div key={`${group.collection.designer}-${group.season.name}`}>
                      {/* Collection Header */}
                      <div style={{ 
                        fontSize: '14px', 
                        fontWeight: 'bold', 
                        marginBottom: '8px',
                        paddingBottom: '4px',
                        borderBottom: '1px solid var(--mac-border)'
                      }}>
                        {group.collection.designer}
                      </div>
                      
                      {/* Collection Images Grid */}
                      <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
                        gap: '8px',
                        marginBottom: '8px',
                        width: '100%'
                      }}>
                        {group.items.map((favourite) => (
                          <div
                            key={favourite.id}
                            className={`gallery-item ${favourite.originalIndex === selectedIndex ? 'selected' : ''}`}
                            onClick={() => handleGallerySelect(favourite.originalIndex)}
                          >
                            <div className="gallery-image-container">
                              <img 
                                src={FashionArchiveAPI.getImageUrl(favourite.image_path)}
                                alt={`Look ${favourite.look.number}`}
                              />
                            </div>
                            <div className="gallery-look-label">
                              Look {favourite.look.number}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                // Standard grid view
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
                  gap: '8px',
                  width: '100%'
                }}>
                  {displayFavourites.map((favourite, index) => (
                    <div
                      key={favourite.id}
                      className={`gallery-item ${index === selectedIndex ? 'selected' : ''}`}
                      onClick={() => handleGallerySelect(index)}
                    >
                      <div className="gallery-image-container">
                        <img 
                          src={FashionArchiveAPI.getImageUrl(favourite.image_path)}
                          alt={`Look ${favourite.look.number}`}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right: Single Image View */}
        <div className="column" style={{ flex: 1 }}>
          <div className="mac-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            {/* Information Panel */}
            <div style={{ 
              padding: '16px',
              borderBottom: '1px solid var(--mac-border)',
              backgroundColor: 'var(--mac-bg)',
              position: 'relative'
            }}>
              {/* Remove button - top right */}
              <button 
                className="mac-button"
                onClick={() => removeFavourite(currentFavourite)}
                style={{ 
                  position: 'absolute',
                  top: '16px',
                  right: '16px',
                  backgroundColor: '#ff6b6b',
                  color: '#fff',
                  fontSize: '12px'
                }}
              >
                Remove ❤️
              </button>
              
              <div style={{ fontSize: '16px', fontWeight: 'bold', marginBottom: '8px', paddingRight: '120px' }}>
                {currentFavourite.collection.designer}
              </div>
              <div style={{ fontSize: '14px', color: '#666', marginBottom: '8px' }}>
                {currentFavourite.season.name}
              </div>
              <div style={{ fontSize: '12px', color: '#999', marginBottom: '12px' }}>
                Look {currentFavourite.look.number} of {currentFavourite.look.total}
              </div>
              <div style={{ fontSize: '11px', color: '#999' }}>
                Added: {new Date(currentFavourite.date_added).toLocaleDateString()}
              </div>
            </div>

            {/* Main Image */}
            <div style={{ 
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: 0,
              overflow: 'hidden',
              padding: '8px'
            }}>
              <img 
                src={FashionArchiveAPI.getImageUrl(currentFavourite.image_path)}
                alt={`Look ${currentFavourite.look.number}`}
                style={{ 
                  maxWidth: '100%',
                  maxHeight: '100%',
                  objectFit: 'contain'
                }}
                onError={(e) => {
                  e.target.alt = 'Image not found';
                  e.target.style.background = '#f0f0f0';
                }}
              />
            </div>

            {/* Navigation Controls */}
            <div style={{ 
              display: 'flex', 
              alignItems: 'center', 
              padding: '8px',
              borderTop: '1px solid var(--mac-border)',
              backgroundColor: 'var(--mac-bg)'
            }}>
              <button 
                className="mac-button" 
                onClick={handlePrevFavourite}
                disabled={displayFavourites.length <= 1}
                style={{ minWidth: '80px' }}
              >
                ◀ Previous
              </button>
              
              <div style={{ 
                flex: 1, 
                textAlign: 'center',
                fontSize: '12px',
                color: '#666'
              }}>
                {selectedIndex + 1} of {displayFavourites.length}
              </div>
              
              <button 
                className="mac-button" 
                onClick={handleNextFavourite}
                disabled={displayFavourites.length <= 1}
                style={{ minWidth: '80px' }}
              >
                Next ▶
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default FavouritesPanel;