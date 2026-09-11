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

  // Load collections for a season (matches tkinter load_selected_season)
  static async getCollections(seasonUrl) {
    const response = await this.callPython('/api/collections', { seasonUrl });
    return response.collections || [];
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

  // Get video file (for playback)
  static getVideoUrl(videoPath) {
    return `${this.BASE_URL}/api/video?path=${encodeURIComponent(videoPath)}`;
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

  static async clearRecents() {
    try {
      const response = await fetch(`${this.BASE_URL}/api/recents`, {
        method: 'DELETE',
        credentials: 'include',
      });
      return response.ok;
    } catch (error) {
      console.error('Clear recents API Error:', error);
      return false;
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

  // My Brands API methods
  static async getBrands() {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands`, {
        credentials: 'include',
        method: 'GET'
      });
      
      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }
      
      const data = await response.json();
      return data.brands || [];
    } catch (error) {
      console.error('Get brands API Error:', error);
      return [];
    }
  }

  static async addBrand(brandData) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands`, {
        credentials: 'include',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(brandData),
      });
      
      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error('Add brand API Error:', error);
      return { success: false, message: error.message };
    }
  }

  static async getBrandDetails(brandId) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands/${brandId}`, {
        credentials: 'include',
        method: 'GET'
      });
      
      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error('Get brand details API Error:', error);
      return { error: error.message };
    }
  }

  static async discoverBrandCollections(brandId) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands/${brandId}/discover`, {
        credentials: 'include',
        method: 'POST'
      });
      
      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error('Discover brand collections API Error:', error);
      return { success: false, message: error.message };
    }
  }

  static async scrapeBrandProducts(brandId, collectionUrl = null) {
    try {
      const body = collectionUrl ? JSON.stringify({ collection_url: collectionUrl }) : undefined;
      const response = await fetch(`${this.BASE_URL}/api/brands/${brandId}/scrape`, {
        credentials: 'include',
        method: 'POST',
        headers: collectionUrl ? { 'Content-Type': 'application/json' } : {},
        body: body
      });
      
      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error('Scrape brand products API Error:', error);
      return { success: false, message: error.message };
    }
  }

  // Stream brand products scraping with real-time progress
  static async scrapeBrandProductsStream(brandId, onProgress, collectionUrl = null) {
    try {
      const body = collectionUrl ? JSON.stringify({ collection_url: collectionUrl }) : undefined;
      const response = await fetch(`${this.BASE_URL}/api/brands/${brandId}/scrape-stream`, {
        credentials: 'include',
        method: 'POST',
        headers: collectionUrl ? { 'Content-Type': 'application/json' } : {},
        body: body
      });

      if (!response.ok) {
        throw new Error(`Stream failed: ${response.statusText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let finalResult = null;

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value);
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));
                
                // Call progress callback
                if (onProgress) {
                  onProgress(data);
                }
                
                // Store final result
                if (data.status === 'completed') {
                  finalResult = data;
                }
                
              } catch (e) {
                console.warn('Error parsing stream data:', e, 'Line:', line);
              }
            }
          }
        }
      } finally {
        reader.releaseLock();
      }

      return finalResult || { success: false, message: 'Stream ended without final result' };

    } catch (error) {
      console.error('Stream brand products API Error:', error);
      return { success: false, message: error.message };
    }
  }

  // NEW: Clean category-first API methods for better UX
  static async getBrandCategories(brandId) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands/${brandId}/categories`, {
        credentials: 'include',
        method: 'GET'
      });
      
      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error('Get brand categories API Error:', error);
      return { categories: {}, error: error.message };
    }
  }

  static async getCategoryProducts(brandId, categoryName) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands/${brandId}/categories/${encodeURIComponent(categoryName)}/products`, {
        credentials: 'include',
        method: 'GET'
      });
      
      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error('Get category products API Error:', error);
      return { products: [], error: error.message };
    }
  }

  // LEGACY: Keep for backward compatibility
  static async getBrandProducts(brandId) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands/${brandId}/products`, {
        credentials: 'include',
        method: 'GET'
      });
      
      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error('Get brand products API Error:', error);
      return { products: [], error: error.message };
    }
  }

  static async addProductFavorite(productId, notes = '') {
    try {
      const response = await fetch(`${this.BASE_URL}/api/products/${productId}/favorite`, {
        credentials: 'include',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ notes }),
      });
      
      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error('Add product favorite API Error:', error);
      return { success: false, message: error.message };
    }
  }

  static async getBrandFavorites() {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brand-favorites`, {
        credentials: 'include',
        method: 'GET'
      });
      
      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }
      
      const data = await response.json();
      return data.favorites || [];
    } catch (error) {
      console.error('Get brand favorites API Error:', error);
      return [];
    }
  }

  static async getBrandStats() {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands/stats`, {
        credentials: 'include',
        method: 'GET'
      });
      
      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }
      
      const data = await response.json();
      return data.stats || {};
    } catch (error) {
      console.error('Get brand stats API Error:', error);
      return {};
    }
  }

  static async validateBrand(homepageUrl) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands/validate`, {
        credentials: 'include',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ homepage_url: homepageUrl }),
      });

      const data = await response.json();
      return data;
    } catch (error) {
      console.error('Validate brand API Error:', error);
      return { success: false, error: error.message };
    }
  }

  static async createBrandWithValidation(homepageUrl, brandName = null) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands`, {
        credentials: 'include',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          homepage_url: homepageUrl,
          name: brandName
        }),
      });

      const data = await response.json();
      return data;
    } catch (error) {
      console.error('Create brand API Error:', error);
      return { success: false, error: error.message };
    }
  }

  static async startBrandScraping(brandId, mode = 'full') {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands/${brandId}/scrape?mode=${mode}`, {
        credentials: 'include',
        method: 'POST'
      });

      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Start brand scraping API Error:', error);
      return { success: false, error: error.message };
    }
  }

  static async getBrandScrapeStatus(brandId) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands/${brandId}/scrape/status`, {
        credentials: 'include',
        method: 'GET'
      });

      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Get brand scrape status API Error:', error);
      return { error: error.message };
    }
  }

  static async followBrand(brandId, brandName, notes = '') {
    try {
      const headers = {
        'Content-Type': 'application/json',
      };

      const response = await fetch(`${this.BASE_URL}/api/brands/follow`, {
        credentials: 'include',
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          brand_id: brandId,
          brand_name: brandName,
          notes: notes
        }),
      });

      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Follow brand API Error:', error);
      return { success: false, error: error.message };
    }
  }

  static async unfollowBrand(brandId) {
    try {
      const headers = {
        'Content-Type': 'application/json',
      };

      const response = await fetch(`${this.BASE_URL}/api/brands/unfollow`, {
        credentials: 'include',
        method: 'POST',
        headers: headers,
        body: JSON.stringify({ brand_id: brandId }),
      });

      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Unfollow brand API Error:', error);
      return { success: false, error: error.message };
    }
  }

  static async getFollowedBrands() {
    try {
      const headers = {};

      const response = await fetch(`${this.BASE_URL}/api/brands/following`, {
        credentials: 'include',
        method: 'GET',
        headers: headers
      });

      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }

      const data = await response.json();
      return data.brands || [];
    } catch (error) {
      console.error('Get followed brands API Error:', error);
      return [];
    }
  }

  static async analyzeBrandUrl(url) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands/analyze`, {
        credentials: 'include',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ url }),
      });

      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Analyze brand URL API Error:', error);
      return { error: error.message };
    }
  }

  static async resolveBrandName(brandName) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands/resolve-name`, {
        credentials: 'include',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ brand_name: brandName }),
      });
      
      if (!response.ok) {
        throw new Error(`API call failed: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error('Resolve brand name API Error:', error);
      return { success: false, error: error.message };
    }
  }
}

export { FashionArchiveAPI };