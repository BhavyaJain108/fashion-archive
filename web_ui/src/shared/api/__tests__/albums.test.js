import AlbumsEndpoints from '../albums';
import ApiClient from '../client';

// What each call puts on the wire, and what it does with the answers the album
// endpoints actually give. Two of those answers are the point of the file:
//
//   404  an album that is not yours — the server will not confirm it exists,
//        so this end must not treat it as an error worth retrying
//   409  a name you already used
//
// and the reorder, which is one request for the whole order rather than one per
// item.

let fetchMock;

const respondWith = (status, body) => {
  fetchMock.mockImplementationOnce(() => Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: () => Promise.resolve(body),
  }));
};

beforeEach(() => {
  fetchMock = jest.fn(() => Promise.resolve({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: () => Promise.resolve({ success: true }),
  }));
  global.fetch = fetchMock;
});

afterEach(() => {
  delete global.fetch;
  jest.restoreAllMocks();
});

const lastCall = () => {
  const [url, options] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
  return {
    url,
    method: options.method,
    body: options.body === undefined ? undefined : JSON.parse(options.body),
  };
};

const SEASON = { name: 'Fall 2024', url: 'https://ex.com/f24', link_text: 'F24' };
const COLLECTION = { designer: 'Balenciaga', url: 'https://ex.com/balenciaga-f24' };

describe('the shelf', () => {
  test('getAlbums returns the array', async () => {
    respondWith(200, { albums: [{ id: 1, name: 'Resort', item_count: 2 }], count: 1 });
    const albums = await AlbumsEndpoints.getAlbums();
    expect(albums).toHaveLength(1);
    expect(lastCall().url).toBe(`${ApiClient.BASE_URL}/api/albums`);
  });

  // An empty shelf and a dead session look identical once the array is empty.
  test('a failed listing throws rather than looking like an empty shelf', async () => {
    respondWith(401, {});
    await expect(AlbumsEndpoints.getAlbums()).rejects.toThrow();
  });

  test('a 401 is reported to the session hook', async () => {
    const onUnauthorized = jest.fn();
    ApiClient.onUnauthorized = onUnauthorized;
    respondWith(401, {});
    await expect(AlbumsEndpoints.getAlbums()).rejects.toThrow();
    expect(onUnauthorized).toHaveBeenCalled();
    ApiClient.onUnauthorized = null;
  });
});

describe('one album', () => {
  test('getAlbum asks for the album and gets its items', async () => {
    respondWith(200, { album: { id: 3, name: 'Resort' }, items: [{ id: 9 }] });
    const answer = await AlbumsEndpoints.getAlbum(3);
    expect(lastCall().url).toBe(`${ApiClient.BASE_URL}/api/albums/3`);
    expect(answer.items).toHaveLength(1);
  });

  // The server answers 404 for an album that is not yours as well as one that
  // does not exist, and deliberately does not say which.
  test('a 404 is null, not a throw', async () => {
    respondWith(404, { success: false, error: 'no such album' });
    expect(await AlbumsEndpoints.getAlbum(3)).toBeNull();
  });

  test('a sort can be asked for without storing it', async () => {
    await AlbumsEndpoints.getAlbum(3, { sortBy: 'designer' });
    expect(lastCall().url).toBe(`${ApiClient.BASE_URL}/api/albums/3?sort_by=designer`);
  });
});

describe('making and naming', () => {
  test('createAlbum posts the name', async () => {
    await AlbumsEndpoints.createAlbum('Resort');
    const { url, method, body } = lastCall();
    expect(url).toBe(`${ApiClient.BASE_URL}/api/albums`);
    expect(method).toBe('POST');
    expect(body).toEqual({ name: 'Resort' });
  });

  test('a duplicate name comes back with its status and reason', async () => {
    respondWith(409, { success: false, error: "an album called 'Resort' already exists" });
    const answer = await AlbumsEndpoints.createAlbum('Resort');
    expect(answer.ok).toBe(false);
    expect(answer.status).toBe(409);
    expect(answer.error).toMatch(/already exists/);
  });

  test('renameAlbum patches only the name', async () => {
    await AlbumsEndpoints.renameAlbum(3, 'Resort 2025');
    const { method, body } = lastCall();
    expect(method).toBe('PATCH');
    expect(body).toEqual({ name: 'Resort 2025' });
  });

  // Sending the one it was not asked to change would reset it server-side.
  test('setAlbumOptions sends only what it was given', async () => {
    await AlbumsEndpoints.setAlbumOptions(3, { sortBy: 'season' });
    expect(lastCall().body).toEqual({ sort_by: 'season' });
  });

  test('deleteAlbum deletes the album', async () => {
    await AlbumsEndpoints.deleteAlbum(3);
    const { url, method } = lastCall();
    expect(url).toBe(`${ApiClient.BASE_URL}/api/albums/3`);
    expect(method).toBe('DELETE');
  });
});

