import React, { useState, useEffect } from 'react';
import { FashionArchiveAPI } from '../services/api';

function MyBrandsPanel() {
  const [brands, setBrands] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedBrands, setExpandedBrands] = useState({});
  const [selectedLeaves, setSelectedLeaves] = useState(new Set());
  const [products, setProducts] = useState([]);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [scrapingBrands, setScrapingBrands] = useState(new Set());

  // Add brand modal state
  const [showAddBrandModal, setShowAddBrandModal] = useState(false);
  const [brandUrlInput, setBrandUrlInput] = useState('');
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState('');

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

    } catch (error) {
      console.error('Error loading brands:', error);
    } finally {
      setLoading(false);
    }
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
      await loadProductsForSelection(newSelected);
    } else {
      setProducts([]);
    }
  };

  // Load products for selected categories
  const loadProductsForSelection = async (selectedSet) => {
    try {
      setLoadingProducts(true);

      // Collect all products from selected categories
      const allProducts = [];

      for (const leafKey of selectedSet) {
        const [brandId, categoryUrl] = leafKey.split('::');

        // Fetch products filtered by category
        const response = await fetch(
          `http://localhost:8081/api/products?brand_id=${brandId}&classification_url=${encodeURIComponent(categoryUrl)}&limit=1000`
        );

        if (response.ok) {
          const data = await response.json();
          allProducts.push(...(data.products || []));
        }
      }

      setProducts(allProducts);
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

    return categories.map((category, idx) => {
      const hasChildren = category.children && category.children.length > 0;
      const isLeaf = !hasChildren;
      const leafKey = `${brand.brand_id}::${category.url}`;
      const isSelected = selectedLeaves.has(leafKey);

      // Determine display name based on whether it's a leaf
      const displayName = isLeaf ? category.name.toLowerCase() : category.name.toUpperCase();

      return (
        <div key={`${brand.brand_id}-${category.url}-${idx}`} style={{ marginLeft: level > 0 ? '16px' : '0' }}>
          <div
            className={`nav-item ${isLeaf ? 'nav-leaf' : 'nav-parent'} ${isSelected ? 'nav-selected' : ''}`}
            onClick={() => {
              if (isLeaf) {
                toggleLeaf(brand.brand_id, category.url, category.name);
              }
            }}
          >
            {!isLeaf && <span className="nav-icon">▸</span>}
            {isLeaf && <span className="nav-bullet">•</span>}
            <span className={isSelected ? 'nav-text-bold' : 'nav-text'}>
              {displayName}
            </span>
          </div>

          {hasChildren && renderCategoryTree(brand, category.children, level + 1)}
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
                  onClick={() => toggleBrand(brand.brand_id)}
                >
                  <span className="brand-expand-icon">{isExpanded ? '▾' : '▸'}</span>
                  <span className="brand-name-text">{brand.name.toUpperCase()}</span>
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
      <div className="product-gallery">
        {loadingProducts ? (
          <div className="gallery-loading">Loading products...</div>
        ) : products.length > 0 ? (
          <div className="product-grid">
            {products.map((product, idx) => (
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
                  <div className="product-name">{product.product_name}</div>
                  {product.attributes?.price && (
                    <div className="product-price">{product.attributes.price}</div>
                  )}
                </div>
              </div>
            ))}
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
