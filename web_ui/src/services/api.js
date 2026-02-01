// Fashion Archive API Service
// Bridges React UI to Python backend maintaining exact same functionality

class FashionArchiveAPI {
  static BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8081';

  // Helper to call Python backend
  static async callPython(endpoint, data = {}) {
    try {
      // Get session token from localStorage
      const token = localStorage.getItem('fashionArchiveToken');

      // Build headers with optional Authorization
      const headers = {
        'Content-Type': 'application/json',
      };

      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(`${this.BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(data),
      });

      if (!response.ok) {
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
  static async downloadVideo(designerName, seasonName) {
    try {
      const response = await this.callPython('/api/download-video', {
        designerName,
        seasonName
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
      return null;
    } catch (error) {
      console.error('Video search error:', error);
      return null;
    }
  }

  // Get image file (for display)
  static getImageUrl(imagePath) {
    return `${this.BASE_URL}/api/image?path=${encodeURIComponent(imagePath)}`;
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

  // Get collections for a season (uses non-streaming endpoint)
  static async streamCollections(seasonUrl, onUpdate) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/collections`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ seasonUrl }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      // Call onUpdate with the final data
      if (onUpdate && data.collections) {
        onUpdate({
          collections: data.collections,
          complete: true
        });
      }

      return data.collections || [];
    } catch (error) {
      console.error('Error loading collections:', error);
      throw error;
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
      const response = await fetch(`${this.BASE_URL}/api/about`);
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
      const token = localStorage.getItem('fashionArchiveToken');
      const headers = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(`${this.BASE_URL}/api/favourites`, {
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
      const token = localStorage.getItem('fashionArchiveToken');
      const headers = {
        'Content-Type': 'application/json',
      };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(`${this.BASE_URL}/api/favourites`, {
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
      const token = localStorage.getItem('fashionArchiveToken');
      const headers = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(`${this.BASE_URL}/api/favourites/stats`, {
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

  static async cleanupFavourites() {
    try {
      const token = localStorage.getItem('fashionArchiveToken');
      const headers = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(`${this.BASE_URL}/api/favourites/cleanup`, {
        method: 'POST',
        headers: headers
      });
      const data = await response.json();
      return data;
    } catch (error) {
      console.error('Cleanup favourites error:', error);
      return { success: false, error: error.message };
    }
  }

  // My Brands API methods
  static async getBrands() {
    try {
      const response = await fetch(`${this.BASE_URL}/api/brands`, {
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
      const token = localStorage.getItem('fashionArchiveToken');
      const headers = {
        'Content-Type': 'application/json',
      };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(`${this.BASE_URL}/api/brands/follow`, {
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

  static async getFollowedBrands() {
    try {
      const token = localStorage.getItem('fashionArchiveToken');
      const headers = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(`${this.BASE_URL}/api/brands/following`, {
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