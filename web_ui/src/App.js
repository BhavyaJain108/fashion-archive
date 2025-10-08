import React, { useState, useEffect } from 'react';
import SeasonsPanel from './components/SeasonsPanel';
import CollectionsPanel from './components/CollectionsPanel';
import ImageViewerPanel from './components/ImageViewerPanel';
import VideoWindow from './components/VideoModal';
import MenuBar from './components/MenuBar';
import FavouritesPanel from './components/FavouritesPanel';
import MyBrandsPanel from './components/MyBrandsPanel';
import { FashionArchiveAPI } from './services/api';

function App() {
  // Page State
  const [currentPage, setCurrentPage] = useState('high-fashion'); // 'high-fashion', 'favourites', or 'my-brands'
  
  // View State - specific to each page
  const [currentView, setCurrentView] = useState('standard'); // high-fashion: 'standard', favourites: 'view-all'
  
  // UI State - matches tkinter version exactly
  const [column2Activated, setColumn2Activated] = useState(false);
  const [column3Activated, setColumn3Activated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  
  // Data State
  const [seasons, setSeasons] = useState([]);
  const [selectedSeason, setSelectedSeason] = useState(null);
  const [collections, setCollections] = useState([]);
  const [selectedCollection, setSelectedCollection] = useState(null);
  const [currentImages, setCurrentImages] = useState([]);
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  
  // Streaming state (matches tkinter stream_collections_update)
  const [collectionsLoading, setCollectionsLoading] = useState(false);
  const [loadingProgress, setLoadingProgress] = useState({ page: 0, total: 0 });
  
  // UI Mode State
  const [galleryMode, setGalleryMode] = useState(false);
  const [zoomMode, setZoomMode] = useState(0); // 0=off, 1=2x, 2=3x
  const [isDownloading, setIsDownloading] = useState(false);
  
  // Video State
  const [videoModalOpen, setVideoModalOpen] = useState(false);
  const [currentVideoPath, setCurrentVideoPath] = useState(null);
  const [videoDownloadState, setVideoDownloadState] = useState('none'); // 'none', 'loading', 'ready'

  // Initialize - Load seasons on startup (matches tkinter)
  useEffect(() => {
    const loadSeasons = async () => {
      try {
        setIsLoading(true);
        const seasonsData = await FashionArchiveAPI.getSeasons();
        setSeasons(seasonsData);
        setIsLoading(false);
      } catch (error) {
        console.error('Error loading seasons:', error);
        setIsLoading(false);
      }
    };
    
    loadSeasons();
  }, []);

  // Handle season selection - show column 2 (collections) with progress tracking
  const handleSeasonSelect = async (season) => {
    setSelectedSeason(season);
    setColumn2Activated(true);
    setCollectionsLoading(true);
    setCollections([]);
    setLoadingProgress({ page: 0, total: 0 });
    
    try {
      // Load collections with progress tracking but show results all at once when complete
      const finalCollections = await FashionArchiveAPI.streamCollections(
        season.url,
        (streamData) => {
          if (streamData.error) {
            console.error('Stream error:', streamData.error);
            setCollectionsLoading(false);
            return;
          }
          
          if (!streamData.complete) {
            // Update progress only (don't show partial results)
            setLoadingProgress({
              page: streamData.page,
              total: streamData.total_collections
            });
          } else {
            // Show final complete data all at once
            if (streamData.collections) {
              setCollections(streamData.collections);
            }
            setCollectionsLoading(false);
          }
        }
      );
      
      // Ensure we have final data
      if (finalCollections) {
        setCollections(finalCollections);
      }
    } catch (error) {
      console.error('Error loading collections:', error);
      setCollections([]);
    } finally {
      setCollectionsLoading(false);
    }
  };

  // Handle designer/collection selection - show column 3 (images)
  const handleCollectionSelect = async (collection) => {
    // Prevent multiple simultaneous downloads (matches tkinter)
    if (isDownloading) {
      console.log('Download already in progress, ignoring selection');
      return;
    }
    
    // Check if same collection (matches tkinter duplicate prevention)
    if (selectedCollection && selectedCollection.url === collection.url) {
      console.log('Same collection selected, ignoring duplicate request');
      return;
    }
    
    setSelectedCollection(collection);
    setColumn3Activated(true);
    setIsDownloading(true);
    
    // Clear current video state (matches tkinter)
    setCurrentVideoPath(null);
    setVideoDownloadState('none');
    if (videoModalOpen) {
      setVideoModalOpen(false);
    }
    
    try {
      // Clean up previous downloads first (matches tkinter cleanup_previous_downloads)
      await FashionArchiveAPI.cleanupDownloads();
      
      // Clear current images immediately (matches tkinter)
      setCurrentImages([]);
      setCurrentImageIndex(0);
      
      // Download images (matches tkinter behavior)
      const imageData = await FashionArchiveAPI.downloadImages(collection);
      setCurrentImages(imageData.imagePaths || []);
      setCurrentImageIndex(0);
      
      // Set video state to ready for download (no automatic download)
      setVideoDownloadState('ready');
        
    } catch (error) {
      console.error('Error downloading images:', error);
      setCurrentImages([]);
    } finally {
      setIsDownloading(false);
    }
  };

  // Image navigation (matches tkinter behavior)
  const handlePrevImage = () => {
    if (currentImages.length > 0) {
      const newIndex = currentImageIndex > 0 
        ? currentImageIndex - 1 
        : currentImages.length - 1; // Wrap to last
      setCurrentImageIndex(newIndex);
    }
  };

  const handleNextImage = () => {
    if (currentImages.length > 0) {
      const newIndex = currentImageIndex < currentImages.length - 1
        ? currentImageIndex + 1
        : 0; // Wrap to first
      setCurrentImageIndex(newIndex);
    }
  };

  // Toggle gallery/single view (matches tkinter)
  const handleToggleGallery = () => {
    setGalleryMode(!galleryMode);
  };

  // Cycle zoom mode (matches tkinter)
  const handleCycleZoom = () => {
    setZoomMode((zoomMode + 1) % 3);
  };

  // Handle video button click - download or toggle video
  const handleVideoButton = async () => {
    if (videoDownloadState === 'ready') {
      // Start download
      setVideoDownloadState('loading');
      try {
        const videoPath = await FashionArchiveAPI.downloadVideo(selectedCollection);
        if (videoPath) {
          setCurrentVideoPath(videoPath);
          setVideoDownloadState('downloaded');
        } else {
          setVideoDownloadState('ready'); // Reset on failure
        }
      } catch (error) {
        console.error('Video download failed:', error);
        setVideoDownloadState('ready'); // Reset on failure
      }
    } else if (videoDownloadState === 'downloaded') {
      // Toggle video modal
      setVideoModalOpen(!videoModalOpen);
    }
  };

  // Keyboard navigation (matches tkinter)
  useEffect(() => {
    const handleKeyPress = (e) => {
      if (e.key === 'ArrowLeft') {
        handlePrevImage();
      } else if (e.key === 'ArrowRight') {
        handleNextImage();
      } else if (e.key === 'Escape' && videoModalOpen) {
        setVideoModalOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [currentImageIndex, currentImages.length, videoModalOpen]);

  // Page switching handlers
  const handlePageSwitch = (page) => {
    setCurrentPage(page);
    // Set default view for the page
    if (page === 'high-fashion') {
      setCurrentView('standard');
    } else if (page === 'favourites') {
      setCurrentView('view-all');
    } else if (page === 'my-brands') {
      setCurrentView('all-brands');
    }
  };

  // View mode switching handlers
  const handleViewChange = (viewMode) => {
    setCurrentView(viewMode);
  };

  if (isLoading) {
    return (
      <div className="columns-container">
        <div className="loading">
          <div className="mac-label">Loading Fashion Week Archive...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="columns-container">
      {/* Menu Bar - matches tkinter menu system */}
      <MenuBar 
        currentPage={currentPage}
        onPageSwitch={handlePageSwitch}
        currentView={currentView}
        onViewChange={handleViewChange}
      />
      
      {/* Title Bar - matches tkinter window title */}
      <div className="mac-title-bar" style={{ 
        position: 'fixed', 
        top: '20px', 
        left: 0, 
        right: 0, 
        zIndex: 100 
      }}>
        Fashion Week Archive Browser
      </div>

      {/* Main Content - offset by menu and title bars */}
      {currentPage === 'high-fashion' ? (
        <div style={{ display: 'flex', width: '100%', height: '100vh', paddingTop: '40px' }}>
          
          {/* Column 1: Seasons (Always visible) */}
          <div className="column" style={{ width: '300px' }}>
            <SeasonsPanel 
              seasons={seasons}
              selectedSeason={selectedSeason}
              onSeasonSelect={handleSeasonSelect}
            />
          </div>

          {/* Column 2: Collections (Visible after season selection) */}
          {column2Activated && (
            <div className="column" style={{ width: '400px' }}>
              <CollectionsPanel 
                collections={collections}
                selectedCollection={selectedCollection}
                onCollectionSelect={handleCollectionSelect}
                seasonTitle={selectedSeason?.name || ''}
                isLoading={collectionsLoading}
                loadingProgress={loadingProgress}
              />
            </div>
          )}

          {/* Column 3: Image Viewer (Visible after collection selection) */}
          {column3Activated && (
            <div className="column" style={{ flex: '1 1 auto', minWidth: 0 }}>
              <ImageViewerPanel 
                images={currentImages}
                currentImageIndex={currentImageIndex}
                galleryMode={galleryMode}
                zoomMode={zoomMode}
                isDownloading={isDownloading}
                videoDownloadState={videoDownloadState}
                designerName={selectedCollection?.designer || ''}
                selectedSeason={selectedSeason}
                selectedCollection={selectedCollection}
                onPrevImage={handlePrevImage}
                onNextImage={handleNextImage}
                onToggleGallery={handleToggleGallery}
                onCycleZoom={handleCycleZoom}
                onVideoButton={handleVideoButton}
                onImageSelect={setCurrentImageIndex}
              />
            </div>
          )}
        </div>
      ) : currentPage === 'favourites' ? (
        <FavouritesPanel currentView={currentView} />
      ) : currentPage === 'my-brands' ? (
        <MyBrandsPanel currentView={currentView} />
      ) : (
        <FavouritesPanel currentView={currentView} />
      )}

      {/* Video Window - Separate draggable window */}
      {videoModalOpen && currentVideoPath && (
        <VideoWindow 
          videoPath={currentVideoPath}
          onClose={() => setVideoModalOpen(false)}
        />
      )}
    </div>
  );
}

export default App;