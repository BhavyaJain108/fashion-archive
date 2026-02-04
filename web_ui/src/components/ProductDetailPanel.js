import React, { useState, useEffect } from 'react';

function ProductDetailPanel({ product, onClose }) {
  const [currentImageIndex, setCurrentImageIndex] = useState(0);

  // Reset to first image when a new product is selected
  useEffect(() => {
    setCurrentImageIndex(0);
  }, [product]);

  if (!product) return null;

  const name = product.name || product.product_name || 'Unknown Product';
  const brand = product.brand
    ? product.brand.toUpperCase()
    : (product.brand_id ? product.brand_id.replace(/_/g, ' ').toUpperCase() : '');
  const url = product.url || product.product_url || '';
  const price = product.price;
  const currency = product.currency || '';
  const description = product.description || '';
  const sku = product.sku || '';
  const category = product.category || '';
  const variants = product.variants || [];

  // Get images
  const images = (product.images || []).map(img =>
    typeof img === 'string' ? img : img.src
  ).filter(Boolean);

  const currentImage = images[currentImageIndex] || null;

  const prevImage = () => {
    setCurrentImageIndex(prev => (prev > 0 ? prev - 1 : images.length - 1));
  };

  const nextImage = () => {
    setCurrentImageIndex(prev => (prev < images.length - 1 ? prev + 1 : 0));
  };

  return (
    <div className="product-detail-panel">
      <div className="detail-panel-header">
        <button className="detail-panel-close" onClick={onClose}>&times;</button>
      </div>

      {/* Image Carousel */}
      {images.length > 0 && (
        <div className="detail-carousel">
          <div className="detail-carousel-main">
            {images.length > 1 && (
              <button className="carousel-arrow carousel-arrow-left" onClick={prevImage}>&lsaquo;</button>
            )}
            <img
              src={currentImage}
              alt={name}
              className="detail-carousel-image"
            />
            {images.length > 1 && (
              <button className="carousel-arrow carousel-arrow-right" onClick={nextImage}>&rsaquo;</button>
            )}
          </div>
          {images.length > 1 && (
            <div className="detail-carousel-dots">
              {images.map((_, idx) => (
                <span
                  key={idx}
                  className={`carousel-dot ${idx === currentImageIndex ? 'active' : ''}`}
                  onClick={() => setCurrentImageIndex(idx)}
                />
              ))}
            </div>
          )}
          {images.length > 1 && (
            <div className="detail-carousel-thumbs">
              {images.map((img, idx) => (
                <img
                  key={idx}
                  src={img}
                  alt={`${name} ${idx + 1}`}
                  className={`carousel-thumb ${idx === currentImageIndex ? 'active' : ''}`}
                  onClick={() => setCurrentImageIndex(idx)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Product Info */}
      <div className="detail-info">
        <div className="detail-brand">{brand}</div>
        <div className="detail-name">{name}</div>
        {price && (
          <div className="detail-price">{currency} {price}</div>
        )}

        {description && (
          <div className="detail-description">{description}</div>
        )}

        {(sku || category) && (
          <div className="detail-meta">
            {sku && <div className="detail-meta-item"><span>SKU:</span> {sku}</div>}
            {category && <div className="detail-meta-item"><span>Category:</span> {category}</div>}
          </div>
        )}

        {/* Variants */}
        {variants.length > 0 && (
          <div className="detail-variants">
            <div className="detail-variants-title">Variants</div>
            <table className="detail-variants-table">
              <thead>
                <tr>
                  {variants[0].size && <th>Size</th>}
                  {variants[0].color && <th>Color</th>}
                  <th>Available</th>
                  {variants[0].price && <th>Price</th>}
                </tr>
              </thead>
              <tbody>
                {variants.map((v, idx) => (
                  <tr key={idx}>
                    {variants[0].size && <td>{v.size || '-'}</td>}
                    {variants[0].color && <td>{v.color || '-'}</td>}
                    <td>{v.available ? 'Yes' : 'No'}</td>
                    {variants[0].price && <td>{v.price || '-'}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {url && (
          <button
            className="detail-view-site"
            onClick={() => window.open(url, '_blank')}
          >
            View on site &rarr;
          </button>
        )}
      </div>
    </div>
  );
}

export default ProductDetailPanel;
