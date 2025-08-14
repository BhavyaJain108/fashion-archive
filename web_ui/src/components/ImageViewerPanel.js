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
  onPrevImage, 
  onNextImage, 
  onToggleGallery, 
  onCycleZoom,
  onVideoButton,
  onImageSelect 
}) {
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
      {/* Header with title and status */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '8px' }}>
        <div className="mac-label title" style={{ flex: 1, margin: 0 }}>
          {total > 0 ? `Look ${lookNumber} / ${total}` : designerName}
        </div>
        <div className="mac-label" style={{ fontSize: '12px', color: '#666' }}>
          {/* Status info can go here */}
        </div>
      </div>

      {/* Top Controls (matches tkinter layout) */}
      <div style={{ display: 'flex', padding: '8px', gap: '8px' }}>
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
      </div>

      {/* Main Image Display */}
      <div 
        className="image-container" 
        style={{ 
          flex: 1, 
          position: 'relative', 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          minHeight: 0, // Allow flex shrinking
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
              width: 'auto',
              height: 'auto',
              objectFit: 'contain',
              display: 'block'
            }}
            onError={(e) => {
              e.target.alt = 'Image not found';
              e.target.style.background = '#f0f0f0';
            }}
          />
        ) : (
          <div className="mac-label">No images loaded</div>
        )}
      </div>

      {/* Bottom Navigation (matches tkinter) - Always visible */}
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        padding: '8px',
        borderTop: '1px solid var(--mac-border)',
        backgroundColor: 'var(--mac-bg)',
        flexShrink: 0 // Prevent shrinking
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
  );
}

export default ImageViewerPanel;