import React, { useState, useEffect, useRef, useCallback } from 'react';
import { FashionArchiveAPI } from '../services/api';

// Brand folder positions storage key
const POSITIONS_KEY = 'myBrandsFolderPositions';

function MyBrandsPanel() {
  const [brands, setBrands] = useState([]);
  const [followedBrands, setFollowedBrands] = useState([]);
  const [loading, setLoading] = useState(true);
  const [contextMenu, setContextMenu] = useState(null);
  const [showAddBrandModal, setShowAddBrandModal] = useState(false);
  const [brandUrlInput, setBrandUrlInput] = useState('');
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState('');
  const [folderPositions, setFolderPositions] = useState({});
  const [dragging, setDragging] = useState(null);
  const [scrapingBrands, setScrapingBrands] = useState(new Set());
  const [lastRightClickPos, setLastRightClickPos] = useState(null);
  const [contextMenuBrand, setContextMenuBrand] = useState(null);

  const desktopRef = useRef(null);

  // Load brands and positions on mount
  useEffect(() => {
    loadBrands();
    loadFolderPositions();
  }, []);

  const loadBrands = async () => {
    try {
      setLoading(true);
      const followed = await FashionArchiveAPI.getFollowedBrands();
      console.log('Followed brands:', followed);
      setFollowedBrands(followed);

      // Load brand details for each followed brand
      const brandDetails = await Promise.all(
        followed.map(async (followedBrand) => {
          try {
            const details = await FashionArchiveAPI.getBrandDetails(followedBrand.brand_id);
            return {
              ...followedBrand,
              ...details
            };
          } catch (err) {
            console.error(`Error loading brand ${followedBrand.brand_id}:`, err);
            return followedBrand;
          }
        })
      );

      setBrands(brandDetails);
    } catch (error) {
      console.error('Error loading brands:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadFolderPositions = () => {
    try {
      const saved = localStorage.getItem(POSITIONS_KEY);
      if (saved) {
        setFolderPositions(JSON.parse(saved));
      }
    } catch (error) {
      console.error('Error loading folder positions:', error);
    }
  };

  const saveFolderPositions = (positions) => {
    try {
      localStorage.setItem(POSITIONS_KEY, JSON.stringify(positions));
    } catch (error) {
      console.error('Error saving folder positions:', error);
    }
  };

  // Get folder position for a brand
  const getFolderPosition = (brandId, index) => {
    if (folderPositions[brandId]) {
      return folderPositions[brandId];
    }

    // Auto-arrange in grid if no position set
    const gridSize = 120; // Folder width + spacing
    const columns = Math.floor((window.innerWidth - 40) / gridSize);
    const row = Math.floor(index / columns);
    const col = index % columns;

    return {
      x: 20 + col * gridSize,
      y: 20 + row * gridSize
    };
  };

  // Handle right-click context menu on desktop
  const handleContextMenu = (e) => {
    e.preventDefault();

    // Store the right-click position relative to the desktop
    const rect = desktopRef.current.getBoundingClientRect();
    setLastRightClickPos({
      x: e.clientX - rect.left + desktopRef.current.scrollLeft,
      y: e.clientY - rect.top + desktopRef.current.scrollTop
    });

    // Reset brand context menu (this is for desktop, not a specific brand)
    setContextMenuBrand(null);

    setContextMenu({
      x: e.clientX,
      y: e.clientY
    });
  };

  // Handle right-click context menu on a folder
  const handleFolderContextMenu = (e, brand) => {
    e.preventDefault();
    e.stopPropagation();

    setContextMenuBrand(brand);

    setContextMenu({
      x: e.clientX,
      y: e.clientY
    });
  };

  const closeContextMenu = () => {
    setContextMenu(null);
    setContextMenuBrand(null);
  };

  // Handle Add New Brand
  const handleAddBrand = () => {
    setShowAddBrandModal(true);
    closeContextMenu();
  };

  // Handle Rescrape Brand
  const handleRescrape = async () => {
    if (!contextMenuBrand) return;

    closeContextMenu();

    try {
      // Add brand to scraping set
      setScrapingBrands(prev => new Set([...prev, contextMenuBrand.brand_id]));

      // Trigger scrape
      await FashionArchiveAPI.scrapeBrandProducts(contextMenuBrand.brand_id);

      // Poll for completion
      const pollInterval = setInterval(async () => {
        try {
          const status = await FashionArchiveAPI.getBrandScrapeStatus(contextMenuBrand.brand_id);

          if (status.status === 'completed' || status.status === 'failed') {
            clearInterval(pollInterval);
            setScrapingBrands(prev => {
              const newSet = new Set(prev);
              newSet.delete(contextMenuBrand.brand_id);
              return newSet;
            });

            // Reload brands to get updated data
            loadBrands();
          }
        } catch (error) {
          console.error('Error polling scrape status:', error);
          clearInterval(pollInterval);
          setScrapingBrands(prev => {
            const newSet = new Set(prev);
            newSet.delete(contextMenuBrand.brand_id);
            return newSet;
          });
        }
      }, 2000); // Poll every 2 seconds
    } catch (error) {
      console.error('Error starting scrape:', error);
      setScrapingBrands(prev => {
        const newSet = new Set(prev);
        newSet.delete(contextMenuBrand.brand_id);
        return newSet;
      });
      setError('Failed to start scraping: ' + error.message);
    }
  };

  // Handle brand URL submission
  const handleSubmitBrandUrl = async () => {
    if (!brandUrlInput.trim()) {
      setError('Please enter a valid URL');
      return;
    }

    setValidating(true);
    setError('');

    try {
      // Step 1: Validate the brand
      const validationResult = await FashionArchiveAPI.validateBrand(brandUrlInput);

      if (!validationResult.success) {
        setError(validationResult.message || validationResult.error || 'Validation failed');
        setValidating(false);
        return;
      }

      // Step 2: Check if brand already exists
      if (validationResult.exists) {
        // Brand exists in database - follow it and add folder
        const brand = validationResult.brand;
        await FashionArchiveAPI.followBrand(brand.brand_id, brand.name);

        // Set position for existing brand at right-click location
        if (lastRightClickPos) {
          const newPositions = {
            ...folderPositions,
            [brand.brand_id]: {
              x: lastRightClickPos.x,
              y: lastRightClickPos.y
            }
          };
          setFolderPositions(newPositions);
          saveFolderPositions(newPositions);
        }

        // Close modal and reload brands
        setShowAddBrandModal(false);
        setBrandUrlInput('');
        loadBrands();
        return;
      }

      // Step 3: Brand is valid but doesn't exist - create it
      const createResult = await FashionArchiveAPI.createBrandWithValidation(
        brandUrlInput,
        validationResult.brand_name
      );

      if (!createResult.success) {
        setError(createResult.message || createResult.error || 'Failed to create brand');
        setValidating(false);
        return;
      }

      const newBrand = createResult.brand;

      // Step 4: Follow the new brand
      await FashionArchiveAPI.followBrand(newBrand.brand_id, newBrand.name);

      // Step 5: Set position for new brand at right-click location
      if (lastRightClickPos) {
        const newPositions = {
          ...folderPositions,
          [newBrand.brand_id]: {
            x: lastRightClickPos.x,
            y: lastRightClickPos.y
          }
        };
        setFolderPositions(newPositions);
        saveFolderPositions(newPositions);
      }

      // Step 6: Start scraping
      setScrapingBrands(prev => new Set(prev).add(newBrand.brand_id));
      FashionArchiveAPI.startBrandScraping(newBrand.brand_id).then(scrapeResult => {
        console.log('Scraping started:', scrapeResult);
        // Poll for status updates
        pollScrapingStatus(newBrand.brand_id);
      });

      // Close modal and reload
      setShowAddBrandModal(false);
      setBrandUrlInput('');
      setValidating(false);
      loadBrands();

    } catch (error) {
      console.error('Error adding brand:', error);
      setError(error.message || 'An error occurred');
      setValidating(false);
    }
  };

  // Poll for scraping status
  const pollScrapingStatus = async (brandId) => {
    const checkStatus = async () => {
      const status = await FashionArchiveAPI.getBrandScrapeStatus(brandId);

      if (status.error) {
        // No status found or error - stop polling
        setScrapingBrands(prev => {
          const newSet = new Set(prev);
          newSet.delete(brandId);
          return newSet;
        });
        return;
      }

      if (status.status === 'completed' || status.status === 'failed') {
        // Scraping finished
        setScrapingBrands(prev => {
          const newSet = new Set(prev);
          newSet.delete(brandId);
          return newSet;
        });
        loadBrands(); // Reload to get updated brand data
      } else {
        // Still running - check again in 3 seconds
        setTimeout(() => checkStatus(), 3000);
      }
    };

    checkStatus();
  };

  // Handle folder drag
  const handleFolderMouseDown = (e, brand) => {
    if (e.button !== 0) return; // Only left click

    e.preventDefault();
    const startX = e.clientX;
    const startY = e.clientY;
    const startPos = getFolderPosition(brand.brand_id, brands.indexOf(brand));

    setDragging({
      brandId: brand.brand_id,
      startX,
      startY,
      startPos
    });
  };

  const handleMouseMove = useCallback((e) => {
    if (!dragging) return;

    const deltaX = e.clientX - dragging.startX;
    const deltaY = e.clientY - dragging.startY;

    const newPositions = {
      ...folderPositions,
      [dragging.brandId]: {
        x: dragging.startPos.x + deltaX,
        y: dragging.startPos.y + deltaY
      }
    };

    setFolderPositions(newPositions);
  }, [dragging, folderPositions]);

  const handleMouseUp = useCallback(() => {
    if (dragging) {
      saveFolderPositions(folderPositions);
      setDragging(null);
    }
  }, [dragging, folderPositions]);

  useEffect(() => {
    if (dragging) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
      return () => {
        window.removeEventListener('mousemove', handleMouseMove);
        window.removeEventListener('mouseup', handleMouseUp);
      };
    }
  }, [dragging, handleMouseMove, handleMouseUp]);

  // Handle folder double-click (to be implemented next)
  const handleFolderDoubleClick = (brand) => {
    console.log('Double clicked brand:', brand);
    // TODO: Open brand detail view
  };

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        height: '100vh',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--macos-bg)'
      }}>
        <div style={{
          fontSize: '16px',
          color: 'var(--macos-text-secondary)'
        }}>
          Loading brands...
        </div>
      </div>
    );
  }

  return (
    <div
      ref={desktopRef}
      className="brands-desktop"
      onContextMenu={handleContextMenu}
      onClick={closeContextMenu}
      style={{ height: '100vh', position: 'relative' }}
    >
      {/* Brand Folders */}
      {brands.map((brand, index) => {
        const pos = getFolderPosition(brand.brand_id, index);
        const isLoading = scrapingBrands.has(brand.brand_id);

        return (
          <div
            key={brand.brand_id}
            className={`brand-folder ${isLoading ? 'loading' : ''}`}
            style={{
              left: `${pos.x}px`,
              top: `${pos.y}px`
            }}
            onMouseDown={(e) => handleFolderMouseDown(e, brand)}
            onDoubleClick={() => handleFolderDoubleClick(brand)}
            onContextMenu={(e) => handleFolderContextMenu(e, brand)}
          >
            {brand.favicon_path ? (
              <div className="folder-icon folder-icon-custom">
                <img
                  src={`http://localhost:8081/api/image?path=${encodeURIComponent(brand.favicon_path)}`}
                  alt={brand.name}
                  className="favicon-img"
                  onError={(e) => {
                    // Fallback to blue folder if favicon fails to load
                    e.target.style.display = 'none';
                    e.target.parentElement.classList.remove('folder-icon-custom');
                  }}
                />
              </div>
            ) : (
              <div className="folder-icon" />
            )}
            <div className={`folder-label ${isLoading ? 'loading-dots' : ''}`}>
              {isLoading ? 'Loading' : brand.name}
            </div>
          </div>
        );
      })}

      {/* Empty State */}
      {brands.length === 0 && (
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          textAlign: 'center',
          color: 'var(--macos-text-secondary)'
        }}>
          <div style={{ fontSize: '48px', marginBottom: '16px' }}>📁</div>
          <div style={{ fontSize: '18px', marginBottom: '8px' }}>No brands yet</div>
          <div style={{ fontSize: '14px' }}>Right-click to add your first brand</div>
        </div>
      )}

      {/* Context Menu */}
      {contextMenu && (
        <div
          className="context-menu"
          style={{
            left: `${contextMenu.x}px`,
            top: `${contextMenu.y}px`
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {contextMenuBrand ? (
            // Brand context menu
            <>
              <div className="context-menu-item" onClick={handleRescrape}>
                Rescrape Brand
              </div>
            </>
          ) : (
            // Desktop context menu
            <div className="context-menu-item" onClick={handleAddBrand}>
              New Brand...
            </div>
          )}
        </div>
      )}

      {/* Add Brand Modal */}
      {showAddBrandModal && (
        <div className="modern-modal-overlay" onClick={() => setShowAddBrandModal(false)}>
          <div className="modern-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modern-modal-title">Add New Brand</div>
            <div className="modern-modal-content">
              Enter the brand's homepage URL to add it to your collection.
            </div>

            {error && (
              <div className="modern-error">
                {error}
              </div>
            )}

            <input
              type="text"
              className="modern-input"
              placeholder="https://example.com"
              value={brandUrlInput}
              onChange={(e) => setBrandUrlInput(e.target.value)}
              onKeyPress={(e) => {
                if (e.key === 'Enter' && !validating) {
                  handleSubmitBrandUrl();
                }
              }}
              autoFocus
              disabled={validating}
            />

            <div className="modern-modal-actions">
              <button
                className="modern-button modern-button-secondary"
                onClick={() => {
                  setShowAddBrandModal(false);
                  setBrandUrlInput('');
                  setError('');
                }}
                disabled={validating}
              >
                Cancel
              </button>
              <button
                className="modern-button modern-button-primary"
                onClick={handleSubmitBrandUrl}
                disabled={validating || !brandUrlInput.trim()}
              >
                {validating ? 'Validating...' : 'Add Brand'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default MyBrandsPanel;
