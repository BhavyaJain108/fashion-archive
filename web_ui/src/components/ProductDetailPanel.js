import React, { useState, useEffect } from 'react';
import './ProductDetailPanel.css';

// ---------------------------------------------------------------------------
// E0005-aware product detail panel.
//
// Reads canonical E0005 field names (product_title, product_code, brand,
// size_info, size_availability, size_stock_counts, color_info, material_info,
// specifications, category1..5, full_price, promotion_type, in_stock,
// delivery, additional_content, itemurl, main_image_url, all_images).
//
// Falls back to the legacy aliases (name, sku, url, images, variants) when
// a record on disk is still in the pre-e0005 shape so old data renders.
// ---------------------------------------------------------------------------

function ProductDetailPanel({ product, onClose }) {
  const [currentImageIndex, setCurrentImageIndex] = useState(0);

  useEffect(() => { setCurrentImageIndex(0); }, [product]);

  if (!product) return null;

  // --- field resolution: E0005 → legacy alias fallback ----------------------
  const title       = product.product_title || product.name || product.product_name || 'Unknown Product';
  const brand       = (product.brand || product.brand_id || '').toString();
  const brandDisplay = brand ? brand.replace(/_/g, ' ').toUpperCase() : '';
  const url         = product.itemurl || product.url || product.product_url || '';
  const sku         = product.product_code || product.sku || '';
  const description = product.description || '';

  const price       = product.price ?? null;
  const fullPrice   = product.full_price ?? null;
  const promo       = product.promotion_type || null;
  const inStock     = product.in_stock;
  const color       = product.color_info || '';
  const material    = product.material_info || '';
  const specsRaw    = product.specifications || '';
  const delivery    = product.delivery || '';
  const additional  = product.additional_content || '';
  const tags        = product.additional_tags || '';

  // images — prefer E0005 all_images, then main_image_url, then legacy images[]
  const rawImages = Array.isArray(product.all_images)
    ? product.all_images
    : (typeof product.all_images === 'string' && product.all_images.startsWith('[')
        ? safeJSON(product.all_images, [])
        : (product.images || []));
  const images = rawImages
    .map(img => typeof img === 'string' ? img : img && img.src)
    .filter(Boolean);
  if (product.main_image_url && !images.includes(product.main_image_url)) {
    images.unshift(product.main_image_url);
  }
  const currentImage = images[currentImageIndex] || null;

  // categories — E0005's category1..5 as breadcrumb
  const breadcrumb = [1,2,3,4,5]
    .map(i => product[`category${i}`])
    .filter(Boolean);
  if (breadcrumb.length === 0 && product.category) {
    // legacy "category" field is "A / B / C" joined
    breadcrumb.push(...String(product.category).split(' / ').filter(Boolean));
  }

  // Sizes: prefer E0005 size_info + size_availability + size_stock_counts.
  // Fallback: legacy variants[] with {size, available, stock_count}.
  const sizeEntries = buildSizeEntries(product);

  // Material composition: parse "Fabric: 100% Wool, Details: 63% Wool, 37% Viscose"
  const compositions = parseMaterial(material);

  // Specifications: split on "; "
  const specs = specsRaw
    ? specsRaw.split(/;\s*/).map(s => s.trim()).filter(Boolean)
    : [];

  // Tags: split on comma
  const tagList = tags ? tags.split(/,\s*/).map(t => t.trim()).filter(Boolean) : [];

  // -- render ----------------------------------------------------------------
  return (
    <div className="product-detail-panel">
      <div className="detail-panel-header">
        <button className="detail-panel-close" onClick={onClose}>&times;</button>
      </div>

      {images.length > 0 && (
        <div className="detail-carousel">
          <div className="detail-carousel-main">
            {images.length > 1 && (
              <button className="carousel-arrow carousel-arrow-left"
                      onClick={() => setCurrentImageIndex(i => (i > 0 ? i - 1 : images.length - 1))}>&lsaquo;</button>
            )}
            <img src={currentImage} alt={title} className="detail-carousel-image" />
            {images.length > 1 && (
              <button className="carousel-arrow carousel-arrow-right"
                      onClick={() => setCurrentImageIndex(i => (i < images.length - 1 ? i + 1 : 0))}>&rsaquo;</button>
            )}
          </div>
          {images.length > 1 && (
            <div className="detail-carousel-dots">
              {images.map((_, idx) => (
                <span key={idx}
                      className={`carousel-dot ${idx === currentImageIndex ? 'active' : ''}`}
                      onClick={() => setCurrentImageIndex(idx)} />
              ))}
            </div>
          )}
          {images.length > 1 && (
            <div className="detail-carousel-thumbs">
              {images.map((img, idx) => (
                <img key={idx} src={img} alt={`${title} ${idx+1}`}
                     className={`carousel-thumb ${idx === currentImageIndex ? 'active' : ''}`}
                     onClick={() => setCurrentImageIndex(idx)} />
              ))}
            </div>
          )}
        </div>
      )}

      <div className="detail-info">
        {/* Brand + title */}
        <div className="detail-brand">{brandDisplay}</div>
        <div className="detail-name">{title}</div>

        {/* Category breadcrumb */}
        {breadcrumb.length > 0 && (
          <div className="detail-breadcrumb">
            {breadcrumb.map((c, i) => (
              <span key={i} className="detail-breadcrumb-crumb">
                {String(c).replace(/-/g, ' ')}
                {i < breadcrumb.length - 1 && <span className="detail-breadcrumb-sep">›</span>}
              </span>
            ))}
          </div>
        )}

        {/* Price + sale + stock badge */}
        <div className="detail-price-row">
          {price !== null && (
            <div className="detail-price">
              {fullPrice && fullPrice !== price && (
                <span className="detail-price-strike">{formatPrice(fullPrice)}</span>
              )}
              {formatPrice(price)}
            </div>
          )}
          {promo && <span className="detail-tag detail-tag-promo">{promo}</span>}
          {inStock === 0 && <span className="detail-tag detail-tag-bad">Sold out</span>}
          {inStock === 1 && <span className="detail-tag detail-tag-good">In stock</span>}
        </div>

        {/* Color */}
        {color && (
          <div className="detail-block">
            <div className="detail-section-head">Color</div>
            <div>{color}</div>
          </div>
        )}

        {/* Size grid */}
        {sizeEntries.length > 0 && (
          <div className="detail-block">
            <div className="detail-section-head">Size · {sizeEntries.length} {sizeEntries.length === 1 ? 'size' : 'sizes'}</div>
            <div className="detail-size-grid">
              {sizeEntries.map((s, i) => (
                <div key={i}
                     className={
                       's-cell' +
                       (s.available === false ? ' gone' : '') +
                       (s.lowStock ? ' low' : '')
                     }>
                  <div className="s-label">{s.label}</div>
                  <div className="s-meta">
                    {s.available === false ? 'Sold out'
                      : s.stockCount === 1 ? '1 left'
                      : s.stockCount && s.stockCount <= 3 ? `${s.stockCount} left`
                      : 'In stock'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Description */}
        {description && (
          <div className="detail-block">
            <div className="detail-section-head">Description</div>
            <div className="detail-description">{description}</div>
          </div>
        )}

        {/* Material composition (parsed table) */}
        {compositions.length > 0 && (
          <div className="detail-block">
            <div className="detail-section-head">Material composition</div>
            <div className="detail-composition">
              {compositions.map((c, i) => (
                <div key={i} className="detail-composition-row">
                  <span className="detail-composition-label">{c.label}</span>
                  <span className="detail-composition-value">{c.value}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Specifications bullet list */}
        {specs.length > 0 && (
          <div className="detail-block">
            <div className="detail-section-head">Specifications</div>
            <ul className="detail-specs-list">
              {specs.map((s, i) => <li key={i}>{s}</li>)}
            </ul>
          </div>
        )}

        {/* Delivery */}
        {delivery && (
          <div className="detail-block">
            <div className="detail-section-head">Delivery</div>
            <div>{delivery}</div>
          </div>
        )}

        {/* Additional content */}
        {additional && (
          <div className="detail-block">
            <div className="detail-section-head">More info</div>
            <div className="detail-description">{additional}</div>
          </div>
        )}

        {/* Tags */}
        {tagList.length > 0 && (
          <div className="detail-block">
            <div className="detail-tags">
              {tagList.map((t, i) => <span key={i} className="detail-tag detail-tag-neutral">{t}</span>)}
            </div>
          </div>
        )}

        {/* SKU footer */}
        {sku && <div className="detail-sku">SKU · {sku}</div>}

        {url && (
          <button className="detail-view-site" onClick={() => window.open(url, '_blank')}>
            View on site &rarr;
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPrice(p) {
  if (p === null || p === undefined) return '';
  const n = typeof p === 'string' ? parseFloat(p.replace(/[^\d.]/g, '')) : Number(p);
  if (!isFinite(n)) return String(p);
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function safeJSON(s, fallback) {
  try { return JSON.parse(s); } catch { return fallback; }
}

/** Build size grid entries from E0005 fields, falling back to legacy variants. */
function buildSizeEntries(product) {
  const sizes = (product.size_info || '').split(/,\s*/).map(s => s.trim()).filter(Boolean);
  const avails = (product.size_availability || '').split(/,\s*/).map(s => s.trim()).filter(Boolean);
  const counts = (product.size_stock_counts || '').split(/,\s*/).map(s => s.trim()).filter(Boolean);

  if (sizes.length > 0) {
    return sizes.map((label, i) => {
      const avail = avails[i];
      const cnt = parseInt(counts[i], 10);
      const stockCount = isFinite(cnt) ? cnt : undefined;
      const available = avail
        ? !['out_of_stock', 'false', '0', 'no'].includes(avail.toLowerCase())
        : (stockCount === undefined ? undefined : stockCount > 0);
      const lowStock = available && stockCount !== undefined && stockCount > 0 && stockCount <= 2;
      return { label, available, stockCount, lowStock };
    });
  }
  // Legacy variants[] fallback
  const variants = product.variants || [];
  return variants
    .filter(v => v.size)
    .map(v => ({
      label: v.size,
      available: v.available !== false,
      stockCount: v.stock_count,
      lowStock: v.available !== false && typeof v.stock_count === 'number' && v.stock_count <= 2,
    }));
}

/** Parse "Fabric: 100% Wool, Details: 63% Wool, 37% Viscose, Lining: 100% Cupro"
 *  into [{label:"Fabric", value:"100% Wool"}, ...] preserving comma-separated
 *  composites under their original label. */
function parseMaterial(s) {
  if (!s || typeof s !== 'string') return [];
  // Split into chunks by ", " but only at label-bearing positions ("X: ").
  const parts = [];
  const tokens = s.split(',').map(t => t.trim()).filter(Boolean);
  let current = null;
  for (const tok of tokens) {
    if (tok.includes(':')) {
      if (current) parts.push(current);
      const [label, ...rest] = tok.split(':');
      current = { label: label.trim(), value: rest.join(':').trim() };
    } else if (current) {
      current.value += ', ' + tok;
    } else {
      parts.push({ label: 'Composition', value: tok });
    }
  }
  if (current) parts.push(current);
  return parts;
}

export default ProductDetailPanel;
