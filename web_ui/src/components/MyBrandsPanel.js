import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import Fuse from 'fuse.js';
import { ArchiveAPI } from '../services/api';
import ProductDetailPanel from './ProductDetailPanel';

// ---------------------------------------------------------------------------
// MyBrandsPanel — the archive, browsed.
//
// The brand list is backend/archive/brands.yml and nothing here can change it: a brand
// joins the archive by being written into that file, which is the one place the
// decision is recorded. Scraping runs beside the app rather than inside it, so this
// panel starts no scrapes and follows none — it reads the catalogue the scraper last
// wrote and shows what is in it, gaps included.
// ---------------------------------------------------------------------------

function MyBrandsPanel() {
  const [brands, setBrands] = useState([]);
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState(null);
  const [expandedBrands, setExpandedBrands] = useState({});
  const [expandedCategories, setExpandedCategories] = useState({});
  const [selectedLeaves, setSelectedLeaves] = useState(new Set());
  const [products, setProducts] = useState([]);
  const [loadingProducts, setLoadingProducts] = useState(false);
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

  // Grid image sizing
  const [imageDimensions, setImageDimensions] = useState({});
  const gridRef = useRef(null);
  const [gridColWidth, setGridColWidth] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [roster, status] = await Promise.all([
          ArchiveAPI.getBrands(),
          ArchiveAPI.health(),
        ]);
        if (cancelled) return;
        setHealth(status);
        setBrands(roster.map(b => ({ ...b, navigation: null })));
      } catch (error) {
        console.error('Could not load the archive roster:', error);
        if (!cancelled) setHealth({ ok: false, error: error.message });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // A brand's tree and counts are fetched the first time it is opened rather than on
  // mount: the tree is derived from the brand's products, so loading all of them up
  // front would read the whole catalogue to draw a sidebar.
  const loadBrandTree = useCallback(async (brandId) => {
    try {
      const [hierarchy, counts] = await Promise.all([
        ArchiveAPI.getHierarchy(brandId),
        ArchiveAPI.getCounts(brandId),
      ]);
      setBrands(prev => prev.map(b =>
        b.brand_id === brandId ? { ...b, navigation: hierarchy } : b
      ));
      setProductCounts(prev => {
        const next = { ...prev };
        for (const [path, n] of Object.entries(counts)) {
          next[`${brandId}::${path}`] = n;
        }
        return next;
      });
    } catch (error) {
      console.error(`Could not load categories for ${brandId}:`, error);
      setBrands(prev => prev.map(b =>
        b.brand_id === brandId ? { ...b, navigation: [] } : b
      ));
    }
  }, []);

  const toggleBrand = useCallback((brandId) => {
    setExpandedBrands(prev => {
      const opening = !prev[brandId];
      if (opening) {
        const brand = brands.find(b => b.brand_id === brandId);
        if (brand && brand.navigation === null) loadBrandTree(brandId);
      }
      return { ...prev, [brandId]: opening };
    });
  }, [brands, loadBrandTree]);

  const toggleCategory = (categoryKey) => {
    setExpandedCategories(prev => ({ ...prev, [categoryKey]: !prev[categoryKey] }));
  };

  // Load products for the selected categories.
  //
  // Cross-category dedup: a product that appears under two selected categories shows
  // once. Within a single category duplicates stay — they are genuinely two listings.
  // Sidebar counts always show the raw per-category total, dedup or not.
  const loadProductsForSelection = useCallback(async (selectedSet, newlySelectedKey = null) => {
    if (selectedSet.size === 0) {
      setProducts([]);
      return;
    }
    setLoadingProducts(true);
    try {
      // Newly selected category first, so it lands at the top of the grid.
      const orderedKeys = [];
      if (newlySelectedKey && selectedSet.has(newlySelectedKey)) orderedKeys.push(newlySelectedKey);
      for (const key of selectedSet) {
        if (key !== newlySelectedKey) orderedKeys.push(key);
      }

      const groups = await Promise.all(orderedKeys.map(async (leafKey) => {
        const sep = leafKey.indexOf('::');
        const brandId = leafKey.slice(0, sep);
        const category = leafKey.slice(sep + 2);
        try {
          return await ArchiveAPI.getProducts(brandId, category, 1000);
        } catch (error) {
          console.error(`Could not load ${category} for ${brandId}:`, error);
          return [];
        }
      }));
      setProducts(deduplicateProducts(groups));
    } finally {
      setLoadingProducts(false);
    }
  }, []);

  const toggleLeaf = useCallback(async (brandId, categoryPath, shiftKey = false) => {
    const leafKey = `${brandId}::${categoryPath}`;
    const next = shiftKey ? new Set([leafKey]) : new Set(selectedLeaves);
    if (!shiftKey) {
      if (next.has(leafKey)) next.delete(leafKey); else next.add(leafKey);
    }
    setSelectedLeaves(next);
    const newlyAdded = next.has(leafKey) && !selectedLeaves.has(leafKey) ? leafKey : null;
    await loadProductsForSelection(next, newlyAdded);
  }, [selectedLeaves, loadProductsForSelection]);

  // --- category tree ------------------------------------------------------

  const countFor = useCallback((brandId, category) => (
    productCounts[`${brandId}::${category.url}`] ?? null
  ), [productCounts]);

  const renderCategoryTree = (brand, categories, level = 0) => {
    if (!categories || categories.length === 0) return null;

    // "all products" first, then parents, then leaves. An empty category is not worth
    // a row — but only once counts have arrived, or a brand's tree would draw blank.
    const sorted = [...categories].sort((a, b) => {
      if (a.url === '*') return -1;
      if (b.url === '*') return 1;
      const aParent = a.children && a.children.length > 0;
      const bParent = b.children && b.children.length > 0;
      if (aParent && !bParent) return -1;
      if (!aParent && bParent) return 1;
      return 0;
    }).filter(cat => (productCounts[`${brand.brand_id}::${cat.url}`] ?? 1) > 0);

    return sorted.map((category) => {
      const hasChildren = category.children && category.children.length > 0;
      const leafKey = `${brand.brand_id}::${category.url}`;
      const isSelected = selectedLeaves.has(leafKey);
      const isExpanded = expandedCategories[leafKey];
      const count = countFor(brand.brand_id, category);

      return (
        <div key={leafKey} style={{ marginLeft: level > 0 ? '16px' : '0' }}>
          <div
            className={`nav-item ${hasChildren ? 'nav-parent' : 'nav-leaf'} ${isSelected ? 'nav-selected' : ''}`}
            onClick={(e) => {
              // A parent is both a row of its own and a container: clicking the caret
              // area opens it, clicking the name selects it. Shift selects it alone.
              if (hasChildren && !e.shiftKey && e.target.closest('.nav-icon')) {
                toggleCategory(leafKey);
              } else {
                toggleLeaf(brand.brand_id, category.url, e.shiftKey);
              }
            }}
          >
            {hasChildren ? (
              <span
                className="nav-icon"
                onClick={(e) => { e.stopPropagation(); toggleCategory(leafKey); }}
              >
                {isExpanded ? '▾' : '▸'}
              </span>
            ) : (
              <span className="nav-bullet">•</span>
            )}
            <span className={isSelected ? 'nav-text-bold' : 'nav-text'}>
              {(category.name || 'unknown').toLowerCase()}
            </span>
            {count !== null && <span className="nav-count">{count}</span>}
          </div>
          {hasChildren && isExpanded && renderCategoryTree(brand, category.children, level + 1)}
        </div>
      );
    });
  };

  // --- category search dropdown -------------------------------------------

  // Flatten every loaded category into a searchable path + build a trigram index.
  // Only opened brands contribute: their trees are the only ones fetched. Full-text
  // product search below goes to the server and covers every brand regardless.
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
    for (const brand of brands) collect(brand, brand.navigation, []);
    leaves.sort((a, b) => a.fullPathLower.localeCompare(b.fullPathLower));

    const idx = {};
    for (let i = 0; i < leaves.length; i++) {
      const s = leaves[i].fullPathLower;
      for (let j = 0; j <= s.length - 3; j++) {
        const tri = s.slice(j, j + 3);
        if (!idx[tri]) idx[tri] = new Set();
        idx[tri].add(i);
      }
      for (let j = 0; j <= s.length - 2; j++) {
        const key = `_bi_${s.slice(j, j + 2)}`;
        if (!idx[key]) idx[key] = new Set();
        idx[key].add(i);
      }
    }
    return { allCategories: leaves, trigramIndex: idx };
  }, [brands]);

  const matchingCategories = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return [];
    if (q.length === 1) return allCategories.filter(cat => cat.fullPathLower.includes(q));

    let candidates = null;
    if (q.length === 2) {
      candidates = trigramIndex[`_bi_${q}`];
    } else {
      for (let i = 0; i <= q.length - 3; i++) {
        const set = trigramIndex[q.slice(i, i + 3)];
        if (!set) return [];
        if (candidates === null) {
          candidates = new Set(set);
        } else {
          for (const idx of candidates) if (!set.has(idx)) candidates.delete(idx);
        }
        if (candidates.size === 0) return [];
      }
    }
    if (!candidates) return [];

    const results = [];
    for (const idx of candidates) {
      if (allCategories[idx].fullPathLower.includes(q)) results.push(allCategories[idx]);
    }
    return results.sort((a, b) => a.fullPathLower.localeCompare(b.fullPathLower));
  }, [searchQuery, allCategories, trigramIndex]);

  const loadCategoryProducts = useCallback(async (category) => {
    setSearchLoading(true);
    try {
      const groups = await Promise.all(category.leafKeys.map(async (leafKey) => {
        const sep = leafKey.indexOf('::');
        try {
          return await ArchiveAPI.getProducts(leafKey.slice(0, sep), leafKey.slice(sep + 2), 1000);
        } catch {
          return [];
        }
      }));
      setSearchResults(deduplicateProducts(groups));
    } finally {
      setSearchLoading(false);
    }
  }, []);

  // Server-side search across every brand, merged with products from any category whose
  // path matches, then re-ranked fuzzily over the merged set.
  const executeSearch = useCallback(async (query) => {
    const q = query.trim();
    if (!q) {
      setSearchResults(null);
      return;
    }
    setSearchLoading(true);
    try {
      const textSearch = ArchiveAPI.searchProducts(q, 200).catch(() => []);
      const catFetches = matchingCategories.flatMap(cat =>
        cat.leafKeys.map((leafKey) => {
          const sep = leafKey.indexOf('::');
          return ArchiveAPI
            .getProducts(leafKey.slice(0, sep), leafKey.slice(sep + 2), 500)
            .catch(() => []);
        })
      );
      const [textResults, ...catResults] = await Promise.all([textSearch, ...catFetches]);
      const merged = deduplicateProducts([textResults, ...catResults]);

      const fuse = new Fuse(merged, {
        keys: [
          'product_title', 'product_code', 'brand', 'brand_id',
          'description', 'specifications', 'material_info',
          'category1', 'category2', 'category3',
          'color_info', 'size_info', 'additional_tags',
        ],
        threshold: 0.5,
        ignoreLocation: true,
        minMatchCharLength: 2,
      });
      const ranked = fuse.search(q).map(r => r.item);
      setSearchResults(ranked.length > 0 ? ranked : merged);
    } finally {
      setSearchLoading(false);
    }
  }, [matchingCategories]);

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
    searchTimerRef.current = setTimeout(() => executeSearch(query), 300);
  }, [executeSearch]);

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

  // --- grid ---------------------------------------------------------------

  const parsePrice = useCallback((product) => {
    const raw = product.price ?? product.full_price ?? '';
    const num = parseFloat(String(raw).replace(/[^0-9.]/g, ''));
    return isNaN(num) ? 0 : num;
  }, []);

  const displayProducts = useMemo(() => {
    let result = searchResults !== null ? searchResults : products;
    if (sortBy) {
      result = [...result].sort((a, b) => {
        const nameA = (a.product_title || '').toLowerCase();
        const nameB = (b.product_title || '').toLowerCase();
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

  useEffect(() => { setImageDimensions({}); }, [displayProducts]);

  useEffect(() => {
    const updateColWidth = () => {
      if (gridRef.current) {
        const firstCard = gridRef.current.querySelector('.product-card');
        if (firstCard) setGridColWidth(firstCard.offsetWidth);
      }
    };
    updateColWidth();
    if (!gridRef.current) return;
    const observer = new ResizeObserver(updateColWidth);
    observer.observe(gridRef.current);
    return () => observer.disconnect();
  }, [displayProducts]);

  const GRID_COLS = 4;
  const rowImageHeights = useMemo(() => {
    if (!gridColWidth) return {};
    const heights = {};
    displayProducts.forEach((_, idx) => {
      const dims = imageDimensions[idx];
      if (dims && dims.naturalWidth > 0) {
        const row = Math.floor(idx / GRID_COLS);
        const displayHeight = Math.ceil((dims.naturalHeight / dims.naturalWidth) * gridColWidth);
        heights[row] = Math.max(heights[row] || 0, displayHeight);
      }
    });
    return heights;
  }, [imageDimensions, gridColWidth, displayProducts]);

  const handleImageLoad = useCallback((idx, e) => {
    const { naturalWidth, naturalHeight } = e.target;
    setImageDimensions(prev => ({ ...prev, [idx]: { naturalWidth, naturalHeight } }));
  }, []);

  const handleResizeMouseDown = useCallback((e) => {
    e.preventDefault();
    isResizing.current = true;
    const startX = e.clientX;
    const startWidth = detailPanelWidth;

    const onMouseMove = (ev) => {
      if (!isResizing.current) return;
      const delta = startX - ev.clientX; // dragging left = wider
      setDetailPanelWidth(Math.min(window.innerWidth * 0.5, Math.max(300, startWidth + delta)));
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
        <div className="loading-state">Loading the archive...</div>
      </div>
    );
  }

  return (
    <div className="my-brands-container">
      {/* Left Sidebar — the roster */}
      <div className="brand-sidebar">
        <div className="brand-sidebar-content">
          {health && !health.ok && (
            <div className="archive-warning">
              The archive catalogue could not be read{health.error ? `: ${health.error}` : '.'}
            </div>
          )}
          {brands.map(brand => {
            const isExpanded = expandedBrands[brand.brand_id];
            const empty = brand.products === 0;

            return (
              <div key={brand.brand_id} className="brand-section">
                <div
                  className={`brand-name ${empty ? 'brand-empty' : ''}`}
                  onClick={() => toggleBrand(brand.brand_id)}
                  title={
                    `${brand.products} products` +
                    (brand.last_run ? ` · last read ${brand.last_run.slice(0, 10)}` : ' · never read') +
                    (brand.notes ? ` · ${brand.notes}` : '')
                  }
                >
                  <span className="brand-name-text">
                    {(brand.name || brand.brand_id).toUpperCase()}
                  </span>
                  <span className="brand-product-count">{brand.products}</span>
                </div>

                {isExpanded && (
                  <div className="brand-categories">
                    {brand.navigation === null
                      ? <div className="nav-item nav-loading">loading...</div>
                      : brand.navigation.length === 0
                        ? <div className="nav-item nav-empty">nothing scraped yet</div>
                        : renderCategoryTree(brand, brand.navigation)}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="brand-sidebar-footer">
          {brands.length} brands · {brands.reduce((n, b) => n + (b.products || 0), 0)} products
          <div className="brand-sidebar-hint">from brands.yml</div>
        </div>
      </div>

      {/* Right Panel — Product Gallery */}
      <div className="product-gallery">
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
            />
            {showDropdown && matchingCategories.length > 0 && (
              <div className="search-dropdown">
                {matchingCategories.map((cat, idx) => {
                  const q = searchQuery.trim().toLowerCase();
                  const matchIdx = cat.fullPath.toLowerCase().indexOf(q);
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
          <div className="product-grid" ref={gridRef}>
            {displayProducts.map((product, idx) => (
              <ProductCard
                key={`${product.itemurl || ''}-${idx}`}
                product={product}
                idx={idx}
                selected={selectedProduct?.itemurl === product.itemurl}
                rowHeight={rowImageHeights[Math.floor(idx / GRID_COLS)]}
                onSelect={() => setSelectedProduct(product)}
                onImageLoad={handleImageLoad}
              />
            ))}
          </div>
        ) : (
          <div className="gallery-empty">
            {selectedLeaves.size === 0 && searchResults === null
              ? 'Pick a brand on the left.'
              : 'Nothing here.'}
          </div>
        )}
      </div>

      {selectedProduct && (
        <div className="detail-panel-wrapper" style={{ width: detailPanelWidth, minWidth: 300 }}>
          <div className="detail-resize-handle" onMouseDown={handleResizeMouseDown} />
          <ProductDetailPanel
            product={selectedProduct}
            onClose={() => setSelectedProduct(null)}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Product card
// ---------------------------------------------------------------------------

function ProductCard({ product, idx, selected, rowHeight, onSelect, onImageLoad }) {
  const brandRaw = product.brand_name || product.brand || product.brand_id || '';
  const brandName = brandRaw ? String(brandRaw).replace(/_/g, ' ').toUpperCase() : '';
  const productName = product.product_title || 'Unknown Product';

  const imageUrl = firstImage(product);
  const price = product.price ?? null;
  const fullPrice = product.full_price ?? null;
  const onSale = fullPrice && price && Number(fullPrice) > Number(price);
  const priceDisplay = price !== null ? formatTilePrice(price, product.currency) : '';

  const sizeBadges = buildTileSizes(product);
  const allSoldOut = sizeBadges.length > 0 && sizeBadges.every(s => s.gone);
  const stock = product.in_stock;

  const cardClass = 'product-card'
    + (selected ? ' selected' : '')
    + (!imageUrl ? ' product-card-no-image' : '');

  // The shop's CDN is the live copy and can stop resolving; the archive kept bytes for
  // some products, so a dead image falls back to ours before it falls back to a ⊘.
  const handleError = (e) => {
    const img = e.currentTarget;
    const fallbacks = (product.archived_images || []).map(p => `${ArchiveAPI.BASE_URL}${p}`);
    const next = fallbacks.find(u => u !== img.src);
    if (next) {
      img.src = next;
      return;
    }
    const card = img.closest('.product-card');
    if (card) card.classList.add('product-card-no-image');
    img.style.display = 'none';
    const placeholder = img.parentElement.querySelector('.no-image-placeholder');
    if (placeholder) placeholder.style.display = 'flex';
  };

  return (
    <div className={cardClass} onClick={onSelect}>
      <div className="product-image" style={rowHeight ? { height: rowHeight } : undefined}>
        {imageUrl ? (
          <img
            src={imageUrl}
            alt={productName}
            loading="lazy"
            onLoad={(e) => onImageLoad(idx, e)}
            onError={handleError}
          />
        ) : null}
        <div className="no-image-placeholder" style={{ display: imageUrl ? 'none' : 'flex' }}>
          <div className="no-image-icon">⊘</div>
          <div className="no-image-text">No image</div>
        </div>
        {imageUrl && onSale && <div className="tile-badge tile-badge-sale">Sale</div>}
        {imageUrl && !onSale && allSoldOut && <div className="tile-badge tile-badge-bad">Sold out</div>}
        {imageUrl && !onSale && !allSoldOut && stock === true && <div className="tile-badge">In stock</div>}
        {!imageUrl && <div className="tile-badge tile-badge-flag">Missing image</div>}
      </div>
      <div className="product-info">
        <div className="product-brand">{brandName}</div>
        <div className="product-name">{productName}</div>
        {priceDisplay && (
          <div className="product-price">
            {onSale && (
              <span className="product-price-strike">
                {formatTilePrice(fullPrice, product.currency)}
              </span>
            )}
            {priceDisplay}
          </div>
        )}
        {sizeBadges.length > 0 && (
          <div className="tile-sizes">
            {sizeBadges.map((s, i) => (
              <span
                key={i}
                className={`tile-size${s.gone ? ' gone' : ''}${s.low ? ' low' : ''}`}
                title={s.label + (s.gone ? ' — sold out' : (s.count ? ` — ${s.count} left` : ''))}
              >
                {s.short}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers (E0005)
// ---------------------------------------------------------------------------

/** Products that appear under two selected categories show once; within one category
 *  duplicates stay, because there they are two real listings. */
function deduplicateProducts(productArrays) {
  const seenUrl = new Set();
  const brandNameSource = new Map();
  const results = [];
  for (let i = 0; i < productArrays.length; i++) {
    for (const p of productArrays[i] || []) {
      const url = p.itemurl || '';
      if (url && seenUrl.has(url)) continue;
      if (url) seenUrl.add(url);

      const brand = (p.brand || p.brand_id || '').toLowerCase();
      const name = (p.product_title || '').toLowerCase();
      if (brand && name) {
        const key = `${brand}::${name}`;
        if (brandNameSource.has(key) && brandNameSource.get(key) !== i) continue;
        brandNameSource.set(key, i);
      }
      results.push(p);
    }
  }
  return results;
}

/** main_image_url, else the first of all_images — which is stored JSON-encoded. */
function firstImage(product) {
  if (product.main_image_url) return product.main_image_url;
  let images = product.all_images;
  if (typeof images === 'string') {
    try { images = JSON.parse(images); } catch { images = []; }
  }
  if (!Array.isArray(images) || images.length === 0) return null;
  const first = images[0];
  return typeof first === 'string' ? first : (first && first.src) || null;
}

const CURRENCY_SIGN = { USD: '$', EUR: '€', GBP: '£', JPY: '¥', CNY: '¥', RUB: '₽' };

function formatTilePrice(p, currency) {
  if (p === null || p === undefined || p === '') return '';
  const n = typeof p === 'string' ? parseFloat(p.replace(/[^\d.]/g, '')) : Number(p);
  if (!isFinite(n)) return String(p);
  const sign = CURRENCY_SIGN[currency] || (currency ? `${currency} ` : '$');
  return sign + n.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

/** Compact per-size badges: [{short:"38", gone, low, count, label:"38 / US 2"}, ...]
 *  from the E0005 size_info / size_availability / size_stock_counts triple, which are
 *  parallel comma-separated lists aligned by position. Capped at 6 to keep tiles small. */
function buildTileSizes(product) {
  const sizes = (product.size_info || '').split(/,\s*/).map(s => s.trim()).filter(Boolean);
  const avails = (product.size_availability || '').split(/,\s*/).map(s => s.trim()).filter(Boolean);
  const counts = (product.size_stock_counts || '').split(/,\s*/).map(s => s.trim()).filter(Boolean);

  return sizes.map((label, i) => {
    const avail = (avails[i] || '').toLowerCase();
    const cnt = parseInt(counts[i], 10);
    const stockCount = isFinite(cnt) ? cnt : undefined;
    const gone = avail
      ? ['out_of_stock', 'false', '0', 'no'].includes(avail)
      : (stockCount === 0);
    const low = !gone && stockCount !== undefined && stockCount > 0 && stockCount <= 2;
    return { label, short: label.split('/')[0].trim(), gone, low, count: stockCount };
  }).slice(0, 6);
}

export default MyBrandsPanel;
