// Fashion Archive API Service
// Bridges the React UI to the Python backend.
//
// Every request sends `credentials: 'include'` so the browser attaches the
// session cookie. The cookie is HttpOnly, which means this file cannot read it
// and neither can anything else running on the page — that is the point. The
// previous version read a token out of localStorage and set an Authorization
// header by hand in eight separate places; any XSS on the page could have read
// that token straight out of storage.

class FashionArchiveAPI {
  static BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8081';

  // Called when the API reports the session is gone, so the app can show the
  // login screen instead of rendering empty data. Set once by App.js.
  static onUnauthorized = null;

  // Single place that notices a dead session. Handlers below call this rather
  // than each deciding for themselves what a 401 means.
  static checkAuth(response) {
    if (response.status === 401 && this.onUnauthorized) {
      this.onUnauthorized();
    }
    return response;
  }

  // ---------------------------------------------------------------- auth ---

  static async authRequest(path, body) {
    const response = await fetch(`${this.BASE_URL}/api/auth/${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, ...data };
  }

  // Who am I? A 200 here is what "remembered the user" looks like on boot.
  static async getMe() {
    const response = await fetch(`${this.BASE_URL}/api/auth/me`, {
      credentials: 'include',
    });
    if (!response.ok) return null;
    const data = await response.json();
    return data.user || null;
  }

  static login(email, password) {
    return this.authRequest('login', { email, password });
  }

  static register(email, password, displayName) {
    return this.authRequest('register', {
      email, password, display_name: displayName,
    });
  }

  static logout() {
    return this.authRequest('logout', {});
  }

  static resendVerification(email) {
    return this.authRequest('resend-verification', { email });
  }

  static requestPasswordReset(email) {
    return this.authRequest('request-reset', { email });
  }

  static resetPassword(token, password) {
    return this.authRequest('reset', { token, password });
  }

  // Helper to call Python backend
  static async callPython(endpoint, data = {}) {
    try {
      // The session cookie rides along via credentials: 'include'.
      const headers = { 'Content-Type': 'application/json' };

      const response = await fetch(`${this.BASE_URL}${endpoint}`, {
        credentials: 'include',
        method: 'POST',
        headers: headers,
        body: JSON.stringify(data),
      });

      if (!response.ok) {
        this.checkAuth(response);
        throw new Error(`API call failed: ${response.statusText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Python API Error:', error);
      throw error;
    }
  }

  // Load seasons (matches tkinter load_seasons method)
  static async getSeasons() {
    const response = await this.callPython('/api/seasons');
    return response.seasons || [];
  }

  // Download images for a collection (matches tkinter download_and_display_images)
  static async downloadImages(collection) {
    const response = await this.callPython('/api/download-images', {
      collectionUrl: collection.url,
      designerName: collection.designer
    });
    return {
      imagePaths: response.images?.map(img => img.path) || [],
      images: response.images || [],
      designerName: collection.designer,
      cacheDir: response.cache_dir,
      count: response.count,
      error: response.error
    };
  }

  // Search for a fashion show video (matches tkinter video download)
  // `gender` is part of the cache key server-side, so passing it keeps
  // Men and Women lookups from colliding — and from costing quota twice.
  static async downloadVideo(designerName, seasonName, gender) {
    try {
      const response = await this.callPython('/api/download-video', {
        designerName,
        seasonName,
        gender
      });
      if (response.success) {
        return {
          videoId: response.videoId,
          youtubeUrl: response.youtubeUrl,
          embedUrl: response.embedUrl,
          title: response.title,
          thumbnail: response.thumbnail
        };
      }
      // A failure here is informative: no video, quota gone for today, or
      // no key configured. The caller shows the reason rather than a
      // generic error.
      return { error: response.error || 'No runway video found',
               quotaExhausted: !!response.quotaExhausted,
               notConfigured: !!response.notConfigured };
    } catch (error) {
      console.error('Video search error:', error);
      return { error: 'Video lookup failed' };
    }
  }

  // Image locations are already URLs — from R2 in production, from the API's
  // local store in development. The backend used to return an absolute
  // filesystem path that this turned into /api/image?path=..., asking the
  // server to read that path off disk.
  static getImageUrl(imagePath) {
    if (!imagePath) return '';
    if (/^https?:\/\//i.test(imagePath)) return imagePath;
    // Legacy value from an older cached response.
    return `${this.BASE_URL}/api/images/${imagePath.replace(/^\/+/, '')}`;
  }

  // Clean up cache (matches tkinter cleanup_previous_downloads)
  static async cleanupDownloads() {
    const response = await this.callPython('/api/cleanup');
    return response.success;
  }

  // Consume a Server-Sent Events endpoint, invoking onEvent per frame.
  // Shared by the collection and image streams.
  static async consumeSSE(endpoint, body, onEvent, signal) {
    const response = await fetch(`${this.BASE_URL}${endpoint}`, {
      method: 'POST',
      credentials: 'include',          // session cookie, as everywhere else
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
    if (!response.ok) {
      this.checkAuth(response);
      throw new Error(`Stream failed: ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Frames are "data: {...}\n\n". Keep the trailing partial frame in
        // the buffer — a JSON payload can be split across reads.
        const frames = buffer.split('\n\n');
        buffer = frames.pop() || '';

        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith('data: ')) continue;
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch (e) {
            console.warn('Bad SSE frame:', e, line.slice(0, 120));
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  // Stream shows for a season. onUpdate({collections, complete}) fires per
  // results page, so rows render while the rest of the season is crawled.
  // `extra` carries optional filters the season URL doesn't encode —
  // category (Ready-to-Wear / Haute Couture / Swim) and shootType.
  static async streamCollections(seasonUrl, onUpdate, signal, extra = {}) {
    const all = [];
    await this.consumeSSE('/api/collections/stream', { seasonUrl, ...extra }, (evt) => {
      if (evt.type === 'collections') {
        all.push(...evt.collections);
        if (onUpdate) onUpdate({ collections: [...all], complete: false });
      } else if (evt.type === 'relabel') {
        // Rows that were indistinguishable get their look counts appended
        // once the crawl is done, so the list isn't held up waiting for them.
        for (const row of all) {
          const label = evt.labels[row.collection_id];
          if (label) row.designer = label;
        }
        if (onUpdate) onUpdate({ collections: [...all], complete: false });
      } else if (evt.type === 'done') {
        if (onUpdate) onUpdate({ collections: [...all], complete: true });
      } else if (evt.type === 'error') {
        throw new Error(evt.error);
      }
    }, signal);
    return all;
  }

  // Stream one show's looks. onMeta fires once with every look's metadata
  // (before any file lands); onImage fires per downloaded image.
  static async streamCollectionImages(collectionUrl, { onMeta, onImage, onDone, signal } = {}) {
    let result = null;
    await this.consumeSSE('/api/download-images/stream', { collectionUrl }, (evt) => {
      if (evt.type === 'meta') {
        if (onMeta) onMeta(evt);
      } else if (evt.type === 'image') {
        if (onImage) onImage(evt);
      } else if (evt.type === 'done') {
        result = evt;
        if (onDone) onDone(evt);
      } else if (evt.type === 'error') {
        throw new Error(evt.error);
      }
    }, signal);
    return result;
  }

  // Shows this user has opened, newest first. Distinct from favourites: a
  // favourite is a deliberate keep, this is just where you have been.
  static async getRecents() {
    try {
      const response = await fetch(`${this.BASE_URL}/api/recents`, {
        credentials: 'include',
      });
      if (!response.ok) {
        this.checkAuth(response);
        return [];
      }
      const data = await response.json();
      return data.recents || [];
    } catch (error) {
      console.error('Get recents API Error:', error);
      return [];
    }
  }

  // Video search test (matches tkinter open_video_test)
  static async testVideoSearch(query) {
    const response = await this.callPython('/api/video-test', { query });
    return response;
  }

  // Get application info (matches tkinter show_about)
  static async getAboutInfo() {
    try {
      const response = await fetch(`${this.BASE_URL}/api/about`, { credentials: 'include' });
      return await response.json();
    } catch (error) {
      console.error('About info error:', error);
      return null;
    }
  }

  // Favourites API methods
  static async getFavourites() {
    console.log('API: Fetching favourites from', `${this.BASE_URL}/api/favourites`);
    try {
      const headers = {};

      const response = await fetch(`${this.BASE_URL}/api/favourites`, {
        credentials: 'include',
        method: 'GET',
        headers: headers
      });

      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }

      const data = await response.json();
      console.log('API: Raw favourites response:', data);
      const favourites = data.favourites || [];
      console.log('API: Parsed favourites:', favourites);
      return favourites;
    } catch (error) {
      console.error('Get favourites API Error:', error);
      return [];
    }
  }

  static async addFavourite(seasonData, collectionData, lookData, imagePath, notes = '') {
    const response = await this.callPython('/api/favourites', {
      season: seasonData,
      collection: collectionData,
      look: lookData,
      image_path: imagePath,
      notes: notes
    });
    return response;
  }

  static async removeFavourite(seasonUrl, collectionUrl, lookNumber) {
    try {
      const headers = {
        'Content-Type': 'application/json',
      };

      const response = await fetch(`${this.BASE_URL}/api/favourites`, {
        credentials: 'include',
        method: 'DELETE',
        headers: headers,
        body: JSON.stringify({
          season_url: seasonUrl,
          collection_url: collectionUrl,
          look_number: lookNumber
        }),
      });

      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Remove favourite API Error:', error);
      throw error;
    }
  }

  static async checkFavourite(seasonUrl, collectionUrl, lookNumber) {
    try {
      const response = await this.callPython('/api/favourites/check', {
        season_url: seasonUrl,
        collection_url: collectionUrl,
        look_number: lookNumber
      });
      return response.is_favourite || false;
    } catch (error) {
      // If unauthorized (not logged in), just return false
      if (error.message && error.message.includes('UNAUTHORIZED')) {
        return false;
      }
      throw error;
    }
  }

  static async getFavouriteStats() {
    try {
      const headers = {};

      const response = await fetch(`${this.BASE_URL}/api/favourites/stats`, {
        credentials: 'include',
        method: 'GET',
        headers: headers
      });

      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }

      const data = await response.json();
      return data.stats || {};
    } catch (error) {
      console.error('Favourites stats error:', error);
      return {};
    }
  }

}

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
    return FashionArchiveAPI.BASE_URL;
  }

  static async get(path) {
    const response = await fetch(`${this.BASE_URL}/api/archive${path}`, {
      credentials: 'include',
    });
    FashionArchiveAPI.checkAuth(response);
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

export { FashionArchiveAPI, ArchiveAPI };