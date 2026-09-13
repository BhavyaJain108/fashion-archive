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