describe('what is in one', () => {
  test('addSavedToAlbum sends the favourite id', async () => {
    await AlbumsEndpoints.addSavedToAlbum(3, 41);
    const { url, method, body } = lastCall();
    expect(url).toBe(`${ApiClient.BASE_URL}/api/albums/3/items`);
    expect(method).toBe('POST');
    expect(body).toEqual({ favourite_id: 41 });
  });

  // The same body `addFavourite` sends. A different one here would save a
  // second copy of a look the reader had already starred.
  test('addLookToAlbum sends a look body and no kind', async () => {
    await AlbumsEndpoints.addLookToAlbum(3, SEASON, COLLECTION, { number: 12 }, '/img/12.jpg');
    const { body } = lastCall();
    expect(body).toEqual({
      season: SEASON,
      collection: COLLECTION,
      look: { number: 12 },
      image_path: '/img/12.jpg',
      notes: '',
    });
    expect(body.kind).toBeUndefined();
  });

  test('addShowToAlbum sends kind show and no look', async () => {
    await AlbumsEndpoints.addShowToAlbum(3, SEASON, COLLECTION, '/img/1.jpg');
    const { body } = lastCall();
    expect(body.kind).toBe('show');
    expect(body.look).toBeUndefined();
  });

  test('addViewToAlbum sends the filters as themselves', async () => {
    await AlbumsEndpoints.addViewToAlbum(3, { city: 'Paris' });
    const { body } = lastCall();
    expect(body).toEqual({ kind: 'view', filters: { city: 'Paris' }, name: '' });
  });

  test('the answer says which halves happened', async () => {
    respondWith(200, { success: true, favourite_id: 41, saved: true, added: true });
    const answer = await AlbumsEndpoints.addLookToAlbum(
      3, SEASON, COLLECTION, { number: 12 }, '/img/12.jpg'
    );
    expect(answer.saved).toBe(true);
    expect(answer.added).toBe(true);
    expect(answer.favourite_id).toBe(41);
  });

  test('removeFromAlbum names both ids in the path', async () => {
    await AlbumsEndpoints.removeFromAlbum(3, 41);
    const { url, method } = lastCall();
    expect(url).toBe(`${ApiClient.BASE_URL}/api/albums/3/items/41`);
    expect(method).toBe('DELETE');
  });
});

describe('the order', () => {
  // One request, not one per item.
  test('reorderAlbum sends the whole list once', async () => {
    await AlbumsEndpoints.reorderAlbum(3, [9, 4, 7]);
    const { url, method, body } = lastCall();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(url).toBe(`${ApiClient.BASE_URL}/api/albums/3/order`);
    expect(method).toBe('PUT');
    expect(body).toEqual({ favourite_ids: [9, 4, 7] });
  });
});

// ── an answer that could not be read ──────────────────────────────────────
//
// `albumRequest` answers an unreadable body with `{}`, which made a 2xx
// carrying a proxy's HTML error page — or nothing at all — arrive as
// `{ok: true, status: 200}`: indistinguishable from a write that worked and
// said so. `wrote` read it as success, `added` was undefined rather than
// false, and a tile was stamped with `favourite_id: undefined`.
//
// The envelope now says whether the body was read, so a caller can tell "the
// server said it did it" from "we have no idea what the server did".

describe('a 2xx whose body is not JSON', () => {
  const unreadable = (status = 200) => {
    fetchMock.mockImplementationOnce(() => Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      statusText: String(status),
      json: () => Promise.reject(new SyntaxError('Unexpected token < in JSON')),
    }));
  };

  test('is marked as unread rather than passed off as an empty success', async () => {
    unreadable();
    const answer = await AlbumsEndpoints.addSavedToAlbum(7, 55);
    expect(answer.ok).toBe(true);
    expect(answer.status).toBe(200);
    expect(answer.bodyRead).toBe(false);
  });

  test('a body that was read says so, even when it is empty', async () => {
    respondWith(200, {});
    const answer = await AlbumsEndpoints.addSavedToAlbum(7, 55);
    expect(answer.bodyRead).toBe(true);
  });

  test('a body that is not an object is not a body', async () => {
    respondWith(200, [1, 2, 3]);
    const answer = await AlbumsEndpoints.addSavedToAlbum(7, 55);
    expect(answer.bodyRead).toBe(false);
  });

  test('a server that sends its own bodyRead cannot forge this', async () => {
    respondWith(200, { bodyRead: false, favourite_id: 5, added: true });
    const answer = await AlbumsEndpoints.addSavedToAlbum(7, 55);
    expect(answer.bodyRead).toBe(true);
  });
});
