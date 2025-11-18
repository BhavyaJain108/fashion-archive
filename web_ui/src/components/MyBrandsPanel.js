import React, { useState, useEffect } from 'react';
import { FashionArchiveAPI } from '../services/api';

function MyBrandsPanel() {
  const [brands, setBrands] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedBrands, setExpandedBrands] = useState({});
  const [expandedCategories, setExpandedCategories] = useState({});
  const [selectedLeaves, setSelectedLeaves] = useState(new Set());
  const [products, setProducts] = useState([]);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [scrapingBrands, setScrapingBrands] = useState(new Set());
  const [productCounts, setProductCounts] = useState({});

  // Add brand modal state
  const [showAddBrandModal, setShowAddBrandModal] = useState(false);
  const [brandUrlInput, setBrandUrlInput] = useState('');
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState('');

  // Long-press state for re-scraping
  const [longPressTimer, setLongPressTimer] = useState(null);
  const [longPressingBrand, setLongPressingBrand] = useState(null);
  const [longPressProgress, setLongPressProgress] = useState(0);

  // Load brands on mount
  useEffect(() => {
    loadBrands();
  }, []);

  const loadBrands = async () => {
    try {
      setLoading(true);
      const followed = await FashionArchiveAPI.getFollowedBrands();

      // Load brand details and navigation for each followed brand
      const brandsWithData = await Promise.all(
        followed.map(async (followedBrand) => {
          try {
            const details = await FashionArchiveAPI.getBrandDetails(followedBrand.brand_id);

            // Load navigation tree
            const navResponse = await fetch(
              `http://localhost:8081/api/image?path=${encodeURIComponent(`data/brands/${followedBrand.brand_id}/navigation.json`)}`
            );
            let navigation = { category_tree: [] };
            if (navResponse.ok) {
              const navText = await navResponse.text();
              try {
                navigation = JSON.parse(navText);
              } catch (e) {
                console.warn('Could not parse navigation for', followedBrand.brand_id);
              }
            }

            return {
              ...followedBrand,
              ...details,
              navigation: navigation.category_tree || []
            };
          } catch (err) {
            console.error(`Error loading brand ${followedBrand.brand_id}:`, err);
            return {
              ...followedBrand,
              navigation: []
            };
          }
        })
      );

      setBrands(brandsWithData);

      // Check scraping status for each brand
      brandsWithData.forEach(brand => {
        if (brand.status?.last_scrape_status === 'running') {
          setScrapingBrands(prev => new Set([...prev, brand.brand_id]));
          pollScrapingStatus(brand.brand_id);
        }
      });

      // Load product counts for all leaf categories
      loadProductCounts(brandsWithData);

    } catch (error) {
      console.error('Error loading brands:', error);
    } finally {
      setLoading(false);
    }
  };

  // Load product counts for all leaf categories from scraping_intel.json
  const loadProductCounts = async (brandsWithData) => {
    const counts = {};

    for (const brand of brandsWithData) {
      try {
        // Fetch scraping intel which contains product counts
        const intelResponse = await fetch(
          `http://localhost:8081/api/image?path=${encodeURIComponent(`data/brands/${brand.brand_id}/scraping_intel.json`)}`
        );

        if (intelResponse.ok) {
          const intelText = await intelResponse.text();
          const intel = JSON.parse(intelText);

          // Extract product counts from worked_on_categories
          const workedOnCategories = intel.patterns?.product_listing?.primary?.worked_on_categories || [];

          for (const category of workedOnCategories) {
            if (category.category_url) {
              const leafKey = `${brand.brand_id}::${category.category_url}`;
              counts[leafKey] = category.products_found || 0;
            }
          }
        }
      } catch (error) {
        console.error(`Error loading product counts for ${brand.brand_id}:`, error);
      }
    }

    setProductCounts(counts);
  };

  // Poll for scraping status
  const pollScrapingStatus = async (brandId) => {
    const checkStatus = async () => {
      try {
        const status = await FashionArchiveAPI.getBrandScrapeStatus(brandId);

        if (status.error || status.status === 'completed' || status.status === 'failed') {
          setScrapingBrands(prev => {
            const newSet = new Set(prev);
            newSet.delete(brandId);
            return newSet;
          });
          loadBrands(); // Reload to get updated data
        } else {
          setTimeout(() => checkStatus(), 3000);
        }
      } catch (error) {
        setScrapingBrands(prev => {
          const newSet = new Set(prev);
          newSet.delete(brandId);
          return newSet;
        });
      }
    };
    checkStatus();
  };

  // Toggle brand expansion
  const toggleBrand = (brandId) => {
    setExpandedBrands(prev => ({
      ...prev,
      [brandId]: !prev[brandId]
    }));
  };

  // Handle long-press to re-scrape brand
  const handleBrandMouseDown = (brandId) => {
    setLongPressingBrand(brandId);
    setLongPressProgress(0);

    let progress = 0;
    const interval = setInterval(() => {
      progress += 2;
      setLongPressProgress(progress);
      if (progress >= 100) {
        clearInterval(interval);
        handleRescrape(brandId);
      }
    }, 30); // 1.5 seconds total (50 * 30ms)

    setLongPressTimer(interval);
  };

  const handleBrandMouseUp = () => {
    if (longPressTimer) {
      clearInterval(longPressTimer);
      setLongPressTimer(null);
    }
    setLongPressingBrand(null);
    setLongPressProgress(0);
  };

  const handleRescrape = async (brandId) => {
    setScrapingBrands(prev => new Set(prev).add(brandId));
    try {
      await FashionArchiveAPI.startBrandScraping(brandId);
      pollScrapingStatus(brandId);
    } catch (error) {
      console.error('Error starting re-scrape:', error);
      setScrapingBrands(prev => {
        const newSet = new Set(prev);
        newSet.delete(brandId);
        return newSet;
      });
    }
  };

  // Toggle category expansion (for parent categories)
  const toggleCategory = (categoryKey) => {
    setExpandedCategories(prev => ({
      ...prev,
      [categoryKey]: !prev[categoryKey]
    }));
  };

  // Toggle leaf selection
  const toggleLeaf = async (brandId, categoryUrl, categoryName) => {
    const leafKey = `${brandId}::${categoryUrl}`;

    const newSelected = new Set(selectedLeaves);
    if (newSelected.has(leafKey)) {
      newSelected.delete(leafKey);
    } else {
      newSelected.add(leafKey);
    }

    setSelectedLeaves(newSelected);

    // Load products for all selected leaves
    if (newSelected.size > 0) {
      // Pass the newly toggled leaf key if it was just added
      const newlyAdded = newSelected.has(leafKey) && !selectedLeaves.has(leafKey) ? leafKey : null;
      await loadProductsForSelection(newSelected, newlyAdded);
    } else {
      setProducts([]);
    }
  };

  // Load products for selected categories
  const loadProductsForSelection = async (selectedSet, newlySelectedKey = null) => {
    try {
      setLoadingProducts(true);

      // Track seen products by URL to avoid duplicates
      const seenProductUrls = new Set();
      const deduplicatedProducts = [];

      // If there's a newly selected key, load it first (prepend)
      let newProducts = [];
      let existingProducts = [];

      if (newlySelectedKey && selectedSet.has(newlySelectedKey)) {
        // Load the newly selected category first
        const [brandId, categoryUrl] = newlySelectedKey.split('::');
        const response = await fetch(
          `http://localhost:8081/api/products?brand_id=${brandId}&classification_url=${encodeURIComponent(categoryUrl)}&limit=1000`
        );
        if (response.ok) {
          const data = await response.json();
          newProducts = data.products || [];
        }
      }

      // Load all other selected categories
      for (const leafKey of selectedSet) {
        if (leafKey === newlySelectedKey) continue; // Skip the newly added one

        const [brandId, categoryUrl] = leafKey.split('::');
        const response = await fetch(
          `http://localhost:8081/api/products?brand_id=${brandId}&classification_url=${encodeURIComponent(categoryUrl)}&limit=1000`
        );

        if (response.ok) {
          const data = await response.json();
          existingProducts.push(...(data.products || []));
        }
      }

      // Deduplicate: prioritize new products, then add existing ones if not already seen
      for (const product of newProducts) {
        if (product.product_url && !seenProductUrls.has(product.product_url)) {
          seenProductUrls.add(product.product_url);
          deduplicatedProducts.push(product);
        }
      }

      for (const product of existingProducts) {
        if (product.product_url && !seenProductUrls.has(product.product_url)) {
          seenProductUrls.add(product.product_url);
          deduplicatedProducts.push(product);
        }
      }

      setProducts(deduplicatedProducts);
    } catch (error) {
      console.error('Error loading products:', error);
    } finally {
      setLoadingProducts(false);
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
      // Validate the brand
      const validationResult = await FashionArchiveAPI.validateBrand(brandUrlInput);

      if (!validationResult.success) {
        setError(validationResult.message || validationResult.error || 'Validation failed');
        setValidating(false);
        return;
      }

      // Check if brand already exists
      if (validationResult.exists) {
        const brand = validationResult.brand;
        await FashionArchiveAPI.followBrand(brand.brand_id, brand.name);
        setShowAddBrandModal(false);
        setBrandUrlInput('');
        loadBrands();
        return;
      }

      // Create new brand
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
      await FashionArchiveAPI.followBrand(newBrand.brand_id, newBrand.name);

      // Start scraping
      setScrapingBrands(prev => new Set(prev).add(newBrand.brand_id));
      FashionArchiveAPI.startBrandScraping(newBrand.brand_id).then(() => {
        pollScrapingStatus(newBrand.brand_id);
      });

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

  // Render category tree recursively
  const renderCategoryTree = (brand, categories, level = 0) => {
    if (!categories || categories.length === 0) return null;

    // Sort categories: parents with children first, then leaf categories
    const sortedCategories = [...categories].sort((a, b) => {
      const aHasChildren = a.children && a.children.length > 0;
      const bHasChildren = b.children && b.children.length > 0;

      if (aHasChildren && !bHasChildren) return -1;
      if (!aHasChildren && bHasChildren) return 1;
      return 0;
    });

    return sortedCategories.map((category, idx) => {
      const hasChildren = category.children && category.children.length > 0;
      const isLeaf = !hasChildren;
      const leafKey = `${brand.brand_id}::${category.url}`;
      // Use URL-based key instead of index to prevent expand/collapse issues
      const categoryKey = `${brand.brand_id}::${category.url || category.name}`;
      const isSelected = selectedLeaves.has(leafKey);
      const isExpanded = expandedCategories[categoryKey];

      // Determine display name based on whether it's a leaf
      const displayName = isLeaf ? category.name.toLowerCase() : category.name.toUpperCase();

      const productCount = isLeaf ? productCounts[leafKey] : null;

      return (
        <div key={categoryKey} style={{ marginLeft: level > 0 ? '16px' : '0' }}>
          <div
            className={`nav-item ${isLeaf ? 'nav-leaf' : 'nav-parent'} ${isSelected ? 'nav-selected' : ''}`}
            onClick={() => {
              if (isLeaf) {
                toggleLeaf(brand.brand_id, category.url, category.name);
              } else {
                toggleCategory(categoryKey);
              }
            }}
          >
            {!isLeaf && <span className="nav-icon">{isExpanded ? '▾' : '▸'}</span>}
            {isLeaf && <span className="nav-bullet">•</span>}
            <span className={isSelected ? 'nav-text-bold' : 'nav-text'}>
              {displayName}
            </span>
            {isLeaf && productCount !== null && productCount !== undefined && (
              <span className="nav-count">{productCount}</span>
            )}
          </div>

          {hasChildren && isExpanded && renderCategoryTree(brand, category.children, level + 1)}
        </div>
      );
    });
  };

  if (loading) {
    return (
      <div className="my-brands-container">
        <div className="loading-state">Loading brands...</div>
      </div>
    );
  }

  return (
    <div className="my-brands-container">
      {/* Left Sidebar - Brand Navigation */}
      <div className="brand-sidebar">
        <div className="brand-sidebar-content">
          {brands.map(brand => {
            const isExpanded = expandedBrands[brand.brand_id];
            const isScraping = scrapingBrands.has(brand.brand_id);

            const isLongPressing = longPressingBrand === brand.brand_id;

            return (
              <div key={brand.brand_id} className="brand-section">
                <div
                  className={`brand-name ${isScraping ? 'brand-loading' : ''} ${isLongPressing ? 'brand-long-pressing' : ''}`}
                  onClick={() => !isLongPressing && !isScraping && toggleBrand(brand.brand_id)}
                  onMouseDown={() => !isScraping && handleBrandMouseDown(brand.brand_id)}
                  onMouseUp={handleBrandMouseUp}
                  onMouseLeave={handleBrandMouseUp}
                  style={{
                    position: 'relative',
                    cursor: isScraping ? 'not-allowed' : undefined,
                    background: isLongPressing
                      ? `linear-gradient(to right, rgba(0, 122, 255, 0.1) ${longPressProgress}%, transparent ${longPressProgress}%)`
                      : undefined
                  }}
                >
                  <span className="brand-name-text">{brand.name.toUpperCase()}</span>
                  {isScraping && <span className="brand-loading-text"> loading...</span>}
                </div>

                {isExpanded && !isScraping && (
                  <div className="brand-categories">
                    {renderCategoryTree(brand, brand.navigation)}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Add Brand Button */}
        <div className="add-brand-footer">
          <button
            className="add-brand-button"
            onClick={() => setShowAddBrandModal(true)}
          >
            + Add New Brand
          </button>
        </div>
      </div>

      {/* Right Panel - Product Gallery */}
      <div className="product-gallery">
        {loadingProducts ? (
          <div className="gallery-loading">Loading products...</div>
        ) : products.length > 0 ? (
          <div className="product-grid">
            {products.map((product, idx) => {
              // Extract brand name from brand_id (e.g., "jukuhara" -> "JUKUHARA")
              const brandName = product.brand_id ? product.brand_id.replace(/_/g, ' ').toUpperCase() : '';

              return (
                <div key={`${product.product_url}-${idx}`} className="product-card">
                  {product.images && product.images.length > 0 && (
                    <div className="product-image">
                      <img
                        src={product.images[0].src}
                        alt={product.product_name}
                        loading="lazy"
                      />
                    </div>
                  )}
                  <div className="product-info">
                    <div className="product-brand">{brandName}</div>
                    <div className="product-name">{product.product_name}</div>
                    {product.attributes?.price && (
                      <div className="product-price">{product.attributes.price}</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="gallery-empty">
            <div className="empty-icon">👕</div>
            <div className="empty-text">Select categories to browse products</div>
          </div>
        )}
      </div>

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
