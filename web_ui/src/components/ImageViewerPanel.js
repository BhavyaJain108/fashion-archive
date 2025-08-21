import React, { useState, useEffect } from 'react';
import { FashionArchiveAPI } from '../services/api';

function ImageViewerPanel({ 
  images, 
  currentImageIndex, 
  galleryMode, 
  zoomMode,
  isDownloading,
  videoDownloadState,
  designerName,
  selectedSeason,
  selectedCollection,
  onPrevImage, 
  onNextImage, 
  onToggleGallery, 
  onCycleZoom,
  onVideoButton,
  onImageSelect 
}) {
  // Favourites state
  const [isFavourite, setIsFavourite] = useState(false);
  const [favouriteLoading, setFavouriteLoading] = useState(false);

  // Get video button content based on state
  const getVideoButtonContent = () => {
    switch (videoDownloadState) {
      case 'ready':
        return 'Load Video';
      case 'loading':
        return 'Loading...';
      case 'downloaded':
        return '📹';
      default:
        return null;
    }
  };

  // Get current image path
  const getCurrentImagePath = () => {
    if (images.length === 0 || currentImageIndex >= images.length) {
      return null;
    }
    return images[currentImageIndex];
  };

  // Extract look number from filename (matches tkinter logic)
  const getLookInfo = () => {
    const imagePath = getCurrentImagePath();
    if (!imagePath) return { lookNumber: 0, total: images.length };
    
    const filename = imagePath.split('/').pop() || '';
    const lookMatch = filename.match(/-(\d+)\./);
    const lookNumber = lookMatch ? parseInt(lookMatch[1]) : currentImageIndex + 1;
    
    return { lookNumber, total: images.length };
  };

  // Check if current look is favourited
  useEffect(() => {
    const checkFavouriteStatus = async () => {
      if (!selectedSeason || !selectedCollection || images.length === 0) {
        setIsFavourite(false);
        return;
      }

      const { lookNumber } = getLookInfo();
      try {
        const isF = await FashionArchiveAPI.checkFavourite(
          selectedSeason.url,
          selectedCollection.url,
          lookNumber
        );
        setIsFavourite(isF);
      } catch (error) {
        console.error('Error checking favourite status:', error);
        setIsFavourite(false);
      }
    };

    checkFavouriteStatus();
  }, [selectedSeason, selectedCollection, currentImageIndex, images]);

  // Handle favourite toggle
  const handleFavouriteToggle = async () => {
    if (!selectedSeason || !selectedCollection || images.length === 0) {
      return;
    }

    const { lookNumber } = getLookInfo();
    const currentImagePath = getCurrentImagePath();

    setFavouriteLoading(true);

    try {
      if (isFavourite) {
        // Remove from favourites
        const result = await FashionArchiveAPI.removeFavourite(
          selectedSeason.url,
          selectedCollection.url,
          lookNumber
        );
        
        if (result.success) {
          setIsFavourite(false);
        }
      } else {
        // Add to favourites
        const result = await FashionArchiveAPI.addFavourite(
          selectedSeason,
          selectedCollection,
          { lookNumber, total: images.length },
          currentImagePath
        );
        
        if (result.success) {
          setIsFavourite(true);
        }
      }
    } catch (error) {
      console.error('Error toggling favourite:', error);
    } finally {
      setFavouriteLoading(false);
    }
  };

  if (isDownloading) {
    return (
      <div className="mac-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <div className="mac-label title">Downloading images...</div>
        <div className="loading">
          <div className="mac-label">Please wait...</div>
        </div>
      </div>
    );
  }

  if (galleryMode) {
    // Gallery Grid View (matches tkinter 4-column layout)
    return (
      <div className="mac-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        {/* Gallery Header */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '8px' }}>
          <div className="mac-label title" style={{ flex: 1, margin: 0 }}>
            {designerName} Gallery
          </div>
          <button 
            className="mac-button" 
            onClick={onToggleGallery}
            style={{ marginLeft: '8px' }}
          >
            single
          </button>
        </div>

        {/* Gallery Grid */}
        <div className="gallery-grid mac-scrollbar" style={{ flex: 1 }}>
          {images.map((imagePath, index) => (
            <div
              key={index}
              className={`gallery-item ${index === currentImageIndex ? 'selected' : ''}`}
              onClick={() => onImageSelect(index)}
              onDoubleClick={() => {
                onImageSelect(index); // Select the image first
                onToggleGallery(); // Then switch to single view
              }}
            >
              <div className="gallery-image-container">
                <img 
                  src={FashionArchiveAPI.getImageUrl(imagePath)}
                  alt={`Look ${index + 1}`}
                  onError={(e) => {
                    e.target.style.display = 'none';
                  }}
                />
              </div>
              <div className="gallery-look-label">
                Look {(() => {
                  // Extract look number from filename (same logic as single view)
                  const filename = imagePath.split('/').pop() || '';
                  const lookMatch = filename.match(/-(\d+)\./);
                  return lookMatch ? parseInt(lookMatch[1]) : index + 1;
                })()}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Single Image View (matches tkinter default view)
  const { lookNumber, total } = getLookInfo();
  const currentImagePath = getCurrentImagePath();

  return (
    <div className="mac-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Title - matches other columns exactly */}
      <div className="mac-label title">
        {total > 0 ? `Look ${lookNumber} / ${total}` : designerName}
      </div>

      {/* Controls bar */}
      <div style={{ display: 'flex', padding: '4px 8px', gap: '8px', alignItems: 'center' }}>
        <button 
          className="mac-button" 
          onClick={onToggleGallery}
          disabled={images.length === 0}
        >
          gallery
        </button>
        
        {getVideoButtonContent() && (
          <button 
            className="mac-button" 
            onClick={onVideoButton}
            disabled={videoDownloadState === 'loading'}
            style={{ 
              opacity: videoDownloadState === 'loading' ? 0.6 : 1,
              cursor: videoDownloadState === 'loading' ? 'not-allowed' : 'pointer'
            }}
          >
            {getVideoButtonContent()}
          </button>
        )}
        
        <div style={{ flex: 1 }}></div>
        
        <button 
          className="mac-button"
          onClick={handleFavouriteToggle}
          disabled={images.length === 0 || favouriteLoading || !selectedSeason || !selectedCollection}
          style={{ 
            backgroundColor: isFavourite ? '#ff6b6b' : 'transparent',
            color: isFavourite ? '#fff' : '#000',
            opacity: favouriteLoading ? 0.6 : 1,
            transition: 'none'
          }}
        >
          {favouriteLoading ? '...' : (isFavourite ? '❤️' : '🤍')}
        </button>
      </div>

      {/* Main Image Display - matches other columns flex pattern */}
      <div 
        className="image-container" 
        style={{ 
          flex: 1,
          margin: '8px 0',
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          overflow: 'hidden'
        }}
      >
        {currentImagePath ? (
          <img 
            src={FashionArchiveAPI.getImageUrl(currentImagePath)}
            alt={`Look ${lookNumber}`}
            style={{ 
              maxWidth: '100%', 
              maxHeight: '100%', 
              objectFit: 'contain'
            }}
            onError={(e) => {
              e.target.alt = 'Image not found';
            }}
          />
        ) : (
          <div className="mac-label">No images loaded</div>
        )}
      </div>

      {/* Bottom Navigation - matches other columns bottom section */}
      <div style={{ padding: '8px' }}>
        <div style={{ 
          display: 'flex', 
          alignItems: 'center',
          borderTop: '1px solid var(--mac-border)',
          backgroundColor: 'var(--mac-bg)',
          padding: '8px 0'
        }}>
          <button 
            className="mac-button" 
            onClick={onPrevImage}
            disabled={images.length <= 1}
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
            {images.length > 0 ? `${currentImageIndex + 1} of ${images.length}` : ''}
          </div>
          
          <button 
            className="mac-button" 
            onClick={onNextImage}
            disabled={images.length <= 1}
            style={{ minWidth: '80px' }}
          >
            Next ▶
          </button>
        </div>
      </div>
    </div>
  );
}

export default ImageViewerPanel;