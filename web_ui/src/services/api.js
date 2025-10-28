// Fashion Archive API Service
// Bridges React UI to Python backend maintaining exact same functionality

class FashionArchiveAPI {
  static BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8081';

  // Helper to call Python backend
  static async callPython(endpoint, data = {}) {
    try {
      const response = await fetch(`${this.BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
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
    const response = await this.callPython('/api/download-images', { collection });
    return {
      imagePaths: response.imagePaths || [],
      designerName: response.designerName || collection.designer,
      error: response.error
    };
  }

  // Download video for a collection (matches tkinter video download)
  static async downloadVideo(collection) {
    try {
      const response = await this.callPython('/api/download-video', { collection });
      return response.videoPath || null;
    } catch (error) {
      console.error('Video download error:', error);
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

  // Stream collections as they load (matches tkinter stream_collections_update)
  static async streamCollections(seasonUrl, onUpdate) {
    try {
      const response = await fetch(`${this.BASE_URL}/api/collections-stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ seasonUrl }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              onUpdate(data);
              if (data.complete) return data.collections || [];
            } catch (e) {
              console.error('Error parsing stream data:', e);
            }
          }
        }
      }
    } catch (error) {
      console.error('Stream error:', error);
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
      const response = await fetch(`${this.BASE_URL}/api/favourites`, {
        method: 'GET'
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
      const response = await fetch(`${this.BASE_URL}/api/favourites`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
        },
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
    const response = await this.callPython('/api/favourites/check', {
      season_url: seasonUrl,
      collection_url: collectionUrl,
      look_number: lookNumber
    });
    return response.is_favourite || false;
  }

  static async getFavouriteStats() {
    try {
      const response = await fetch(`${this.BASE_URL}/api/favourites/stats`, {
        method: 'GET'
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
      const response = await fetch(`${this.BASE_URL}/api/favourites/cleanup`, {
        method: 'POST'
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