import React, { useState, useEffect } from 'react';
import SeasonsPanel from './components/SeasonsPanel';
import CollectionsPanel from './components/CollectionsPanel';
import ImageViewerPanel from './components/ImageViewerPanel';
import VideoWindow from './components/VideoModal';
import FavouritesPanel from './components/FavouritesPanel';
import MyBrandsPanel from './components/MyBrandsPanel';
import AuthPanel from './auth/AuthPanel';
import HighFashionV2 from './components/HighFashionV2';
import { FashionArchiveAPI } from './services/api';

function App() {
  // Authentication State.
  //
  // There is no token here any more. The session lives in an HttpOnly cookie
  // the browser attaches automatically and this code cannot read, so the only
  // question the UI can ask is "does /api/auth/me answer?".
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [currentUser, setCurrentUser] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);

  // Set from the URL when arriving via an emailed link.
  const [authMode, setAuthMode] = useState(null);
  const [authNotice, setAuthNotice] = useState('');
  const [resetToken, setResetToken] = useState(null);
  
  // Page State
  const [currentPage, setCurrentPage] = useState('high-fashion'); // 'high-fashion', 'favourites', or 'my-brands'

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

  // Restore the session on load.
  //
  // One request. If the cookie is good the user is already in; if not they see
  // the sign-in screen. The previous version kept a copy of the user in
  // localStorage and trusted it, which meant the UI could show someone as
  // logged in after the server had already expired their session.
  useEffect(() => {
    // A 401 from anywhere in the app means the session died mid-use.
    FashionArchiveAPI.onUnauthorized = () => {
      setIsAuthenticated(false);
      setCurrentUser(null);
      setAuthNotice('Your session expired. Please sign in again.');
    };

    const params = new URLSearchParams(window.location.search);
    const onResetPage = window.location.pathname.startsWith('/reset-password');

    if (onResetPage && params.get('token')) {
      setResetToken(params.get('token'));
      setAuthMode('reset');
    } else if (params.get('verified')) {
      setAuthNotice('Email confirmed. You can sign in now.');
    } else if (params.get('error')) {
      setAuthNotice('That confirmation link is invalid or has expired.');
    }

    // Drop token and status out of the address bar so a reset token is not
    // left sitting in history or copied out of the URL bar.
    if (params.toString()) {
      window.history.replaceState({}, '', window.location.pathname);
    }

    const restore = async () => {
      try {
        const user = await FashionArchiveAPI.getMe();
        if (user) {
          setCurrentUser(user);
          setIsAuthenticated(true);
          loadSeasonsInBackground();
        }
      } catch (error) {
        console.error('Session check failed:', error);
      } finally {
        setAuthChecked(true);
        setIsLoading(false);
      }
    };

    restore();
  }, []);

  // Load seasons in background after authentication
  const loadSeasonsInBackground = async () => {
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

  // Handle successful login
  const handleAuthenticated = (user) => {
    setCurrentUser(user);
    setIsAuthenticated(true);
    setAuthMode(null);
    setAuthNotice('');
    setResetToken(null);
    loadSeasonsInBackground();
  };

  // Handle logout
  const handleLogout = async () => {
    try {
      // The server clears the cookie and deletes the session row; there is no
      // client-side token to forget.
      await FashionArchiveAPI.logout();
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      setCurrentUser(null);
      setIsAuthenticated(false);
      setAuthMode('login');
      setAuthNotice('');
      
      // Reset app state
      setSeasons([]);
      setSelectedSeason(null);
      setCollections([]);
      setSelectedCollection(null);
      setCurrentImages([]);
      setColumn2Activated(false);
      setColumn3Activated(false);
    }
  };

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

  // Handle video button click - search or toggle video
  const handleVideoButton = async () => {
    if (videoDownloadState === 'ready') {
      // Start search
      setVideoDownloadState('loading');
      try {
        const designerName = selectedCollection?.designer || '';
        const seasonName = selectedSeason?.name || '';
        const videoInfo = await FashionArchiveAPI.downloadVideo(designerName, seasonName);
        if (videoInfo) {
          setCurrentVideoPath(videoInfo);
          setVideoDownloadState('downloaded');
        } else {
          setVideoDownloadState('ready'); // Reset on failure
        }
      } catch (error) {
        console.error('Video search failed:', error);
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
  };

  if (isLoading) {
    console.log('🔍 Showing loading screen');
    return (
      <div className="columns-container">
        <div className="loading">
          <div className="mac-label">Loading Fashion Archive...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="columns-container">
      {/* Main Content */}
      {currentPage === 'high-fashion' ? (
        <HighFashionV2
          currentPage={currentPage}
          onPageSwitch={handlePageSwitch}
          onLogout={handleLogout}
          currentUser={currentUser}
        />
      ) : currentPage === 'favourites' ? (
        <FavouritesPanel
          currentPage={currentPage}
          onPageSwitch={handlePageSwitch}
          currentUser={currentUser}
          onLogout={handleLogout}
        />
      ) : currentPage === 'my-brands' ? (
        <MyBrandsPanel
          currentPage={currentPage}
          onPageSwitch={handlePageSwitch}
          currentUser={currentUser}
          onLogout={handleLogout}
        />
      ) : (
        <FavouritesPanel
          currentPage={currentPage}
          onPageSwitch={handlePageSwitch}
          currentUser={currentUser}
          onLogout={handleLogout}
        />
      )}

      {/* Video Window - Separate draggable window */}
      {videoModalOpen && currentVideoPath && (
        <VideoWindow 
          videoPath={currentVideoPath}
          onClose={() => setVideoModalOpen(false)}
        />
      )}

      {/* Auth screens. Held back until the cookie check finishes, so a
          returning user never sees a flash of the sign-in form. */}
      {authChecked && !isAuthenticated && (
        <AuthPanel
          onAuthenticated={handleAuthenticated}
          initialMode={authMode}
          initialNotice={authNotice}
          resetToken={resetToken}
        />
      )}
    </div>
  );
}

export default App;