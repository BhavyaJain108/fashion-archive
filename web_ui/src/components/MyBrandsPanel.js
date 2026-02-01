import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import Fuse from 'fuse.js';
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

  // Search + sort state
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('');
  const [searchResults, setSearchResults] = useState(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedDropdownIdx, setSelectedDropdownIdx] = useState(-1);
  const searchTimerRef = useRef(null);
  const searchInputRef = useRef(null);

  // Resizable detail panel
  const [detailPanelWidth, setDetailPanelWidth] = useState(400);
  const isResizing = useRef(false);

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

      // Track seen products by URL and by brand+name (cross-category only)
      const seenProductUrls = new Set();
      const deduplicatedProducts = [];

      // Helper function to get product URL (handles both old and new formats)
      const getProductUrl = (product) => {
        return product.url || product.product_url || '';
      };

      // For cross-category dedup: track brand+name from first batch (new category)
      // so duplicates from OTHER categories get removed, but same-category dupes stay
      const newCategoryNames = new Set();
      const existingCategoryNames = new Set();

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

      // Deduplicate: prioritize new products, then add existing ones
      // Cross-category dedup by brand+name; same-category dupes are kept
      for (const product of newProducts) {
        const url = getProductUrl(product);
        if (url && seenProductUrls.has(url)) continue;
        if (url) seenProductUrls.add(url);
        const brand = (product.brand || product.brand_id || '').toLowerCase();
        const name = (product.name || product.product_name || '').toLowerCase();
        if (brand && name) newCategoryNames.add(`${brand}::${name}`);
        deduplicatedProducts.push(product);
      }

      for (const product of existingProductsWithCategory) {
        const url = getProductUrl(product);
        if (url && seenProductUrls.has(url)) continue;
        if (url) seenProductUrls.add(url);
        // Skip if same brand+name already in the new category batch
        const brand = (product.brand || product.brand_id || '').toLowerCase();
        const name = (product.name || product.product_name || '').toLowerCase();
        if (brand && name) {
          const key = `${brand}::${name}`;
          if (newCategoryNames.has(key)) continue;
          if (existingCategoryNames.has(key)) continue;
          existingCategoryNames.add(key);
        }
        deduplicatedProducts.push(product);
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

  // Flatten all categories with full paths + build trigram index for O(1) lookup
  const { allCategories, trigramIndex } = useMemo(() => {
    const leaves = [];
    const collect = (brand, cats, path) => {
      if (!cats) return;
      for (const cat of cats) {
        const currentPath = [...path, cat.name || ''];
        if (cat.children && cat.children.length > 0) {
          collect(brand, cat.children, currentPath);
        } else {
          const fullPath = [(brand.name || brand.brand_id || ''), ...currentPath].join(' / ');
          leaves.push({
            fullPath,
            fullPathLower: fullPath.toLowerCase(),
            name: cat.name || '',
            url: cat.url,
            brandId: brand.brand_id,
            leafKeys: [`${brand.brand_id}::${cat.url}`],
          });
        }
      }
    };
    for (const brand of brands) {
      collect(brand, brand.navigation, []);
    }
    leaves.sort((a, b) => a.fullPathLower.localeCompare(b.fullPathLower));

    // Build trigram index: map each 3-char substring → Set of category indices
    const idx = {};
    for (let i = 0; i < leaves.length; i++) {
      const s = leaves[i].fullPathLower;
      for (let j = 0; j <= s.length - 3; j++) {
        const tri = s.slice(j, j + 3);
        if (!idx[tri]) idx[tri] = new Set();
        idx[tri].add(i);
      }
      // Also index bigrams for short queries
      for (let j = 0; j <= s.length - 2; j++) {
        const bi = s.slice(j, j + 2);
        const key = `_bi_${bi}`;
        if (!idx[key]) idx[key] = new Set();
        idx[key].add(i);
      }
    }

    return { allCategories: leaves, trigramIndex: idx };
  }, [brands]);

  // Categories matching search query via trigram index intersection, then verify
  const matchingCategories = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return [];

    // For very short queries (1 char), fall back to linear scan
    if (q.length === 1) {
      return allCategories.filter(cat => cat.fullPathLower.includes(q));
    }

    // Get candidate set via trigram/bigram index intersection
    let candidates = null;
    if (q.length === 2) {
      candidates = trigramIndex[`_bi_${q}`];
    } else {
      // Intersect trigram sets for each trigram in query
      for (let i = 0; i <= q.length - 3; i++) {
        const tri = q.slice(i, i + 3);
        const set = trigramIndex[tri];
        if (!set) return []; // trigram not found = no matches
        if (candidates === null) {
          candidates = new Set(set);
        } else {
          for (const idx of candidates) {
            if (!set.has(idx)) candidates.delete(idx);
          }
        }
        if (candidates.size === 0) return [];
      }
    }

    if (!candidates) return [];

    // Verify candidates with full substring check (hash narrowed the set)
    const results = [];
    for (const idx of candidates) {
      if (allCategories[idx].fullPathLower.includes(q)) {
        results.push(allCategories[idx]);
      }
    }
    return results.sort((a, b) => a.fullPathLower.localeCompare(b.fullPathLower));
  }, [searchQuery, allCategories, trigramIndex]);

  // Deduplicate products by URL, then by name across different categories (not within same category)
  const deduplicateProducts = useCallback((productArrays) => {
    const seenUrl = new Set();
    // Track which brand+name combos we've seen AND which array index they came from
    const brandNameSource = new Map(); // "brand::name" → array index
    const results = [];
    for (let i = 0; i < productArrays.length; i++) {
      for (const p of productArrays[i]) {
        const url = p.url || p.product_url || '';
        if (url && seenUrl.has(url)) continue;
        if (url) seenUrl.add(url);

        // Cross-category name dedup: skip if same brand+name from a DIFFERENT array
        const brand = (p.brand || p.brand_id || '').toLowerCase();
        const name = (p.name || p.product_name || '').toLowerCase();
        if (brand && name) {
          const key = `${brand}::${name}`;
          if (brandNameSource.has(key) && brandNameSource.get(key) !== i) continue;
          brandNameSource.set(key, i);
        }

        results.push(p);
      }
    }
    return results;
  }, []);

  // Load products for a specific dropdown category
  const loadCategoryProducts = useCallback(async (category) => {
    setSearchLoading(true);
    try {
      // Fire all leaf key fetches in parallel
      const fetches = category.leafKeys.map(async (leafKey) => {
        const [brandId, categoryUrl] = leafKey.split('::');
        const response = await fetch(
          `http://localhost:8081/api/products?brand_id=${brandId}&classification_url=${encodeURIComponent(categoryUrl)}&limit=1000`
        );
        if (response.ok) {
          const data = await response.json();
          return data.products || [];
        }
        return [];
      });
      const results = await Promise.all(fetches);
      setSearchResults(deduplicateProducts(results));
    } catch (e) {
      console.error('Category load failed:', e);
    } finally {
      setSearchLoading(false);
    }
  }, [deduplicateProducts]);

  // Concurrent search: fires backend product search + matching category product fetches in parallel
  const executeSearch = useCallback(async (query) => {
    const q = query.trim();
    if (!q) {
      setSearchResults(null);
      return;
    }
    setSearchLoading(true);
    try {
      // 1) Backend full-text search
      const textSearchPromise = fetch(
        `http://localhost:8081/api/products/search?q=${encodeURIComponent(q)}&limit=200`
      ).then(r => r.ok ? r.json().then(d => d.products || []) : []).catch(() => []);

      // 2) Fetch products from all matching categories in parallel
      const catFetches = matchingCategories.flatMap(cat =>
        cat.leafKeys.map(leafKey => {
          const [brandId, categoryUrl] = leafKey.split('::');
          return fetch(
            `http://localhost:8081/api/products?brand_id=${brandId}&classification_url=${encodeURIComponent(categoryUrl)}&limit=500`
          ).then(r => r.ok ? r.json().then(d => d.products || []) : []).catch(() => []);
        })
      );

      // Await all concurrently
      const [textResults, ...catResults] = await Promise.all([textSearchPromise, ...catFetches]);

      // Deduplicate: text search results first (higher relevance), then category products
      const merged = deduplicateProducts([textResults, ...catResults]);

      // Fuzzy re-rank the merged set
      const fuse = new Fuse(merged, {
        keys: ['name', 'product_name', 'brand', 'brand_id', 'description', 'category'],
        threshold: 0.5,
        ignoreLocation: true,
        minMatchCharLength: 2,
      });
      const fuzzyResults = fuse.search(q).map(r => r.item);
      setSearchResults(fuzzyResults.length > 0 ? fuzzyResults : merged);
    } catch (e) {
      console.error('Search failed:', e);
    } finally {
      setSearchLoading(false);
    }
  }, [matchingCategories, deduplicateProducts]);

  // Handle search input — show dropdown + debounced auto-search for products simultaneously
  const handleSearchChange = useCallback((query) => {
    setSearchQuery(query);
    setSelectedDropdownIdx(-1);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);

    if (!query.trim()) {
      setSearchResults(null);
      setShowDropdown(false);
      return;
    }

    setShowDropdown(true);

    // Debounced product search fires simultaneously with instant category dropdown
    searchTimerRef.current = setTimeout(() => {
      executeSearch(query);
    }, 300);
  }, [executeSearch]);

  // Handle keyboard in search input
  const handleSearchKeyDown = useCallback((e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
      if (selectedDropdownIdx >= 0 && selectedDropdownIdx < matchingCategories.length) {
        loadCategoryProducts(matchingCategories[selectedDropdownIdx]);
      } else {
        executeSearch(searchQuery);
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setShowDropdown(true);
      setSelectedDropdownIdx(prev => Math.min(prev + 1, matchingCategories.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedDropdownIdx(prev => Math.max(prev - 1, -1));
    } else if (e.key === 'Escape') {
      setShowDropdown(false);
    }
  }, [searchQuery, selectedDropdownIdx, matchingCategories, loadCategoryProducts, executeSearch]);

  // Parse price to number for sorting
  const parsePrice = useCallback((product) => {
    const raw = product.price || product.attributes?.price || '';
    const num = parseFloat(String(raw).replace(/[^0-9.]/g, ''));
    return isNaN(num) ? 0 : num;
  }, []);

  // Compute displayed products: use search results when searching, else category products
  const displayProducts = useMemo(() => {
    let result = searchResults !== null ? searchResults : products;

    // Sort
    if (sortBy) {
      result = [...result].sort((a, b) => {
        const nameA = (a.name || a.product_name || '').toLowerCase();
        const nameB = (b.name || b.product_name || '').toLowerCase();
        switch (sortBy) {
          case 'name-asc': return nameA.localeCompare(nameB);
          case 'name-desc': return nameB.localeCompare(nameA);
          case 'price-asc': return parsePrice(a) - parsePrice(b);
          case 'price-desc': return parsePrice(b) - parsePrice(a);
          default: return 0;
        }
      });
    }

    return result;
  }, [products, searchResults, sortBy, parsePrice]);

  // Drag resize handlers for detail panel
  const handleResizeMouseDown = useCallback((e) => {
    e.preventDefault();
    isResizing.current = true;
    const startX = e.clientX;
    const startWidth = detailPanelWidth;

    const onMouseMove = (e) => {
      if (!isResizing.current) return;
      const delta = startX - e.clientX; // dragging left = wider
      const newWidth = Math.min(window.innerWidth * 0.5, Math.max(300, startWidth + delta));
      setDetailPanelWidth(newWidth);
    };

    const onMouseUp = () => {
      isResizing.current = false;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, [detailPanelWidth]);

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
      <div className="product-gallery">
        {/* Search + Sort Toolbar */}
        <div className="product-toolbar">
            <div className="search-wrapper">
              <input
                ref={searchInputRef}
                type="text"
                className="product-search-input"
                placeholder="Search products..."
                value={searchQuery}
                onChange={(e) => handleSearchChange(e.target.value)}
                onKeyDown={handleSearchKeyDown}
                onFocus={() => { if (searchQuery.trim()) setShowDropdown(true); }}
                onBlur={() => {}}
              />
              {showDropdown && matchingCategories.length > 0 && (
                <div className="search-dropdown">
                  {matchingCategories.map((cat, idx) => {
                    const q = searchQuery.trim().toLowerCase();
                    const pathLower = cat.fullPath.toLowerCase();
                    const matchIdx = pathLower.indexOf(q);
                    const before = cat.fullPath.slice(0, matchIdx);
                    const match = cat.fullPath.slice(matchIdx, matchIdx + q.length);
                    const after = cat.fullPath.slice(matchIdx + q.length);
                    return (
                      <div
                        key={`${cat.brandId}-${cat.url}`}
                        className={`search-dropdown-item ${idx === selectedDropdownIdx ? 'highlighted' : ''}`}
                        onMouseDown={() => loadCategoryProducts(cat)}
                      >
                        <span className="dropdown-cat-name">
                          {before}<strong>{match}</strong>{after}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
            <select
              className="product-sort-select"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
            >
              <option value="">Sort by...</option>
              <option value="name-asc">Name A → Z</option>
              <option value="name-desc">Name Z → A</option>
              <option value="price-asc">Price Low → High</option>
              <option value="price-desc">Price High → Low</option>
            </select>
          </div>

        {(searchLoading || loadingProducts) ? (
          <div className="gallery-loading">Loading products...</div>
        ) : displayProducts.length > 0 ? (
          <div className="product-grid">
            {displayProducts.map((product, idx) => {
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

      {/* Product Detail Panel with drag handle */}
      {selectedProduct && (
        <div className="detail-panel-wrapper" style={{ width: detailPanelWidth, minWidth: 300 }}>
          <div className="detail-resize-handle" onMouseDown={handleResizeMouseDown} />
          <ProductDetailPanel
            product={selectedProduct}
            onClose={() => setSelectedProduct(null)}
          />
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
