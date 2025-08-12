// Fashion Archive API Service
// Bridges React UI to Python backend maintaining exact same functionality

class FashionArchiveAPI {
  static BASE_URL = 'http://localhost:8081';

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

  // Clean up downloads (matches tkinter cleanup_previous_downloads)
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
}

export { FashionArchiveAPI };