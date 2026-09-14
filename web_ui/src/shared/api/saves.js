import ApiClient from './client';

// Recents and favourites: what this user has looked at, and what they kept.
export class SavesEndpoints {
  // Shows this user has opened, newest first. Distinct from favourites: a
  // favourite is a deliberate keep, this is just where you have been.
  static async getRecents() {
    try {
      const response = await fetch(`${ApiClient.BASE_URL}/api/recents`, {
        credentials: 'include',
      });
      if (!response.ok) {
        ApiClient.checkAuth(response);
        return [];
      }
      const data = await response.json();
      return data.recents || [];
    } catch (error) {
      console.error('Get recents API Error:', error);
      return [];
    }
  }



  // Favourites API methods
  static async getFavourites() {
    console.log('API: Fetching favourites from', `${ApiClient.BASE_URL}/api/favourites`);
    try {
      const headers = {};

      const response = await fetch(`${ApiClient.BASE_URL}/api/favourites`, {
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
    const response = await ApiClient.callPython('/api/favourites', {
      season: seasonData,
      collection: collectionData,
      look: lookData,
      image_path: imagePath,
      notes: notes
    });
    return response;
  }

  // DELETE is the one verb ApiClient has no helper for — it carries a body,
  // which fetch allows and most helpers do not model. One place builds it so
  // the look, show and view deletes cannot drift apart in their headers or
  // their error handling.
  static async deleteFavourite(payload) {
    try {
      const headers = {
        'Content-Type': 'application/json',
      };

      const response = await fetch(`${ApiClient.BASE_URL}/api/favourites`, {
        credentials: 'include',
        method: 'DELETE',
        headers: headers,
        body: JSON.stringify(payload),
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

  // Positional, and staying that way: two of the three arguments are URLs, so
  // a renumbering is invisible at the call site and wrong at the server. The
  // kind is left off rather than sent as 'look' — absent means look, which is
  // the request this has always sent.
  static async removeFavourite(seasonUrl, collectionUrl, lookNumber) {
    return SavesEndpoints.deleteFavourite({
      season_url: seasonUrl,
      collection_url: collectionUrl,
      look_number: lookNumber
    });
  }

  // ------------------------------------------------------------- a show ---
  // A whole run rather than one photograph: same season and collection, no
  // number. The server keys it on season + collection alone, so saving the
  // show does not touch a saved look of it and unsaving it does not either.

  static async addShowFavourite(seasonData, collectionData, imagePath, notes = '') {
    return ApiClient.callPython('/api/favourites', {
      kind: 'show',
      season: seasonData,
      collection: collectionData,
      image_path: imagePath,
      notes: notes
    });
  }

  static async removeShowFavourite(seasonUrl, collectionUrl) {
    return SavesEndpoints.deleteFavourite({
      kind: 'show',
      season_url: seasonUrl,
      collection_url: collectionUrl
    });
  }

  static async checkShowFavourite(seasonUrl, collectionUrl) {
    const data = await ApiClient.callPython('/api/favourites/check', {
      kind: 'show',
      season_url: seasonUrl,
      collection_url: collectionUrl
    });
    return Boolean(data.is_favourite);
  }

  // ------------------------------------------------------------- a view ---
  // A saved view IS its filters — the server hashes them to decide whether it
  // has this view already, so the filter object is sent as itself and nothing
  // is bundled in beside it. The name is optional; leave it off and the server
  // derives one from the values.

  static async addViewFavourite(filters, name = '') {
    return ApiClient.callPython('/api/favourites', {
      kind: 'view',
      filters: filters || {},
      name: name
    });
  }

  static async removeViewFavourite(filters) {
    return SavesEndpoints.deleteFavourite({
      kind: 'view',
      filters: filters || {}
    });
  }

  static async checkViewFavourite(filters) {
    const data = await ApiClient.callPython('/api/favourites/check', {
      kind: 'view',
      filters: filters || {}
    });
    return Boolean(data.is_favourite);
  }


  static async getFavouriteStats() {
    try {
      const headers = {};

      const response = await fetch(`${ApiClient.BASE_URL}/api/favourites/stats`, {
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

export default SavesEndpoints;
