import ApiClient from './client';

// ---------------------------------------------------------------------------
// ArchiveAPI — the My Brands page.
//
// Everything here is read-only. The roster lives in backend/archive/brands.yml and
// the products are whatever the scraper last wrote into the catalogue; the page shows
// that and changes none of it. Scraping runs beside the app, not inside it, so there
// is no add-brand, no follow and no start-scrape call to make.
// ---------------------------------------------------------------------------

class ArchiveAPI {
  static get BASE_URL() {
    return ApiClient.BASE_URL;
  }

  static async get(path) {
    const response = await fetch(`${this.BASE_URL}/api/archive${path}`, {
      credentials: 'include',
    });
    ApiClient.checkAuth(response);
    if (!response.ok) {
      throw new Error(`Archive API ${path} failed: ${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  /** The brands the archive follows and shows, each with what it currently holds. */
  static async getBrands() {
    const data = await this.get('/brands');
    return data.brands || [];
  }

  /** The brand's own taxonomy, built from the categories its products actually carry. */
  static async getHierarchy(brandId) {
    const data = await this.get(`/brands/${encodeURIComponent(brandId)}/categories/hierarchy`);
    return data.hierarchy || [];
  }

  /** Products per category path, including every ancestor, so a collapsed parent totals. */
  static async getCounts(brandId) {
    const data = await this.get(`/products/counts?brand_id=${encodeURIComponent(brandId)}`);
    return data.counts || {};
  }

  static async getProducts(brandId, category = '*', limit = 1000) {
    const data = await this.get(
      `/products?brand_id=${encodeURIComponent(brandId)}` +
      `&category=${encodeURIComponent(category)}&limit=${limit}`
    );
    return data.products || [];
  }

  static async searchProducts(query, limit = 200) {
    const data = await this.get(`/products/search?q=${encodeURIComponent(query)}&limit=${limit}`);
    return data.products || [];
  }

  /**
   * The shop front: every brand in one grid. `params` are the page's own state
   * (group, bucket, brand, sale, colour, q, sort, offset, limit). A 503 with
   * code WARMING means the server is still building its index; call again.
   */
  static async storefront(params = {}) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== '' && v !== null && v !== undefined && v !== false) qs.set(k, String(v));
    const response = await fetch(`${this.BASE_URL}/api/archive/storefront?${qs}`, { credentials: 'include' });
    ApiClient.checkAuth(response);
    if (response.status === 503) return { warming: true };
    if (!response.ok) throw new Error(`Storefront failed: ${response.status}`);
    return response.json();
  }

  /** One product by the handle in its URL, with eight more from the same brand. */
  static async product(brandId, handle) {
    const response = await fetch(
      `${this.BASE_URL}/api/archive/product?brand_id=${encodeURIComponent(brandId)}&handle=${encodeURIComponent(handle)}`,
      { credentials: 'include' }
    );
    ApiClient.checkAuth(response);
    if (response.status === 503) return { warming: true };
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`Product failed: ${response.status}`);
    return response.json();
  }

  /** Whether the catalogue is where the app thinks it is. */
  static async health() {
    try {
      return await this.get('/health');
    } catch (error) {
      return { ok: false, error: error.message };
    }
  }
}

export default ArchiveAPI;
