import { useState, useEffect } from 'react';
import { FashionArchiveAPI } from '../services/api';
import MacModal from './MacModal';

function MyBrandsPanel() {
  const [brands, setBrands] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({});
  const [selectedBrand, setSelectedBrand] = useState(null);
  const [showAddBrand, setShowAddBrand] = useState(false);
  const [newBrandInput, setNewBrandInput] = useState('');
  const [inputMode, setInputMode] = useState('name'); // 'name' or 'url'
  const [validationLoading, setValidationLoading] = useState(false);
  const [resolverLoading, setResolverLoading] = useState(false);
  const [scrapingLoading, setScrapingLoading] = useState(false);
  const [scrapingResult, setScrapingResult] = useState(null);
  const [selectedProductIndex, setSelectedProductIndex] = useState(0);
  const [hoveredProductIndex, setHoveredProductIndex] = useState(null); // Track hovered product for preview
  const [resultModal, setResultModal] = useState(null); // { type: 'success'|'error', title: '', message: '' }
  const [imageColors, setImageColors] = useState({}); // Store extracted colors for each image
  
  // NEW: Clean UX state management
  const [viewMode, setViewMode] = useState('brand'); // 'brand' | 'categories' | 'products'
  const [categories, setCategories] = useState({}); // Store categories without products
  const [selectedCategory, setSelectedCategory] = useState(null); // Currently selected category
  const [categoryProducts, setCategoryProducts] = useState([]); // Products for selected category
  
  // Legacy functions removed - new clean UX doesn't need these

  // Extract dominant color from image
  const extractImageColor = (imageUrl, productId) => {
    if (imageColors[productId]) return; // Already extracted
    
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        canvas.width = img.width;
        canvas.height = img.height;
        ctx.drawImage(img, 0, 0);
        
        // Sample pixels from edges to get border color
        const edgePixels = [];
        const margin = 5; // Sample from 5px inside the edge
        
        // Sample top and bottom edges
        for (let x = margin; x < canvas.width - margin; x += 10) {
          const topPixel = ctx.getImageData(x, margin, 1, 1).data;
          const bottomPixel = ctx.getImageData(x, canvas.height - margin, 1, 1).data;
          edgePixels.push(topPixel, bottomPixel);
        }
        
        // Sample left and right edges  
        for (let y = margin; y < canvas.height - margin; y += 10) {
          const leftPixel = ctx.getImageData(margin, y, 1, 1).data;
          const rightPixel = ctx.getImageData(canvas.width - margin, y, 1, 1).data;
          edgePixels.push(leftPixel, rightPixel);
        }
        
        // Calculate average color
        let r = 0, g = 0, b = 0;
        edgePixels.forEach(pixel => {
          r += pixel[0];
          g += pixel[1]; 
          b += pixel[2];
        });
        
        const count = edgePixels.length;
        r = Math.round(r / count);
        g = Math.round(g / count);
        b = Math.round(b / count);
        
        const bgColor = `rgb(${r}, ${g}, ${b})`;
        const textColor = (r * 0.299 + g * 0.587 + b * 0.114) > 128 ? '#000' : '#fff';
        
        setImageColors(prev => ({
          ...prev,
          [productId]: { background: bgColor, text: textColor }
        }));
      } catch (error) {
        console.warn('Could not extract color from image:', error);
      }
    };
    img.src = imageUrl;
  };

  // Load brands on component mount
  useEffect(() => {
    loadBrands();
    loadStats();
  }, []);

  // Keyboard navigation for products
  useEffect(() => {
    const handleKeyDown = (event) => {
      // Only handle arrow keys when we have products and we're in products view
      if (viewMode !== 'products' || categoryProducts.length === 0) return;

      switch (event.key) {
        case 'ArrowLeft':
          event.preventDefault();
          setSelectedProductIndex(prev => {
            const newIndex = prev > 0 ? prev - 1 : categoryProducts.length - 1;
            // Scroll to show the new selection
            scrollToProduct(newIndex);
            return newIndex;
          });
          break;
        case 'ArrowRight':
          event.preventDefault();
          setSelectedProductIndex(prev => {
            const newIndex = prev < categoryProducts.length - 1 ? prev + 1 : 0;
            // Scroll to show the new selection
            scrollToProduct(newIndex);
            return newIndex;
          });
          break;
        default:
          break;
      }
    };

    // Add event listener
    window.addEventListener('keydown', handleKeyDown);

    // Cleanup
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [viewMode, categoryProducts.length]);

  // Function to scroll gallery to show specific product
  const scrollToProduct = (productIndex) => {
    // Give a small delay to ensure state updates have rendered
    setTimeout(() => {
      // Find the product element by its index
      const productElement = document.querySelector(`[data-product-index="${productIndex}"]`);
      if (productElement) {
        productElement.scrollIntoView({
          behavior: 'smooth',
          block: 'nearest',
          inline: 'center'
        });
      }
    }, 10);
  };

  const loadBrands = async () => {
    try {
      setLoading(true);
      const brandsData = await FashionArchiveAPI.getBrands();
      // Filter to only show approved brands
      const approvedBrands = brandsData.filter(brand => brand.validation_status === 'approved');
      setBrands(approvedBrands);
    } catch (error) {
      console.error('Error loading brands:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadStats = async () => {
    try {
      const statsData = await FashionArchiveAPI.getBrandStats();
      setStats(statsData);
    } catch (error) {
      console.error('Error loading stats:', error);
    }
  };

  const handleAddBrand = async () => {
    if (!newBrandInput.trim()) return;
    
    try {
      let finalUrl = newBrandInput.trim();
      
      // If input mode is 'name', resolve brand name to URL first
      if (inputMode === 'name') {
        setResolverLoading(true);
        
        try {
          const resolverResult = await FashionArchiveAPI.resolveBrandName(newBrandInput.trim());
          
          if (resolverResult.success && resolverResult.url) {
            finalUrl = resolverResult.url;
            console.log(`🔍 Resolved "${newBrandInput}" to: ${finalUrl}`);
          } else {
            setResultModal({
              type: 'error',
              title: 'Brand Not Found',
              message: `Could not find official website for "${newBrandInput}". ${resolverResult.message || 'Try entering the URL directly.'}`
            });
            setResolverLoading(false);
            return;
          }
        } catch (error) {
          console.error('Error resolving brand name:', error);
          setResultModal({
            type: 'error',
            title: 'Search Error',
            message: 'Error finding brand website. Please try entering the URL directly.'
          });
          setResolverLoading(false);
          return;
        } finally {
          setResolverLoading(false);
        }
      }
      
      // Now validate and add the brand with the final URL
      setValidationLoading(true);
      const result = await FashionArchiveAPI.addBrand({
        url: finalUrl,
        name: inputMode === 'name' ? newBrandInput.trim() : null  // Send brand name for validation
      });
      
      if (result.success) {
        setNewBrandInput('');
        setShowAddBrand(false);
        loadBrands();
        loadStats();
        setResultModal({
          type: 'success',
          title: 'Brand Added Successfully!',
          message: `✅ ${result.brand?.name || 'Brand'} has been validated and added to your collection.`
        });
      } else {
        setResultModal({
          type: 'error',
          title: 'Brand Validation Failed',
          message: result.message || 'Failed to add brand. Please try again.'
        });
      }
    } catch (error) {
      console.error('Error adding brand:', error);
      setResultModal({
        type: 'error',
        title: 'Error Adding Brand',
        message: 'An unexpected error occurred. Please try again.'
      });
    } finally {
      setValidationLoading(false);
    }
  };

  const handleBrandSelect = async (brand) => {
    setSelectedBrand(brand);
    
    // Clear previous results
    setScrapingResult(null);
    setCategoryProducts([]);
    setSelectedCategory(null);
    
    // NEW: Load categories first (clean UX flow)
    try {
      const categoriesData = await FashionArchiveAPI.getBrandCategories(brand.id);
      
      if (categoriesData && !categoriesData.error) {
        if (categoriesData.is_scraped) {
          // Brand has been scraped - show categories
          setCategories(categoriesData.categories);
          setViewMode('categories');
          console.log(`📦 Loaded ${categoriesData.total_categories} categories for ${brand.name}`);
        } else {
          // Brand not scraped yet - show brand info
          setCategories({});
          setViewMode('brand');
          console.log(`🏷️ Brand ${brand.name} not scraped yet`);
        }
      } else {
        console.error('Error loading categories:', categoriesData.error);
        setViewMode('brand');
      }
    } catch (error) {
      console.error('Error loading brand categories:', error);
      setViewMode('brand');
    }
  };

  const handleCategorySelect = async (categoryName) => {
    if (!selectedBrand) return;
    
    setSelectedCategory(categoryName);
    setCategoryProducts([]);
    setSelectedProductIndex(0);
    
    try {
      const productsData = await FashionArchiveAPI.getCategoryProducts(selectedBrand.id, categoryName);
      
      if (productsData && !productsData.error) {
        setCategoryProducts(productsData.products || []);
        setViewMode('products');
        console.log(`📦 Loaded ${productsData.products?.length || 0} products for ${categoryName}`);
        
        // Extract colors for images
        productsData.products?.forEach(product => {
          if (product.image_url) {
            extractImageColor(product.image_url, product.id);
          }
        });
      } else {
        console.error('Error loading category products:', productsData.error);
      }
    } catch (error) {
      console.error('Error loading category products:', error);
    }
  };

  // Removed handleBackToCategories - no longer needed in new always-visible UX

  const handleScrapeProducts = async () => {
    if (!selectedBrand) return;
    
    setScrapingLoading(true);
    setScrapingResult(null);
    
    try {
      console.log('🚀 Starting dynamic parallel collection scraping for brand:', selectedBrand.name);
      
      const result = await FashionArchiveAPI.scrapeBrandProductsStream(
        selectedBrand.id,
        (progressData) => {
          console.log('📊 Progress:', progressData);
          
          if (progressData.status === 'starting') {
            setScrapingResult({
              success: true,
              type: 'progress',
              message: '🔧 Initializing dynamic parallel batching...',
              stage: 'setup'
            });
          } else if (progressData.status === 'scraping_started') {
            setScrapingResult({
              success: true,
              type: 'progress', 
              message: '🤖 AI analyzing page (detecting collections)...',
              stage: 'analysis'
            });
          } else if (progressData.status === 'products_found') {
            setScrapingResult({
              success: true,
              type: 'progress',
              message: `🔥 Found ${progressData.count} products across ${progressData.collections} collections!`,
              stage: 'discovery',
              productsCount: progressData.count,
              collectionsCount: progressData.collections
            });
          } else if (progressData.status === 'downloading_images') {
            setScrapingResult({
              success: true,
              type: 'progress',
              message: `⚡ Parallel download: ${progressData.product_count} products`,
              stage: 'downloading'
            });
          } else if (progressData.status === 'using_cached_images') {
            setScrapingResult({
              success: true,
              type: 'progress',
              message: `♻️ Using ${progressData.count} cached images`,
              stage: 'cached'
            });
          } else if (progressData.status === 'storing_progress') {
            setScrapingResult({
              success: true,
              type: 'progress',
              message: `💾 Stored ${progressData.stored}/${progressData.total} products`,
              stage: 'storing'
            });
          }
        }
      );
      
      if (result && result.status === 'completed') {
        // Scraping completed successfully
        setScrapingResult({
          success: true,
          type: 'products',
          message: `Successfully scraped ${result.total_products || 0} products`,
          productsCount: result.total_products || 0,
          collectionsCount: Object.keys(result.collections || {}).length,
          hasCollections: true,
          collections: result.collections
        });
        
        // NEW: After successful scraping, load categories for clean UX
        const categoriesData = await FashionArchiveAPI.getBrandCategories(selectedBrand.id);
        if (categoriesData && !categoriesData.error && categoriesData.is_scraped) {
          setCategories(categoriesData.categories);
          setViewMode('categories'); // Show categories with "select category" message
          setSelectedCategory(null); // Clear any previous selection
          setCategoryProducts([]); // Clear any previous products
          console.log(`🔄 Refreshed categories after scraping - ${categoriesData.total_categories} categories`);
        }
        
      } else {
        setScrapingResult({
          success: false,
          message: result?.error || 'Dynamic parallel scraping failed'
        });
      }
    } catch (error) {
      console.error('Error in scraping process:', error);
      setScrapingResult({
        success: false,
        message: 'Error in scraping process. Please try again.'
      });
    } finally {
      setScrapingLoading(false);
    }
  };

  // Removed handleScrapeCollection - no longer used in new category-first UX

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
            <div className="mac-label">Loading brands...</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', height: '100vh', flexDirection: 'column', background: 'var(--mac-bg)' }}>
      {/* Title Bar */}
      <div className="mac-title-bar" style={{ 
        height: '20px',
        flexShrink: 0
      }}>
        My Brands - {stats.total_brands || 0} brands, {stats.total_products || 0} products
      </div>

      {/* Main Content */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0, paddingTop: '8px' }}>
        
        {/* Left: Brands List - Similar to SeasonsPanel */}
        <div className="column" style={{ width: '300px' }}>
          <div className="mac-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column', paddingTop: '20px' }}>
            
            {/* Title - matches seasons panel */}
            <div className="mac-label title">
              My Fashion Brands
            </div>

            {/* Brands List - matches seasons listbox */}
            <div className="mac-listbox mac-scrollbar" style={{ flex: 1, margin: '8px 0', marginTop: '16px' }}>
              {brands.length === 0 ? (
                <div className="mac-listbox-item">
                  <div style={{ textAlign: 'center', padding: '20px', color: '#666' }}>
                    <div style={{ fontSize: '24px', marginBottom: '8px' }}>👗</div>
                    <div>No brands added yet</div>
                  </div>
                </div>
              ) : (
                brands.map((brand) => (
                  <div
                    key={brand.id}
                    className={`mac-listbox-item ${selectedBrand?.id === brand.id ? 'selected' : ''}`}
                    onClick={() => handleBrandSelect(brand)}
                  >
                    🏷️ {brand.name || new URL(brand.url).hostname}
                  </div>
                ))
              )}
            </div>

            {/* Action Buttons - matches seasons panel */}
            <div style={{ padding: '8px' }}>
              <button 
                className="mac-button" 
                style={{ width: '100%', marginBottom: '8px' }}
                disabled={!selectedBrand}
                onClick={handleScrapeProducts}
              >
                {scrapingLoading ? 'Scraping Products...' : 'Scrape Products'}
              </button>
              
              <button 
                className="mac-button"
                style={{ width: '100%' }}
                onClick={() => setShowAddBrand(true)}
              >
                Add New Brand
              </button>
            </div>
          </div>
        </div>

        {/* Right: Clean UX Flow */}
        <div className="column" style={{ flex: 1 }}>
          <div className="mac-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            {selectedBrand ? (
              <>
                {/* Brand Header */}
                <div style={{ padding: '20px 20px 16px 20px', borderBottom: '1px solid #e0e0e0' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <h3 style={{ margin: '0', fontSize: '18px' }}>{selectedBrand.name}</h3>
                  </div>
                </div>

                {/* Scraping Status */}
                {scrapingLoading && (
                  <div style={{ 
                    margin: '20px',
                    padding: '16px', 
                    backgroundColor: '#f0f8ff', 
                    border: '1px solid #d0e8ff',
                    borderRadius: '4px'
                  }}>
                    <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '4px' }}>
                      🔄 {scrapingResult?.message || 'Scraping Products...'}
                    </div>
                    <div style={{ fontSize: '12px', color: '#666' }}>
                      {scrapingResult?.stage === 'downloading' ? 'Downloading product images...' : 
                       scrapingResult?.stage === 'analysis' ? 'AI analyzing website structure...' :
                       scrapingResult?.stage === 'discovery' ? 'Discovering product collections...' :
                       'Setting up parallel scraping system...'}
                    </div>
                  </div>
                )}

                {/* MAIN CONTENT AREA */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                  
                  {/* Brand View - Show scrape button */}
                  {viewMode === 'brand' && (
                    <div style={{ 
                      flex: 1,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: '#666',
                      padding: '40px'
                    }}>
                      <div style={{ fontSize: '48px', marginBottom: '20px' }}>🛍️</div>
                      <div style={{ fontSize: '18px', marginBottom: '12px', textAlign: 'center' }}>
                        Ready to discover {selectedBrand.name} products
                      </div>
                      <div style={{ fontSize: '14px', textAlign: 'center', marginBottom: '24px', lineHeight: '1.4' }}>
                        Click "Scrape Products" to analyze the website and<br />
                        discover all product categories and collections
                      </div>
                    </div>
                  )}

                  {/* Categories + Products View - Always show category buttons when scraped */}
                  {(viewMode === 'categories' || viewMode === 'products') && Object.keys(categories).length > 0 && (
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                      
                      {/* Category Toggle Buttons - Mac Style */}
                      <div style={{ 
                        display: 'flex', 
                        flexWrap: 'wrap', 
                        gap: '4px',
                        padding: '12px 20px',
                        borderBottom: '1px solid #e0e0e0',
                        backgroundColor: 'var(--mac-bg)'
                      }}>
                          {Object.entries(categories).map(([categoryName, categoryData]) => (
                            <button
                              key={categoryName}
                              className="mac-button"
                              onClick={() => handleCategorySelect(categoryName)}
                              style={{
                                fontSize: '12px',
                                padding: '4px 8px',
                                minWidth: 'auto',
                                backgroundColor: selectedCategory === categoryName ? 'var(--mac-selected-bg)' : 'var(--mac-button-bg)',
                                color: selectedCategory === categoryName ? 'var(--mac-selected-text)' : 'var(--mac-text)',
                                border: selectedCategory === categoryName ? '2px inset var(--mac-bg)' : '2px outset var(--mac-bg)',
                                cursor: 'pointer'
                              }}
                            >
                              {categoryName} ({categoryData.count})
                            </button>
                          ))}
                      </div>

                      {/* Products Display Area */}
                      {viewMode === 'products' && categoryProducts.length > 0 ? (
                        <div style={{ 
                          flex: 1, 
                          display: 'flex', 
                          gap: '16px',
                          padding: '20px',
                          minHeight: 0,
                          overflow: 'hidden'
                        }}>
                      
                      {/* Product Gallery */}
                      <div style={{ 
                        width: '50%', 
                        display: 'flex', 
                        flexDirection: 'column',
                        minHeight: 0
                      }}>
                        <div className="mac-label" style={{ 
                          fontSize: '12px', 
                          marginBottom: '8px',
                          flexShrink: 0,
                          padding: '4px'
                        }}>
                          {selectedCategory} ({categoryProducts.length} products)
                        </div>
                        
                        <div className="mac-scrollbar" style={{ 
                          flex: 1, 
                          overflowY: 'auto',
                          border: '1px solid #e0e0e0',
                          borderRadius: '4px',
                          padding: '8px'
                        }}>
                          <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
                            gap: '8px',
                            width: '100%'
                          }}>
                            {categoryProducts.map((product, index) => (
                              <div
                                key={product.id}
                                data-product-index={index}
                                className={`gallery-item ${index === selectedProductIndex ? 'selected' : ''}`}
                                style={{
                                  cursor: 'pointer',
                                  border: index === selectedProductIndex ? '2px solid #007bff' : '1px solid #e0e0e0',
                                  borderRadius: '4px',
                                  padding: '4px',
                                  backgroundColor: imageColors[product.id]?.background || '#f8f9fa'
                                }}
                                onClick={() => setSelectedProductIndex(index)}
                                onMouseEnter={() => setHoveredProductIndex(index)}
                                onMouseLeave={() => setHoveredProductIndex(null)}
                              >
                                <div style={{ 
                                  width: '100%', 
                                  aspectRatio: '1',
                                  overflow: 'hidden',
                                  borderRadius: '2px',
                                  marginBottom: '4px'
                                }}>
                                  <img 
                                    src={product.image_url}
                                    alt={product.name}
                                    style={{ 
                                      width: '100%',
                                      height: '100%',
                                      objectFit: 'contain'
                                    }}
                                    onLoad={() => {
                                      extractImageColor(product.image_url, product.id);
                                    }}
                                    onError={(e) => {
                                      e.target.style.display = 'none';
                                      e.target.nextSibling.style.display = 'flex';
                                    }}
                                  />
                                  <div style={{ 
                                    width: '100%',
                                    height: '100%',
                                    backgroundColor: '#f0f0f0',
                                    display: 'none',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    fontSize: '10px',
                                    color: '#999'
                                  }}>
                                    No Image
                                  </div>
                                </div>
                                <div style={{ 
                                  fontSize: '11px', 
                                  textAlign: 'center',
                                  lineHeight: '1.2',
                                  height: '32px',
                                  overflow: 'hidden',
                                  display: '-webkit-box',
                                  WebkitLineClamp: 2,
                                  WebkitBoxOrient: 'vertical',
                                  color: imageColors[product.id]?.text || '#000'
                                }}>
                                  {product.name}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>

                      {/* Selected Product Details */}
                      <div style={{ 
                        flex: 1, 
                        display: 'flex', 
                        flexDirection: 'column',
                        minHeight: 0
                      }}>
                        {(() => {
                          const displayIndex = hoveredProductIndex !== null ? hoveredProductIndex : selectedProductIndex;
                          const currentProduct = categoryProducts[displayIndex];
                          if (!currentProduct) return null;
                          
                          return (
                            <>
                              {/* Product Info Header */}
                              <div style={{ 
                                padding: '16px',
                                border: '1px solid #e0e0e0',
                                borderRadius: '4px',
                                marginBottom: '16px',
                                backgroundColor: '#fff',
                                position: 'relative'
                              }}>
                                <button 
                                  className="mac-button"
                                  onClick={() => {
                                    if (currentProduct.url) {
                                      window.open(currentProduct.url, '_blank');
                                    }
                                  }}
                                  style={{ 
                                    position: 'absolute',
                                    top: '16px',
                                    right: '16px',
                                    backgroundColor: '#007bff',
                                    color: '#fff',
                                    fontSize: '12px'
                                  }}
                                >
                                  Visit Product 🛍️
                                </button>
                                
                                <div style={{ fontSize: '16px', fontWeight: 'bold', marginBottom: '8px', paddingRight: '140px' }}>
                                  {currentProduct.name}
                                </div>
                                
                                {currentProduct.price && (
                                  <div style={{ fontSize: '14px', color: '#0066cc', marginBottom: '8px' }}>
                                    💰 {currentProduct.price}
                                  </div>
                                )}
                                
                                <div style={{ fontSize: '11px', color: '#999' }}>
                                  Product {(hoveredProductIndex !== null ? hoveredProductIndex : selectedProductIndex) + 1} of {categoryProducts.length}
                                </div>
                              </div>

                              {/* Main Product Image */}
                              <div style={{ 
                                flex: 1,
                                border: '1px solid #e0e0e0',
                                borderRadius: '4px',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                minHeight: 0,
                                overflow: 'hidden',
                                padding: '8px',
                                backgroundColor: imageColors[currentProduct.id]?.background || '#fff'
                              }}>
                                <img 
                                  src={currentProduct.image_url}
                                  alt={currentProduct.name}
                                  style={{ 
                                    maxWidth: '100%',
                                    maxHeight: '100%',
                                    objectFit: 'contain',
                                    backgroundColor: 'transparent'
                                  }}
                                  onLoad={() => {
                                    extractImageColor(currentProduct.image_url, currentProduct.id);
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
                                border: '1px solid #e0e0e0',
                                borderRadius: '4px',
                                backgroundColor: '#fff',
                                marginTop: '16px'
                              }}>
                                <button 
                                  className="mac-button" 
                                  onClick={() => {
                                    const newIndex = Math.max(0, selectedProductIndex - 1);
                                    setSelectedProductIndex(newIndex);
                                    scrollToProduct(newIndex);
                                  }}
                                  disabled={selectedProductIndex === 0}
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
                                  {(hoveredProductIndex !== null ? hoveredProductIndex : selectedProductIndex) + 1} of {categoryProducts.length} products
                                </div>
                                
                                <button 
                                  className="mac-button" 
                                  onClick={() => {
                                    const newIndex = Math.min(categoryProducts.length - 1, selectedProductIndex + 1);
                                    setSelectedProductIndex(newIndex);
                                    scrollToProduct(newIndex);
                                  }}
                                  disabled={selectedProductIndex === categoryProducts.length - 1}
                                  style={{ minWidth: '80px' }}
                                >
                                  Next ▶
                                </button>
                              </div>
                            </>
                          );
                        })()}
                      </div>
                    </div>
                      ) : viewMode === 'categories' ? (
                        /* Category Selection Message */
                        <div style={{ 
                          flex: 1,
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          justifyContent: 'center',
                          padding: '40px'
                        }}>
                          <div style={{ fontSize: '24px', marginBottom: '12px' }}>👆</div>
                          <div className="mac-label" style={{ fontSize: '14px', marginBottom: '8px', textAlign: 'center' }}>
                            Select a category above to view products
                          </div>
                          <div className="mac-text" style={{ fontSize: '11px', textAlign: 'center' }}>
                            Click any category button to see its products
                          </div>
                        </div>
                      ) : (
                        /* No products in selected category */
                        <div style={{ 
                          flex: 1,
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          justifyContent: 'center',
                          padding: '40px'
                        }}>
                          <div style={{ fontSize: '32px', marginBottom: '16px' }}>🔍</div>
                          <div className="mac-label" style={{ fontSize: '14px', marginBottom: '8px', textAlign: 'center' }}>
                            No products found in {selectedCategory}
                          </div>
                          <div className="mac-text" style={{ fontSize: '11px', textAlign: 'center' }}>
                            This category may be empty or still loading.
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Empty State - No categories found */}
                  {Object.keys(categories).length === 0 && !scrapingLoading && viewMode !== 'brand' && (
                    <div style={{ 
                      flex: 1,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: '#666',
                      padding: '40px'
                    }}>
                      <div style={{ fontSize: '48px', marginBottom: '20px' }}>📦</div>
                      <div style={{ fontSize: '16px', marginBottom: '8px' }}>
                        No categories found
                      </div>
                      <div style={{ fontSize: '12px', textAlign: 'center' }}>
                        Brand may not be scraped yet. Try clicking "Scrape Products".
                      </div>
                    </div>
                  )}
                  
                </div>
              </>
            ) : (
              <div style={{ 
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flex: 1,
                color: '#666',
                flexDirection: 'column'
              }}>
                <div style={{ fontSize: '32px', marginBottom: '16px' }}>🏷️</div>
                <div>Select a brand to start browsing</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Add Brand Modal - Classic Mac Style */}
      {showAddBrand && (
        <div className="mac-modal-overlay" style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 2000
        }}>
          <div className="mac-dialog" style={{
            backgroundColor: 'var(--mac-bg)',
            border: '2px outset var(--mac-bg)',
            padding: '20px',
            width: '500px',
            minHeight: '320px',
            boxSizing: 'border-box',
            display: 'flex',
            flexDirection: 'column'
          }}>
            
            {/* Title */}
            <div className="mac-label title" style={{ 
              textAlign: 'center',
              marginBottom: '20px',
              fontSize: '14px'
            }}>
              Add New Brand
            </div>
            
            {/* Input Mode Toggle */}
            <div style={{ marginBottom: '16px' }}>
              <div className="mac-label" style={{ marginBottom: '8px', fontSize: '12px' }}>
                Add brand by:
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  className={`mac-button ${inputMode === 'name' ? 'selected' : ''}`}
                  onClick={() => setInputMode('name')}
                  style={{
                    flex: 1,
                    backgroundColor: inputMode === 'name' ? '#007bff' : 'var(--mac-bg)',
                    color: inputMode === 'name' ? '#fff' : '#000',
                    fontSize: '12px',
                    padding: '6px 12px'
                  }}
                  disabled={validationLoading || resolverLoading}
                >
                  📛 Brand Name
                </button>
                <button
                  className={`mac-button ${inputMode === 'url' ? 'selected' : ''}`}
                  onClick={() => setInputMode('url')}
                  style={{
                    flex: 1,
                    backgroundColor: inputMode === 'url' ? '#007bff' : 'var(--mac-bg)',
                    color: inputMode === 'url' ? '#fff' : '#000',
                    fontSize: '12px',
                    padding: '6px 12px'
                  }}
                  disabled={validationLoading || resolverLoading}
                >
                  🌐 Website URL
                </button>
              </div>
            </div>
            
            {/* Input Field */}
            <div style={{ marginBottom: '16px', flex: 1 }}>
              <label className="mac-label" style={{ 
                display: 'block', 
                marginBottom: '8px',
                fontSize: '12px'
              }}>
                {inputMode === 'name' ? 'Brand Name:' : 'Website URL:'}
              </label>
              <input 
                type="text"
                value={newBrandInput}
                onChange={(e) => setNewBrandInput(e.target.value.slice(0, 250))}
                className="mac-input"
                maxLength={250}
                style={{ 
                  width: '100%',
                  padding: '8px',
                  fontSize: '14px',
                  boxSizing: 'border-box',
                  marginBottom: '4px'
                }}
                placeholder={
                  inputMode === 'name' 
                    ? "e.g., Jukuhara, Comme des Garçons, Issey Miyake" 
                    : "https://example-brand.com"
                }
                disabled={validationLoading || resolverLoading}
              />
              <div style={{ 
                fontSize: '11px', 
                color: '#666', 
                textAlign: 'right',
                marginBottom: '8px'
              }}>
                {newBrandInput.length}/250 characters
              </div>

              {/* Help Text */}
              <div className="mac-text" style={{ 
                fontSize: '11px', 
                color: '#666', 
                lineHeight: '1.3',
                padding: '8px',
                border: '1px inset var(--mac-bg)',
                backgroundColor: '#f9f9f9',
                marginBottom: '16px'
              }}>
                {inputMode === 'name' ? (
                  <>
                    🔍 We'll search Google for "<strong>{newBrandInput || '[brand name]'}</strong> official website" and validate it's a small, emerging independent fashion brand.
                  </>
                ) : (
                  <>
                    📋 We'll validate that this is a small, emerging, independent fashion brand (not large retailers or marketplaces) before adding it to your collection.
                  </>
                )}
              </div>

              {/* Loading State */}
              {resolverLoading && (
                <div style={{
                  padding: '12px',
                  border: '1px inset var(--mac-bg)',
                  backgroundColor: '#f0f8ff',
                  marginBottom: '16px',
                  fontSize: '12px'
                }}>
                  🔍 Searching for "<strong>{newBrandInput}</strong>" official website...
                </div>
              )}

              {validationLoading && (
                <div style={{
                  padding: '12px',
                  border: '1px inset var(--mac-bg)',
                  backgroundColor: '#fff0f0',
                  marginBottom: '16px',
                  fontSize: '12px'
                }}>
                  🤖 AI validating brand as small/independent...
                </div>
              )}
            </div>

            {/* Buttons */}
            <div style={{ 
              display: 'flex', 
              gap: '12px', 
              justifyContent: 'flex-end',
              marginTop: 'auto'
            }}>
              <button 
                className="mac-button"
                onClick={() => {
                  setShowAddBrand(false);
                  setNewBrandInput('');
                }}
                disabled={validationLoading || resolverLoading}
                style={{ minWidth: '80px' }}
              >
                Cancel
              </button>
              <button 
                className="mac-button"
                onClick={handleAddBrand}
                disabled={!newBrandInput.trim() || validationLoading || resolverLoading}
                style={{ 
                  backgroundColor: (validationLoading || resolverLoading || !newBrandInput.trim()) ? '#ccc' : '#007bff',
                  color: '#fff',
                  minWidth: '100px'
                }}
              >
                {resolverLoading ? 'Searching...' : validationLoading ? 'Validating...' : 'Add Brand'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Result Modal - Success/Error */}
      <MacModal
        show={!!resultModal}
        onClose={() => setResultModal(null)}
        type={resultModal?.type || 'info'}
        title={resultModal?.title || ''}
        message={resultModal?.message || ''}
        zIndex={2100}
      />
    </div>
  );
}

export default MyBrandsPanel;