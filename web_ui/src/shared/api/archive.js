import ApiClient from './client';

// The high-fashion archive: browsing, searching and streaming firstVIEW's
// catalogue and designer index.
export class ArchiveEndpoints {
  // Load seasons (matches tkinter load_seasons method)
  static async getSeasons() {
    const response = await ApiClient.callPython('/api/seasons');
    return response.seasons || [];
  }


  // Search for a fashion show video (matches tkinter video download)
  // `gender` is part of the cache key server-side, so passing it keeps
  // Men and Women lookups from colliding — and from costing quota twice.
  static async downloadVideo(designerName, seasonName, gender) {
    try {
      const response = await ApiClient.callPython('/api/download-video', {
        designerName,
        seasonName,
        gender
      }, { acceptErrors: true });
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


  // Stream one window of the archive.
  //
  // The browsing call. `filters` needs nothing but a gender — firstVIEW
  // answers a gender-only query with every show it holds, newest first — so
  // the list opens on the whole archive rather than on an instruction to
  // pick a year. Year, season, category, shoot type and initial each just
  // narrow the same query.
  //
  // One call is a window, not the whole result: `startPage`/`pages` in,
  // `nextPage`/`hasMore` out, so the caller asks for more as the reader
  // scrolls instead of waiting on a 900-page crawl.
  static async streamCatalog(filters, { startPage = 0, pages = 5, onUpdate, signal } = {}) {
    const all = [];
    let cursor = { nextPage: startPage, hasMore: false, total: 0 };

    await ApiClient.consumeSSE('/api/catalog/stream',
      { ...filters, startPage, pages },
      (evt) => {
        if (evt.type === 'collections') {
          all.push(...evt.collections);
          if (onUpdate) onUpdate({ rows: [...all], complete: false });
        } else if (evt.type === 'relabel') {
          // Rows indistinguishable on every printed field get their look
          // counts appended once the window is already on screen.
          for (const row of all) {
            const label = evt.labels[row.collection_id];
            if (label) row.subtitle = label;
          }
          if (onUpdate) onUpdate({ rows: [...all], complete: false });
        } else if (evt.type === 'done') {
          cursor = { nextPage: evt.nextPage, hasMore: !!evt.hasMore, total: evt.total };
          if (onUpdate) onUpdate({ rows: [...all], complete: true });
        } else if (evt.type === 'error') {
          throw new Error(evt.error);
        }
      }, signal);

    return { rows: all, ...cursor };
  }

  // Is the archive held locally? When it is, browsing is a database query
  // rather than a crawl of firstVIEW; when it is not, the streaming crawl
  // below still works, just slowly. Checked once.
  static _indexReady = null;

  static async getIndexStatus() {
    if (this._indexReady !== null) return this._indexReady;
    try {
      const response = await fetch(`${ApiClient.BASE_URL}/api/index/status`, {
        credentials: 'include',
      });
      if (!response.ok) {
        ApiClient.checkAuth(response);
        this._indexReady = { shows: 0 };
        return this._indexReady;
      }
      this._indexReady = await response.json();
      return this._indexReady;
    } catch (error) {
      console.error('Index status failed:', error);
      this._indexReady = { shows: 0 };
      return this._indexReady;
    }
  }

  // The archive list, from the local index. One request, no streaming, and
  // no contact with firstVIEW at all — the rows are already ours.
  //
  // `text` is a free-text query, `designer` pins it to one label, and
  // `facets: true` asks for the counts behind every filter dropdown so none
  // of them can offer a combination with nothing in it.
  static async browseCatalog(filters, { text, limit = 200, offset = 0, facets = false } = {}) {
    return ApiClient.callPython('/api/browse', {
      ...filters, text, limit, offset, facets,
    });
  }

  // Free text over every show. The query firstVIEW has no equivalent for:
  // their search covers designer names only, so "chanel fw25" could not be
  // asked of them at all.
  static async searchShows(text, { limit = 60 } = {}) {
    return ApiClient.callPython('/api/search', { text, limit });
  }

  // Every designer firstVIEW lists, fetched once and kept.
  //
  // The whole index comes down in one request — 8,657 names, ~87 KB gzipped —
  // because matching has to happen locally. firstVIEW's own designer search is
  // a plain substring, so "commes" finds nothing; fuzzy matching needs the
  // names in hand. The response carries an ETag and a day's cache lifetime, so
  // a reload is a 304 rather than another 87 KB.
  static _designerIndex = null;

  static async getDesigners() {
    if (this._designerIndex) return this._designerIndex;
    try {
      const response = await fetch(`${ApiClient.BASE_URL}/api/designers`, {
        credentials: 'include',
        // Revalidate rather than trust what is stored. This payload gains
        // its entry counts when the show index is built, and an earlier
        // version of it was served with a day's max-age — so a browser that
        // saw that one would go on ranking search results by a copy with no
        // counts in it, for a day, whatever the server now says. Asking
        // explicitly is what unsticks those; the answer is a 304 with no
        // body whenever nothing has changed.
        cache: 'no-cache',
      });
      if (!response.ok) {
        ApiClient.checkAuth(response);
        // 503 means the index was never built. Worth telling apart from an
        // empty archive, so the caller gets null rather than [].
        return null;
      }
      const data = await response.json();
      this._designerIndex = data.designers || [];
      return this._designerIndex;
    } catch (error) {
      console.error('Designer index failed to load:', error);
      return null;
    }
  }

  // Every show by one designer, across all years and both genders.
  //
  // A different query from the catalog: collection_designer.php ignores year,
  // season and gender, so this is the only way to see a designer's whole
  // working life. Yohji Yamamoto is 175 shows over 1995-2027.
  static async streamDesignerCollections(designerId, { onUpdate, signal } = {}) {
    const all = [];
    await ApiClient.consumeSSE('/api/designer/stream', { designerId }, (evt) => {
      if (evt.type === 'collections') {
        all.push(...evt.collections);
        if (onUpdate) onUpdate({ rows: [...all], complete: false });
      } else if (evt.type === 'relabel') {
        for (const row of all) {
          const label = evt.labels[row.collection_id];
          if (label) row.subtitle = label;
        }
        if (onUpdate) onUpdate({ rows: [...all], complete: false });
      } else if (evt.type === 'done') {
        if (onUpdate) onUpdate({ rows: [...all], complete: true });
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
    await ApiClient.consumeSSE('/api/download-images/stream', { collectionUrl }, (evt) => {
      if (evt.type === 'meta') {
        if (onMeta) onMeta(evt);
      } else if (evt.type === 'image') {
        if (onImage) onImage(evt);
      } else if (evt.type === 'image_error') {
        // One look that would not download. The show is still worth showing,
        // so this is noted and skipped — throwing here ended the download of
        // every look behind the failed one.
        console.warn(`Look ${evt.index} failed:`, evt.error);
      } else if (evt.type === 'done') {
        result = evt;
        if (onDone) onDone(evt);
      } else if (evt.type === 'error') {
        throw new Error(evt.error);
      }
    }, signal);
    return result;
  }
}

export default ArchiveEndpoints;
