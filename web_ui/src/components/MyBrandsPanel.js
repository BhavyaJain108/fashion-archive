import React, { useState, useEffect, useRef } from 'react';
import { FashionArchiveAPI } from '../services/api';
import ProductDetailPanel from './ProductDetailPanel';

function MyBrandsPanel() {
  const [brands, setBrands] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedBrands, setExpandedBrands] = useState({});
  const [expandedCategories, setExpandedCategories] = useState({});
  const [selectedLeaves, setSelectedLeaves] = useState(new Set());
  const selectedLeavesRef = useRef(new Set());
  const [products, setProducts] = useState([]);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [scrapingBrands, setScrapingBrands] = useState(new Set());
  const [productCounts, setProductCounts] = useState({});
  const [selectedProduct, setSelectedProduct] = useState(null);

  // Streaming state
  const [streamingBrandId, setStreamingBrandId] = useState(null); // which brand is being streamed

  // Add brand modal state
  const [showAddBrandModal, setShowAddBrandModal] = useState(false);
  const [brandUrlInput, setBrandUrlInput] = useState('');
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState('');

  // Click-count state for re-scraping (double-click = products only, triple-click = full)
  const clickCountRef = useRef({});
  const clickTimerRef = useRef({});

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

            // Load navigation tree via API endpoint
            let navigation = [];
            try {
              const navResponse = await fetch(
                `http://localhost:8081/api/brands/${followedBrand.brand_id}/categories/hierarchy`
              );
              if (navResponse.ok) {
                const navData = await navResponse.json();
                navigation = navData.hierarchy || [];
              }
            } catch (e) {
              console.warn('Could not load navigation for', followedBrand.brand_id);
            }

            return {
              ...followedBrand,
              ...details,
              navigation: navigation
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

  // Load product counts for all leaf categories via API
  const loadProductCounts = async (brandsWithData) => {
    const counts = {};

    for (const brand of brandsWithData) {
      try {
        // Fetch product counts via API endpoint
        const countsResponse = await fetch(
          `http://localhost:8081/api/products/counts?brand_id=${brand.brand_id}`
        );

        if (countsResponse.ok) {
          const countsData = await countsResponse.json();
          const urlCounts = countsData.counts || {};

          // Map URL counts to leaf keys
          for (const [categoryUrl, count] of Object.entries(urlCounts)) {
            const leafKey = `${brand.brand_id}::${categoryUrl}`;
            counts[leafKey] = count;
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

  // Stream products via SSE as they're extracted
  const streamProducts = (brandId) => {
    setStreamingBrandId(brandId);
    const source = new EventSource(`http://localhost:8081/api/brands/${brandId}/scrape/stream`);

    source.onmessage = (event) => {
      try {
        const product = JSON.parse(event.data);
        const categoryUrl = product._category_url || '';

        // Update live category counter (keyed by brandId::categoryUrl to match sidebar tree)
        if (categoryUrl) {
          const leafKey = `${brandId}::${categoryUrl}`;
          setProductCounts(prev => ({
            ...prev,
            [leafKey]: (prev[leafKey] || 0) + 1
          }));
        }

        // Only add to product grid if this product's category is currently selected
        if (categoryUrl) {
          const leafKey = `${brandId}::${categoryUrl}`;
          if (selectedLeavesRef.current.has(leafKey)) {
            setProducts(prev => [product, ...prev]);
          }
        }
      } catch (e) {
        console.error('Error parsing streamed product:', e);
      }
    };

    source.addEventListener('nav_ready', async () => {
      // Navigation tree is ready — re-fetch hierarchy and update the brand's tree
      try {
        const navResponse = await fetch(
          `http://localhost:8081/api/brands/${brandId}/categories/hierarchy`
        );
        if (navResponse.ok) {
          const navData = await navResponse.json();
          const hierarchy = navData.hierarchy || [];
          setBrands(prev => prev.map(b =>
            b.brand_id === brandId ? { ...b, navigation: hierarchy } : b
          ));
          // Auto-expand the brand so user sees categories appear
          setExpandedBrands(prev => ({ ...prev, [brandId]: true }));
        }
      } catch (e) {
        console.warn('Failed to reload navigation after nav_ready:', e);
      }
    });

    source.addEventListener('done', () => {
      source.close();
      setScrapingBrands(prev => {
        const newSet = new Set(prev);
        newSet.delete(brandId);
        return newSet;
      });
      setStreamingBrandId(null);
      loadBrands();
    });

    source.onerror = () => {
      source.close();
    };

    return source;
  };

  // Toggle brand expansion
  const toggleBrand = (brandId) => {
    setExpandedBrands(prev => ({
      ...prev,
      [brandId]: !prev[brandId]
    }));
  };

  // Handle click counting: single=expand, double=rescrape products, triple=full rescrape
  const handleBrandClick = (brandId) => {
    if (!clickCountRef.current[brandId]) clickCountRef.current[brandId] = 0;
    clickCountRef.current[brandId]++;

    if (clickTimerRef.current[brandId]) clearTimeout(clickTimerRef.current[brandId]);

    clickTimerRef.current[brandId] = setTimeout(() => {
      const clicks = clickCountRef.current[brandId];
      clickCountRef.current[brandId] = 0;

      if (clicks === 1) {
        toggleBrand(brandId);
      } else if (clicks === 2) {
        handleRescrape(brandId, 'products_only');
      } else if (clicks >= 3) {
        handleRescrape(brandId, 'full');
      }
    }, 350);
  };

  const handleRescrape = async (brandId, mode = 'full') => {
    setScrapingBrands(prev => new Set(prev).add(brandId));
    setProducts([]);
    setStreamingBrandId(brandId);
    // Clear product counts for this brand so categories show 0 until products stream in
    setProductCounts(prev => {
      const cleared = { ...prev };
      Object.keys(cleared).forEach(key => {
        if (key.startsWith(`${brandId}::`)) delete cleared[key];
      });
      return cleared;
    });
    // Expand the brand tree so user can see categories reappearing
    setExpandedBrands(prev => ({ ...prev, [brandId]: true }));
    try {
      await FashionArchiveAPI.startBrandScraping(brandId, mode);
      streamProducts(brandId);
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
  const toggleLeaf = async (brandId, categoryUrl, categoryName, shiftKey = false) => {
    const leafKey = `${brandId}::${categoryUrl}`;

    let newSelected;

    if (shiftKey) {
      // Shift-click: exclusively select this category (deselect all others)
      newSelected = new Set([leafKey]);
    } else {
      // Normal click: toggle this category
      newSelected = new Set(selectedLeaves);
      if (newSelected.has(leafKey)) {
        newSelected.delete(leafKey);
      } else {
        newSelected.add(leafKey);
      }
    }

    setSelectedLeaves(newSelected);
    selectedLeavesRef.current = newSelected;

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

      // Helper function to get product URL (handles both old and new formats)
      const getProductUrl = (product) => {
        return product.url || product.product_url || '';
      };

      // If there's a newly selected key, load it first (prepend)
      let newProducts = [];
      let existingProductsWithCategory = [];

      if (newlySelectedKey && selectedSet.has(newlySelectedKey)) {
        // Load the newly selected category first
        const [brandId, categoryIdentifier] = newlySelectedKey.split('::');
        // Try both classification_url and classification_name for compatibility
        let response = await fetch(
          `http://localhost:8081/api/products?brand_id=${brandId}&classification_url=${encodeURIComponent(categoryIdentifier)}&limit=1000`
        );
        if (response.ok) {
          const data = await response.json();
          newProducts = (data.products || []).map(p => ({ ...p, _category: categoryIdentifier }));
        }
      }

      // Load all other selected categories
      for (const leafKey of selectedSet) {
        if (leafKey === newlySelectedKey) continue; // Skip the newly added one

        const [brandId, categoryIdentifier] = leafKey.split('::');
        const response = await fetch(
          `http://localhost:8081/api/products?brand_id=${brandId}&classification_url=${encodeURIComponent(categoryIdentifier)}&limit=1000`
        );

        if (response.ok) {
          const data = await response.json();
          const productsWithCategory = (data.products || []).map(p => ({ ...p, _category: categoryIdentifier }));
          existingProductsWithCategory.push(...productsWithCategory);
        }
      }

      // Deduplicate: prioritize new products, then add existing ones if not already seen
      for (const product of newProducts) {
        const url = getProductUrl(product);
        if (url && !seenProductUrls.has(url)) {
          seenProductUrls.add(url);
          deduplicatedProducts.push(product);
        }
      }

      for (const product of existingProductsWithCategory) {
        const url = getProductUrl(product);
        if (url && !seenProductUrls.has(url)) {
          seenProductUrls.add(url);
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

      // Start scraping with live streaming
      setScrapingBrands(prev => new Set(prev).add(newBrand.brand_id));
      setProducts([]);
      setStreamingBrandId(newBrand.brand_id);
      FashionArchiveAPI.startBrandScraping(newBrand.brand_id).then(() => {
        streamProducts(newBrand.brand_id);
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

  // Check if a category subtree has any products (for filtering during scraping)
  const hasProductsInSubtree = (brand, category) => {
    const hasChildren = category.children && category.children.length > 0;
    if (!hasChildren) {
      // Leaf: check product count
      const leafKey = `${brand.brand_id}::${category.url}`;
      return (productCounts[leafKey] || 0) > 0;
    }
    // Parent: check if any child has products
    return category.children.some(child => hasProductsInSubtree(brand, child));
  };

  // Render category tree recursively
  const renderCategoryTree = (brand, categories, level = 0) => {
    if (!categories || categories.length === 0) return null;

    const isScraping = scrapingBrands.has(brand.brand_id);

    // Sort categories: parents with children first, then leaf categories
    const sortedCategories = [...categories].sort((a, b) => {
      const aHasChildren = a.children && a.children.length > 0;
      const bHasChildren = b.children && b.children.length > 0;

      if (aHasChildren && !bHasChildren) return -1;
      if (!aHasChildren && bHasChildren) return 1;
      return 0;
    });

    // During scraping, filter to only categories with products
    const visibleCategories = isScraping
      ? sortedCategories.filter(cat => hasProductsInSubtree(brand, cat))
      : sortedCategories;

    return visibleCategories.map((category, idx) => {
      const hasChildren = category.children && category.children.length > 0;
      const isLeaf = !hasChildren;
      const leafKey = `${brand.brand_id}::${category.url}`;
      // Use URL-based key instead of index to prevent expand/collapse issues
      const categoryKey = `${brand.brand_id}::${category.url || category.name}`;
      const isSelected = selectedLeaves.has(leafKey);
      const isExpanded = expandedCategories[categoryKey];

      // All categories display in lowercase
      const displayName = (category.name || 'Unknown').toLowerCase();

      const productCount = isLeaf ? productCounts[leafKey] : null;

      return (
        <div key={categoryKey} style={{ marginLeft: level > 0 ? '16px' : '0' }}>
          <div
            className={`nav-item ${isLeaf ? 'nav-leaf' : 'nav-parent'} ${isSelected ? 'nav-selected' : ''}`}
            onClick={(e) => {
              if (isLeaf) {
                toggleLeaf(brand.brand_id, category.url, category.name, e.shiftKey);
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

            return (
              <div key={brand.brand_id} className="brand-section">
                <div
                  className={`brand-name ${isScraping ? 'brand-loading' : ''}`}
                  onClick={() => !isScraping && handleBrandClick(brand.brand_id)}
                  style={{
                    position: 'relative',
                    cursor: isScraping ? 'not-allowed' : undefined,
                  }}
                >
                  <span className="brand-name-text">{(brand.name || brand.brand_id || 'Unknown').toUpperCase()}</span>
                  {isScraping && <span className="brand-loading-text"> loading...</span>}
                </div>

                {isExpanded && (
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
      <div className={`product-gallery ${selectedProduct ? 'with-detail' : ''}`}>
        {loadingProducts ? (
          <div className="gallery-loading">Loading products...</div>
        ) : products.length > 0 ? (
          <div className="product-grid">
            {products.map((product, idx) => {
              const brandName = product.brand
                ? product.brand.toUpperCase()
                : (product.brand_id ? product.brand_id.replace(/_/g, ' ').toUpperCase() : '');
              const productName = product.name || product.product_name || 'Unknown Product';
              const productUrl = product.url || product.product_url || '';
              let imageUrl = null;
              if (product.images && product.images.length > 0) {
                const firstImage = product.images[0];
                imageUrl = typeof firstImage === 'string' ? firstImage : firstImage.src;
              }
              const priceDisplay = product.price
                ? `${product.currency || ''} ${product.price}`.trim()
                : product.attributes?.price;

              return (
                <div
                  key={`${productUrl}-${idx}`}
                  className={`product-card ${selectedProduct && (selectedProduct.url || selectedProduct.product_url) === productUrl ? 'selected' : ''}`}
                  onClick={() => setSelectedProduct(product)}
                >
                  {imageUrl && (
                    <div className="product-image">
                      <img src={imageUrl} alt={productName} loading="lazy" />
                    </div>
                  )}
                  <div className="product-info">
                    <div className="product-brand">{brandName}</div>
                    <div className="product-name">{productName}</div>
                    {priceDisplay && <div className="product-price">{priceDisplay}</div>}
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>

      {/* Product Detail Panel */}
      {selectedProduct && (
        <ProductDetailPanel
          product={selectedProduct}
          onClose={() => setSelectedProduct(null)}
        />
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
