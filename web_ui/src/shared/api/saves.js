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
  //
  // Rows come back with `collection.id` alongside `collection.url` — firstVIEW's
  // id for the show. Nothing is sent for it on the way in and nothing should be:
  // the server derives it from the collection_url in the same statement that
  // stores the url, so a client that supplied one could only ever supply one that
  // disagreed. Two spellings of one show is the bug the column exists to end.
  static async getFavourites() {
    console.log('API: Fetching favourites from', `${ApiClient.BASE_URL}/api/favourites`);
    try {
      const headers = {};

      const response = await fetch(`${ApiClient.BASE_URL}/api/favourites`, {
        credentials: 'include',
        method: 'GET',
        headers: headers
      });

      // A dead session is not an empty library. Without this a 401 was caught
      // below and answered with [], so the reader saw no saves, an all-dark
      // star field and no sign-in prompt — and `useSaves.error` never fired,
      // because the throw did not escape. `getRecents` has always reported it;
      // this is the same endpoint family and now gives the same answer.
      if (!response.ok) {
        ApiClient.checkAuth(response);
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

  // ---------------------------------------------------------- a page ---
  //
  // The same endpoint, asked for a slice rather than the lot. `getFavourites`
  // above is the unpaged reading and stays exactly as it was for the caller
  // that wants everything; this one returns the envelope beside the rows —
  // `{ favourites, total, hasMore, nextCursor }` — which is the shape
  // `browse_catalog` already answers for shows.
  //
  // Paging is by CURSOR, not by page number or offset, and the server's
  // `list_page` says why: the library unsaves rows out of the very list it is
  // paging through, and an offset slides by one for every row taken out above
  // it. A cursor names the last row actually delivered, so it cannot slide.
  //
  // `nextCursor` is opaque and is passed back untouched. Reading it, or
  // building one, is how the two ends stop agreeing about what it means.
  static async getFavouritesPage({ kind = null, limit = null, cursor = null } = {}) {
    const query = new URLSearchParams();
    if (kind) query.set('kind', kind);
    if (limit !== null && limit !== undefined) query.set('limit', String(limit));
    if (cursor) query.set('cursor', cursor);

    try {
      const response = await fetch(
        `${ApiClient.BASE_URL}/api/favourites?${query.toString()}`,
        { credentials: 'include', method: 'GET' },
      );

      // A dead session is not an empty library — same reasoning as
      // `getFavourites` above, and the same answer.
      if (!response.ok) {
        ApiClient.checkAuth(response);
        throw new Error(`API call failed: ${response.statusText}`);
      }

      const data = await response.json();
      return {
        favourites: data.favourites || [],
        total: data.total || 0,
        hasMore: Boolean(data.hasMore),
        nextCursor: data.nextCursor || null,
      };
    } catch (error) {
      // Rethrown, not swallowed into an empty page. A caller that pages has a
      // "load more" control to leave alone and an error to show; handing it
      // `{hasMore: false}` for a network blip would tell the reader their
      // library ends here.
      console.error('Get favourites page API Error:', error);
      throw error;
    }
  }

  // ---------------------------------------------------------- the keys ---
  //
  // The identity of every save and nothing else — no designer, no image path,
  // no timestamp. This is what lets the rows above be paged: a star is lit by
  // asking whether the thing on screen is saved, of every thumbnail in a
  // strip, so that answer has to be local AND complete. A saved look on a page
  // the client has not fetched would read as unsaved, and pressing its star
  // would write a second save of a row the server already holds.
  //
  // The rows come back in `shape`'s nesting minus the display fields, so
  // `targetOfRow` in useSaves reads a key and a full favourite identically and
  // there is only ever one key function.
  static async getFavouriteKeys() {
    try {
      const response = await fetch(`${ApiClient.BASE_URL}/api/favourites/keys`, {
        credentials: 'include',
        method: 'GET',
      });

      if (!response.ok) {
        ApiClient.checkAuth(response);
        throw new Error(`API call failed: ${response.statusText}`);
      }

      const data = await response.json();
      return data.keys || [];
    } catch (error) {
      // Rethrown, and this is the one where it matters most. An empty key set
      // is indistinguishable from a reader who has saved nothing: every star
      // goes dark, and the next press writes a second save of a row the server
      // already holds. So a failure here is an error the hook reports, never a
      // quiet [].
      console.error('Get favourite keys API Error:', error);
      throw error;
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
