import React, { useState, useEffect } from 'react';
import { FashionArchiveAPI } from '../services/api';
import MacModal from './MacModal';

function MyBrandsPanel({ currentView }) {
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
  const [products, setProducts] = useState([]);
  const [scrapingResult, setScrapingResult] = useState(null);
  const [selectedProductIndex, setSelectedProductIndex] = useState(0);
  const [hoveredProductIndex, setHoveredProductIndex] = useState(null); // Track hovered product for preview
  const [resultModal, setResultModal] = useState(null); // { type: 'success'|'error', title: '', message: '' }
  const [imageColors, setImageColors] = useState({}); // Store extracted colors for each image
  const [collections, setCollections] = useState({}); // Store collections data from API
  const [selectedCategory, setSelectedCategory] = useState('all'); // Track selected category filter
  const [filteredProducts, setFilteredProducts] = useState([]); // Store filtered products
  const [collectionsOnly, setCollectionsOnly] = useState([]); // Store collection metadata only
  const [selectedCollectionSlug, setSelectedCollectionSlug] = useState(null); // Track selected collection
  const [viewMode, setViewMode] = useState('collections'); // 'collections' or 'products'

  // Filter products by category
  const filterProductsByCategory = (category) => {
    setSelectedCategory(category);
    if (category === 'all') {
      setFilteredProducts(products);
    } else {
      const filtered = products.filter(product => product.collection === category);
      setFilteredProducts(filtered);
    }
    setSelectedProductIndex(0);
  };

  // Update filtered products when products or selectedCategory changes
  useEffect(() => {
    if (selectedCategory === 'all') {
      setFilteredProducts(products);
    } else {
      const filtered = products.filter(product => product.collection === selectedCategory);
      setFilteredProducts(filtered);
    }
  }, [products, selectedCategory]);

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
      // Only handle arrow keys when we have products
      if (filteredProducts.length === 0) return;

      switch (event.key) {
        case 'ArrowLeft':
          event.preventDefault();
          setSelectedProductIndex(prev => {
            const newIndex = prev > 0 ? prev - 1 : filteredProducts.length - 1;
            // Scroll to show the new selection
            scrollToProduct(newIndex);
            return newIndex;
          });
          break;
        case 'ArrowRight':
          event.preventDefault();
          setSelectedProductIndex(prev => {
            const newIndex = prev < filteredProducts.length - 1 ? prev + 1 : 0;
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
  }, [filteredProducts.length]);

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
    setProducts([]);
    setCollections({});
    setCollectionsOnly([]);
    setScrapingResult(null);
    setViewMode('collections');
    setSelectedCollectionSlug(null);
    
    // Load collections only (no products initially)
    try {
      const collectionsData = await FashionArchiveAPI.getBrandCollections(brand.id);
      if (collectionsData) {
        setCollectionsOnly(collectionsData.collections || []);
        console.log(`📂 Loaded ${collectionsData.collections?.length || 0} collections for ${brand.name}`);
      }
    } catch (error) {
      console.error('Error loading brand collections:', error);
    }
  };

  const handleCollectionSelect = async (collection) => {
    if (!selectedBrand) return;
    
    setSelectedCollectionSlug(collection.slug);
    setViewMode('products');
    setProducts([]);
    setFilteredProducts([]);
    
    // Load products for this specific collection
    try {
      const productsData = await FashionArchiveAPI.getCollectionProducts(selectedBrand.id, collection.slug);
      if (productsData) {
        setProducts(productsData.products || []);
        setFilteredProducts(productsData.products || []);
        setSelectedProductIndex(0);
        console.log(`👕 Loaded ${productsData.products?.length || 0} products for ${collection.name}`);
      }
    } catch (error) {
      console.error('Error loading collection products:', error);
    }
  };

  const handleBackToCollections = () => {
    setViewMode('collections');
    setSelectedCollectionSlug(null);
    setProducts([]);
    setFilteredProducts([]);
  };

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
        
        // Load the products from database to display them
        const productsData = await FashionArchiveAPI.getBrandProducts(selectedBrand.id);
        if (productsData) {
          if (productsData.collections) {
            setCollections(productsData.collections);
            setProducts(productsData.products || []);
            setFilteredProducts(productsData.products || []);
            setSelectedCategory('all');
          } else {
            setProducts(productsData.products || []);
            setFilteredProducts(productsData.products || []);
          }
        }
        setSelectedProductIndex(0);
        
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

  const handleScrapeCollection = async (collectionUrl, collectionName) => {
    if (!selectedBrand) return;
    
    setScrapingLoading(true);
    console.log('🎯 Scraping collection:', collectionName, '→', collectionUrl);
    
    try {
      const result = await FashionArchiveAPI.scrapeBrandProducts(selectedBrand.id, collectionUrl);
      
      if (result.success) {
        setScrapingResult({
          success: true,
          type: 'products',
          message: `${collectionName}: ${result.message}`,
          productsCount: result.products?.length || 0,
          strategy: result.strategy_used,
          collectionName: collectionName
        });
        
        // Load the products to display
        const productsData = await FashionArchiveAPI.getBrandProducts(selectedBrand.id);
        if (productsData) {
          if (productsData.collections) {
            setCollections(productsData.collections);
            setProducts(productsData.products || []);
            setFilteredProducts(productsData.products || []);
            setSelectedCategory('all');
          } else {
            setProducts(productsData.products || []);
            setFilteredProducts(productsData.products || []);
          }
        }
        setSelectedProductIndex(0); // Reset to first product
        
      } else {
        setScrapingResult({
          success: false,
          message: `${collectionName}: ${result.message || 'Scraping failed'}`
        });
      }
    } catch (error) {
      console.error('Error scraping collection:', error);
      setScrapingResult({
        success: false,
        message: `Error scraping ${collectionName}. Please try again.`
      });
    } finally {
      setScrapingLoading(false);
    }
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
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', paddingTop: '8px' }}>
        
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
                brands.map((brand, index) => (
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

        {/* Right: Scraping Results and Products */}
        <div className="column" style={{ flex: 1 }}>
          <div className="mac-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            {selectedBrand ? (
              <>
                {/* Collection Selection State - Full Width */}
                {!scrapingLoading && scrapingResult?.type === 'collections' ? (
                  <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                    {/* Brand Info Header */}
                    <div style={{ padding: '20px', paddingBottom: '10px' }}>
                      <h3 style={{ margin: '0 0 8px 0' }}>{selectedBrand.name}</h3>
                    </div>
                    
                    {/* Collections List */}
                    <div className="mac-listbox mac-scrollbar" style={{ flex: 1, margin: '0 20px 20px 20px' }}>
                      {scrapingResult.collections.map((collection, index) => (
                        <div
                          key={index}
                          className="mac-listbox-item"
                          onClick={() => handleScrapeCollection(collection.url, collection.name)}
                          style={{ cursor: 'pointer' }}
                        >
                          📁 {collection.name}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                    
                    {/* Brand Info Header */}
                    <div style={{ padding: '20px 20px 0 20px', marginBottom: '20px' }}>
                      <h3 style={{ margin: '0 0 8px 0' }}>{selectedBrand.name}</h3>
                    </div>

                    {/* Collection Tabs - Always Visible */}
                    {collectionsOnly.length > 0 && (
                      <div style={{ 
                        padding: '0 20px',
                        marginBottom: '20px',
                        borderBottom: '1px solid #e0e0e0'
                      }}>
                        <div style={{ 
                          display: 'flex', 
                          flexWrap: 'wrap', 
                          gap: '2px', 
                          marginBottom: '12px'
                        }}>
                          <button
                            className={`mac-button ${viewMode === 'collections' ? 'selected' : ''}`}
                            onClick={() => setViewMode('collections')}
                            style={{
                              fontSize: '12px',
                              padding: '4px 8px',
                              minWidth: 'auto',
                              backgroundColor: viewMode === 'collections' ? 'var(--mac-selected-bg)' : 'var(--mac-button-bg)',
                              color: viewMode === 'collections' ? 'var(--mac-selected-text)' : 'var(--mac-text)',
                              border: viewMode === 'collections' ? '2px inset var(--mac-bg)' : '2px outset var(--mac-bg)'
                            }}
                          >
                            📂 All Collections
                          </button>
                          {collectionsOnly.map((collection, index) => (
                            <button
                              key={index}
                              className={`mac-button ${selectedCollectionSlug === collection.slug ? 'selected' : ''}`}
                              onClick={() => handleCollectionSelect(collection)}
                              style={{
                                fontSize: '12px',
                                padding: '4px 8px',
                                minWidth: 'auto',
                                backgroundColor: selectedCollectionSlug === collection.slug ? 'var(--mac-selected-bg)' : 'var(--mac-button-bg)',
                                color: selectedCollectionSlug === collection.slug ? 'var(--mac-selected-text)' : 'var(--mac-text)',
                                border: selectedCollectionSlug === collection.slug ? '2px inset var(--mac-bg)' : '2px outset var(--mac-bg)'
                              }}
                            >
                              {collection.name} ({collection.count})
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Scraping Status */}
                    {scrapingLoading && (
                      <div style={{ 
                        padding: '16px', 
                        backgroundColor: '#f0f8ff', 
                        border: '1px solid #d0e8ff',
                        borderRadius: '4px',
                        marginBottom: '16px'
                      }}>
                        <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '4px' }}>
                          🔄 Scraping Products...
                        </div>
                        <div style={{ fontSize: '12px', color: '#666' }}>
                          Analyzing website and downloading product images to downloads folder
                        </div>
                      </div>
                    )}

                    {/* Collections View */}
                    {viewMode === 'collections' && collectionsOnly.length > 0 && (
                      <div style={{ 
                        flex: 1, 
                        display: 'flex', 
                        flexDirection: 'column',
                        minHeight: 0,
                        overflow: 'hidden'
                      }}>
                        <div style={{ 
                          fontSize: '14px', 
                          fontWeight: 'bold', 
                          marginBottom: '12px',
                          flexShrink: 0
                        }}>
                          📂 Collections ({collectionsOnly.length})
                        </div>
                        
                        <div className="mac-scrollbar" style={{ 
                          flex: 1, 
                          overflowY: 'auto',
                          overflowX: 'hidden',
                          border: '1px solid #e0e0e0',
                          borderRadius: '4px',
                          padding: '16px',
                          minHeight: 0,
                          maxHeight: '100%'
                        }}>
                          <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
                            gap: '16px',
                            width: '100%'
                          }}>
                            {collectionsOnly.map((collection, index) => (
                              <div
                                key={index}
                                className="mac-button"
                                onClick={() => handleCollectionSelect(collection)}
                                style={{
                                  cursor: 'pointer',
                                  padding: '16px',
                                  textAlign: 'center',
                                  backgroundColor: 'var(--mac-button-bg)',
                                  border: '2px outset var(--mac-bg)',
                                  fontSize: '14px',
                                  minHeight: '80px',
                                  display: 'flex',
                                  flexDirection: 'column',
                                  alignItems: 'center',
                                  justifyContent: 'center'
                                }}
                              >
                                <div style={{ fontSize: '24px', marginBottom: '8px' }}>📁</div>
                                <div style={{ fontWeight: 'bold', marginBottom: '4px' }}>
                                  {collection.name}
                                </div>
                                <div style={{ fontSize: '12px', color: '#666' }}>
                                  {collection.count} products
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Products Gallery - Two Column Layout */}
                    {viewMode === 'products' && filteredProducts.length > 0 && (
                      <div style={{ 
                        flex: 1, 
                        display: 'flex', 
                        gap: '16px',
                        minHeight: 0,
                        maxHeight: 'calc(100vh - 180px)',
                        overflow: 'hidden'
                      }}>
                        
                        {/* Left: Product Gallery - Organized by Collections */}
                        <div style={{ 
                          width: '50%', 
                          display: 'flex', 
                          flexDirection: 'column',
                          minHeight: 0,
                          maxHeight: '100%'
                        }}>
                          <div style={{ 
                            fontSize: '14px', 
                            fontWeight: 'bold', 
                            marginBottom: '12px',
                            flexShrink: 0
                          }}>
                            📦 {selectedCollectionSlug ? collectionsOnly.find(c => c.slug === selectedCollectionSlug)?.name || 'Collection' : 'Products'} ({filteredProducts.length})
                          </div>
                          
                          
                          <div className="mac-scrollbar" style={{ 
                            flex: 1, 
                            overflowY: 'auto',
                            overflowX: 'hidden',
                            border: '1px solid #e0e0e0',
                            borderRadius: '4px',
                            padding: '8px',
                            minHeight: 0,
                            maxHeight: '100%'
                          }}>
                            {(() => {
                              // Group products by collection
                              const grouped = {};
                              const ungrouped = [];
                              
                              filteredProducts.forEach((product, index) => {
                                const collectionName = product.collection_name;
                                if (collectionName) {
                                  if (!grouped[collectionName]) {
                                    grouped[collectionName] = [];
                                  }
                                  grouped[collectionName].push({ ...product, originalIndex: index });
                                } else {
                                  ungrouped.push({ ...product, originalIndex: index });
                                }
                              });
                              
                              const collectionNames = Object.keys(grouped);
                              const hasCollections = collectionNames.length > 0;
                              
                              return (
                                <div style={{ width: '100%' }}>
                                  {/* Show collections if they exist */}
                                  {hasCollections && collectionNames.map(collectionName => (
                                    <div key={collectionName} style={{ marginBottom: '24px' }}>
                                      {/* Collection Header */}
                                      <div style={{ 
                                        fontSize: '12px', 
                                        fontWeight: 'bold', 
                                        color: '#666',
                                        marginBottom: '8px',
                                        padding: '4px 8px',
                                        backgroundColor: '#f8f9fa',
                                        border: '1px solid #e9ecef',
                                        borderRadius: '4px'
                                      }}>
                                        📁 {collectionName} ({grouped[collectionName].length} products)
                                      </div>
                                      
                                      {/* Collection Products Grid */}
                                      <div style={{
                                        display: 'grid',
                                        gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
                                        gap: '8px',
                                        width: '100%',
                                        marginBottom: '12px'
                                      }}>
                                        {grouped[collectionName].map((product) => (
                                          <div
                                            key={product.id}
                                            data-product-index={product.originalIndex}
                                            className={`gallery-item ${product.originalIndex === selectedProductIndex ? 'selected' : ''}`}
                                            style={{
                                              cursor: 'pointer',
                                              border: product.originalIndex === selectedProductIndex ? '2px solid #007bff' : 'none',
                                              borderRadius: '4px',
                                              padding: '4px',
                                              backgroundColor: imageColors[product.id]?.background || '#e0e0e0'
                                            }}
                                            onClick={() => setSelectedProductIndex(product.originalIndex)}
                                            onMouseEnter={() => setHoveredProductIndex(product.originalIndex)}
                                            onMouseLeave={() => setHoveredProductIndex(null)}
                                          >
                                            <div style={{ 
                                              width: '100%', 
                                              aspectRatio: '1',
                                              overflow: 'hidden',
                                              borderRadius: '2px',
                                              marginBottom: '4px',
                                              display: 'flex',
                                              alignItems: 'center',
                                              justifyContent: 'center'
                                            }}>
                                              <img 
                                                src={product.images && product.images[0] ? product.images[0] : product.image_url}
                                                alt={product.name}
                                                style={{ 
                                                  width: '100% !important',
                                                  height: '100% !important',
                                                  objectFit: 'cover !important',
                                                  display: 'block !important',
                                                  maxWidth: 'none !important',
                                                  maxHeight: 'none !important'
                                                }}
                                                onLoad={() => {
                                                  const imageUrl = product.images && product.images[0] ? product.images[0] : product.image_url;
                                                  extractImageColor(imageUrl, product.id);
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
                                              fontSize: '12px', 
                                              textAlign: 'center',
                                              lineHeight: '1.2',
                                              height: '24px',
                                              overflow: 'hidden',
                                              display: '-webkit-box',
                                              WebkitLineClamp: 2,
                                              WebkitBoxOrient: 'vertical',
                                              color: imageColors[product.id]?.text || '#000'
                                            }}>
                                              {product.name?.replace(`[${collectionName}] `, '') || 'Untitled'}
                                            </div>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  ))}
                                  
                                  {/* Show ungrouped products if any */}
                                  {ungrouped.length > 0 && (
                                    <div style={{ marginBottom: '24px' }}>
                                      {hasCollections && (
                                        <div style={{ 
                                          fontSize: '12px', 
                                          fontWeight: 'bold', 
                                          color: '#666',
                                          marginBottom: '8px',
                                          padding: '4px 8px',
                                          backgroundColor: '#f8f9fa',
                                          border: '1px solid #e9ecef',
                                          borderRadius: '4px'
                                        }}>
                                          📦 Other Products ({ungrouped.length} products)
                                        </div>
                                      )}
                                      
                                      <div style={{
                                        display: 'grid',
                                        gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
                                        gap: '8px',
                                        width: '100%'
                                      }}>
                                        {ungrouped.map((product) => (
                                          <div
                                            key={product.id}
                                            data-product-index={product.originalIndex}
                                            className={`gallery-item ${product.originalIndex === selectedProductIndex ? 'selected' : ''}`}
                                            style={{
                                              cursor: 'pointer',
                                              border: product.originalIndex === selectedProductIndex ? '2px solid #007bff' : 'none',
                                              borderRadius: '4px',
                                              padding: '4px',
                                              backgroundColor: imageColors[product.id]?.background || '#e0e0e0'
                                            }}
                                            onClick={() => setSelectedProductIndex(product.originalIndex)}
                                            onMouseEnter={() => setHoveredProductIndex(product.originalIndex)}
                                            onMouseLeave={() => setHoveredProductIndex(null)}
                                          >
                                            <div style={{ 
                                              width: '100%', 
                                              aspectRatio: '1',
                                              overflow: 'hidden',
                                              borderRadius: '2px',
                                              marginBottom: '4px',
                                              display: 'flex',
                                              alignItems: 'center',
                                              justifyContent: 'center'
                                            }}>
                                              <img 
                                                src={product.images && product.images[0] ? product.images[0] : product.image_url}
                                                alt={product.name}
                                                style={{ 
                                                  width: '100% !important',
                                                  height: '100% !important',
                                                  objectFit: 'cover !important',
                                                  display: 'block !important',
                                                  maxWidth: 'none !important',
                                                  maxHeight: 'none !important'
                                                }}
                                                onLoad={() => {
                                                  const imageUrl = product.images && product.images[0] ? product.images[0] : product.image_url;
                                                  extractImageColor(imageUrl, product.id);
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
                                              fontSize: '12px', 
                                              textAlign: 'center',
                                              lineHeight: '1.2',
                                              height: '24px',
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
                                  )}
                                </div>
                              );
                            })()}
                          </div>
                        </div>

                        {/* Right: Selected Product Details */}
                        <div style={{ 
                          flex: 1, 
                          display: 'flex', 
                          flexDirection: 'column',
                          minHeight: 0,
                          maxHeight: '100%',
                          overflow: 'hidden'
                        }}>
                          {(() => {
                            // Show hovered product if hovering, otherwise show selected product
                            const displayIndex = hoveredProductIndex !== null ? hoveredProductIndex : selectedProductIndex;
                            const currentProduct = filteredProducts[displayIndex];
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
                                  {/* Visit Product button - top right */}
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
                                    Product {(hoveredProductIndex !== null ? hoveredProductIndex : selectedProductIndex) + 1} of {filteredProducts.length}
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
                                    src={currentProduct.images && currentProduct.images[0] ? currentProduct.images[0] : currentProduct.image_url}
                                    alt={currentProduct.name}
                                    style={{ 
                                      maxWidth: '100%',
                                      maxHeight: '100%',
                                      objectFit: 'contain'
                                    }}
                                    onLoad={() => {
                                      const imageUrl = currentProduct.images && currentProduct.images[0] ? currentProduct.images[0] : currentProduct.image_url;
                                      extractImageColor(imageUrl, currentProduct.id);
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
                                    {(hoveredProductIndex !== null ? hoveredProductIndex : selectedProductIndex) + 1} of {filteredProducts.length} products
                                  </div>
                                  
                                  <button 
                                    className="mac-button" 
                                    onClick={() => {
                                      const newIndex = Math.min(filteredProducts.length - 1, selectedProductIndex + 1);
                                      setSelectedProductIndex(newIndex);
                                      scrollToProduct(newIndex);
                                    }}
                                    disabled={selectedProductIndex === filteredProducts.length - 1}
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
                    )}


                    {/* Error State */}
                    {!scrapingLoading && scrapingResult && !scrapingResult.success && (
                      <div style={{ 
                        flex: 1,
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#dc3545',
                        textAlign: 'center'
                      }}>
                        <div style={{ fontSize: '32px', marginBottom: '16px' }}>❌</div>
                        <div style={{ fontSize: '16px', marginBottom: '8px', fontWeight: 'bold' }}>
                          Scraping Failed
                        </div>
                        <div style={{ fontSize: '14px' }}>
                          {scrapingResult.message}
                        </div>
                      </div>
                    )}

                    {/* Initial State */}
                    {!scrapingLoading && !scrapingResult && filteredProducts.length === 0 && (
                      <div style={{ 
                        flex: 1,
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#666'
                      }}>
                        <div style={{ fontSize: '32px', marginBottom: '16px' }}>🛍️</div>
                        <div style={{ fontSize: '16px', marginBottom: '8px' }}>
                          Ready to scrape {selectedBrand.name}
                        </div>
                        <div style={{ fontSize: '12px', textAlign: 'center' }}>
                          Click "Scrape Products" to discover collections and extract products<br />
                          No validation needed - this brand is already approved!
                        </div>
                      </div>
                    )}
                  </div>
                )}
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
                <div>Select a brand to start scraping</div>
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