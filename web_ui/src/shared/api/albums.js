import ApiClient from './client';

// Albums: named groups of saved things, in an order the reader chose.
//
// Two things about the server are worth knowing at this end.
//
// **An album id that is not yours is a 404, not a 403.** The server will not
// confirm that somebody else's album exists, so "gone" and "never yours" arrive
// here as the same answer and there is nothing to tell apart. A 404 from any of
// these calls means: stop showing that album.
//
// **Adding something unsaved saves it first.** An album holds favourites, so
// `addLookToAlbum` sends the same body `addFavourite` sends and the server does
// both halves in one transaction. The answer says which halves happened —
// `saved` is whether the favourite was created by this request, `added` whether
// it went into the album — so a UI can say "saved and added" or just "added"
// without asking again.
export class AlbumsEndpoints {
  // Every call below is JSON in, JSON out, with the session cookie attached.
  // One place builds the request so the eight endpoints cannot drift in their
  // headers or in what they do about a dead session.
  //
  // The envelope keeps `status` because these endpoints answer with it: 404 is
  // an album that is not yours, 409 a name you already used, 400 a body the
  // server would not store. Throwing would discard the reason.
  //
  // It also keeps `bodyRead`, which says whether there was an answer to read
  // at all. A body that will not parse used to become `{}`, so a 2xx carrying
  // a proxy's HTML error page arrived here as `{ok: true, status: 200}` —
  // exactly what a write that succeeded and had nothing to add looks like.
  // `useAlbums.wrote` read that as success, `added` was undefined rather than
  // false, and a tile was stamped `favourite_id: undefined`. A 2xx nobody
  // could read is not a success and not a failure; it is unknown, and the
  // caller has to be able to tell.
  //
  // `bodyRead` is written AFTER the spread, so a server sending a field of
  // that name cannot decide this for us.
  static async albumRequest(path, { method = 'GET', body } = {}) {
    const hasBody = body !== undefined;
    const response = await fetch(`${ApiClient.BASE_URL}${path}`, {
      method,
      credentials: 'include',
      headers: hasBody ? { 'Content-Type': 'application/json' } : {},
      body: hasBody ? JSON.stringify(body) : undefined,
    });
    ApiClient.checkAuth(response);
    const data = await response.json().catch(() => null);
    const read = Boolean(data) && typeof data === 'object' && !Array.isArray(data);
    return { ok: response.ok, status: response.status, ...(read ? data : {}), bodyRead: read };
  }

  // ------------------------------------------------------------ the shelf ---

  // Every album with its `item_count` and `cover_image_path`, newest first —
  // one request for the whole shelf rather than one per album.
  //
  // A failed request throws rather than returning []. An empty shelf and a dead
  // session look identical once the array is empty, and answering [] to the
  // second is how a signed-out reader gets shown an empty library instead of a
  // sign-in prompt.
  static async getAlbums() {
    const answer = await AlbumsEndpoints.albumRequest('/api/albums');
    if (!answer.ok) throw new Error(`Could not load albums (${answer.status})`);
    return answer.albums || [];
  }

  // One album and everything in it. `sortBy` renders it in another order for
  // this request without storing the choice; leave it off for the album's own.
  // Null for an album that is not yours — the server will not say which of the
  // two reasons it is.
  static async getAlbum(albumId, { sortBy } = {}) {
    const query = sortBy ? `?sort_by=${encodeURIComponent(sortBy)}` : '';
    const answer = await AlbumsEndpoints.albumRequest(`/api/albums/${albumId}${query}`);
    if (answer.status === 404) return null;
    if (!answer.ok) throw new Error(`Could not load album ${albumId} (${answer.status})`);
    return { album: answer.album, items: answer.items || [] };
  }

  // --------------------------------------------------------- making, naming ---

  // 409 with an error to show when the name is taken: one name per user,
  // case-insensitively, because the name is the only handle on an album.
  static createAlbum(name, { layoutMode, sortBy } = {}) {
    const body = { name };
    if (layoutMode) body.layout_mode = layoutMode;
    if (sortBy) body.sort_by = sortBy;
    return AlbumsEndpoints.albumRequest('/api/albums', { method: 'POST', body });
  }

  static renameAlbum(albumId, name) {
    return AlbumsEndpoints.albumRequest(`/api/albums/${albumId}`, {
      method: 'PATCH',
      body: { name },
    });
  }

  // Only what is passed is sent, and only what is sent is written: changing the
  // sort must not reset the layout to its default on the way past.
  // The canvas arrangement, whole. Sent after a debounce, not per pointer move.
  static setAlbumLayout(albumId, items) {
    return AlbumsEndpoints.albumRequest(`/api/albums/${albumId}/layout`, {
      method: 'PUT', body: { items },
    });
  }

  static setAlbumOptions(albumId, { layoutMode, sortBy } = {}) {
    const body = {};
    if (layoutMode !== undefined) body.layout_mode = layoutMode;
    if (sortBy !== undefined) body.sort_by = sortBy;
    return AlbumsEndpoints.albumRequest(`/api/albums/${albumId}`, { method: 'PATCH', body });
  }

  // Deletes the album, not the favourites in it. The other button — the one
  // that un-saves — is `removeFavourite`, and the two must not be wired to the
  // same control.
  static deleteAlbum(albumId) {
    return AlbumsEndpoints.albumRequest(`/api/albums/${albumId}`, { method: 'DELETE' });
  }

  // ----------------------------------------------------- what is in one ---

  // Something already in the library, by its favourite id.
  static addSavedToAlbum(albumId, favouriteId) {
    return AlbumsEndpoints.albumRequest(`/api/albums/${albumId}/items`, {
      method: 'POST',
      body: { favourite_id: favouriteId },
    });
  }

  // A look that may not be saved yet. Same body as `addFavourite`, because the
  // server reads it with the same code — a different body here would save a
  // second copy of a look the reader had already starred.
  static addLookToAlbum(albumId, seasonData, collectionData, lookData, imagePath, notes = '') {
    return AlbumsEndpoints.albumRequest(`/api/albums/${albumId}/items`, {
      method: 'POST',
      body: {
        season: seasonData,
        collection: collectionData,
        look: lookData,
        image_path: imagePath,
        notes,
      },
    });
  }

  static addShowToAlbum(albumId, seasonData, collectionData, imagePath, notes = '') {
    return AlbumsEndpoints.albumRequest(`/api/albums/${albumId}/items`, {
      method: 'POST',
      body: {
        kind: 'show',
        season: seasonData,
        collection: collectionData,
        image_path: imagePath,
        notes,
      },
    });
  }

  // A saved view IS its filters — the server hashes them to decide whether it
  // has this view already — so the filter object is sent as itself.
  static addViewToAlbum(albumId, filters, name = '') {
    return AlbumsEndpoints.albumRequest(`/api/albums/${albumId}/items`, {
      method: 'POST',
      body: { kind: 'view', filters: filters || {}, name },
    });
  }

  static removeFromAlbum(albumId, favouriteId) {
    return AlbumsEndpoints.albumRequest(`/api/albums/${albumId}/items/${favouriteId}`, {
      method: 'DELETE',
    });
  }

  // ----------------------------------------------------------- the order ---

  // The whole arrangement in one request, first to last. Not one request per
  // item: N requests for one drag is N chances to arrive out of order, and the
  // order that sticks is then whichever one finished last.
  static reorderAlbum(albumId, favouriteIds) {
    return AlbumsEndpoints.albumRequest(`/api/albums/${albumId}/order`, {
      method: 'PUT',
      body: { favourite_ids: favouriteIds },
    });
  }
}

export default AlbumsEndpoints;
