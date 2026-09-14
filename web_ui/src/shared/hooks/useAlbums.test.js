import { renderHook, act, waitFor } from '@testing-library/react';
import { AlbumsAPI } from '../api';
import { keyOf } from './useSaves';
import {
  useAlbums, applyOrder, itemKeyOf, coverOf, wrote, sameAlbum,
} from './useAlbums';

// Two shows, fully described, because the mistake an add has to keep
// impossible is a look written out of two of them at once: the look write is
// positional and two of its three arguments are urls.
const GUCCI = {
  season: { name: 'Spring 1999', url: 'https://ex.test/season/ss99', link_text: 'SS99' },
  collection: { designer: 'Gucci', url: 'https://ex.test/show/gucci-ss99' },
};
const PRADA = {
  season: { name: 'Fall 2001', url: 'https://ex.test/season/fw01', link_text: 'FW01' },
  collection: { designer: 'Prada', url: 'https://ex.test/show/prada-fw01' },
};

// A target, as useSaves takes one: something that may not be saved yet.
const look = (show, number, total = 40) => ({
  kind: 'look', ...show, look: { number, total }, imagePath: `x/look-${number}.jpg`,
});
const showTarget = (s) => ({ kind: 'show', ...s, imagePath: 'x/look-1.jpg' });
const viewTarget = (filters, name) => ({ kind: 'view', filters, name });

// A row as the album and favourites endpoints send one: it has an id.
const item = (id, number, show = GUCCI) => ({
  id,
  kind: 'look',
  season: show.season,
  collection: show.collection,
  look: { number, total: 40 },
  view: { name: '', filters: {} },
  image_path: `x/look-${number}.jpg`,
  sort_index: number * 1024,
  placement: { x: null, y: null, w: null, z: null },
});

const shelf = () => ([
  {
    id: 1, name: 'Resort', layout_mode: 'grid', sort_by: 'added',
    item_count: 3, cover_image_path: 'x/look-1.jpg', created_at: '2026-09-01T00:00:00+00:00',
  },
  {
    id: 2, name: 'Tailoring', layout_mode: 'grid', sort_by: 'added',
    item_count: 0, cover_image_path: null, created_at: '2026-08-01T00:00:00+00:00',
  },
]);

const openAlbum = () => ({
  album: { id: 1, name: 'Resort', layout_mode: 'grid', sort_by: 'added' },
  items: [item(11, 1), item(12, 2), item(13, 3)],
});

// Every answer below comes through AlbumsEndpoints.albumRequest, which carries
// `ok` and `status` beside the body. The mocks carry them too, because the
// difference between a 404 and a 200 that says `success: false` is the whole
// of what `wrote` reads.
const OK = { ok: true, status: 200, success: true };
const NOT_FOUND = { ok: false, status: 404, success: false, error: 'no such album' };
const TAKEN = { ok: false, status: 409, success: false, error: "an album called 'Resort' already exists" };
const BAD = { ok: false, status: 400, success: false, error: 'unknown kind' };
// A failure that is not a 404, for the rollback tests: a 404 means the album is
// not yours, which drops it off the shelf entirely, and there is then no list
// left to check the rollback against.
const BOOM = { ok: false, status: 500, success: false, error: 'boom' };
const ADDED = { ...OK, favourite_id: 99, saved: true, added: true, message: 'Added to album' };

const ids = (rows) => rows.map(row => row.id);
const shelfRow = (result, id) => result.current.albums.find(row => row.id === id);

let api;
let errorLog;
let saves;

// The collaborator that owns the star. `useSaves` is the real one; here it is
// a set of keys, so a test can see the save half of an add and its rollback.
const fakeSaves = () => {
  const lit = new Set();
  return {
    lit,
    isSaved: jest.fn(target => lit.has(keyOf(target))),
    setSaved: jest.fn((target, on) => {
      if (on) lit.add(keyOf(target));
      else lit.delete(keyOf(target));
    }),
  };
};

beforeEach(() => {
  api = {
    getAlbums: jest.spyOn(AlbumsAPI, 'getAlbums').mockResolvedValue(shelf()),
    getAlbum: jest.spyOn(AlbumsAPI, 'getAlbum').mockResolvedValue(openAlbum()),
    createAlbum: jest.spyOn(AlbumsAPI, 'createAlbum').mockResolvedValue({
      ...OK, status: 201, album: { id: 3, name: 'New', layout_mode: 'grid', sort_by: 'added' },
    }),
    renameAlbum: jest.spyOn(AlbumsAPI, 'renameAlbum').mockResolvedValue(OK),
    setAlbumOptions: jest.spyOn(AlbumsAPI, 'setAlbumOptions').mockResolvedValue(OK),
    deleteAlbum: jest.spyOn(AlbumsAPI, 'deleteAlbum').mockResolvedValue(OK),
    addSavedToAlbum: jest.spyOn(AlbumsAPI, 'addSavedToAlbum').mockResolvedValue(ADDED),
    addLookToAlbum: jest.spyOn(AlbumsAPI, 'addLookToAlbum').mockResolvedValue(ADDED),
    addShowToAlbum: jest.spyOn(AlbumsAPI, 'addShowToAlbum').mockResolvedValue(ADDED),
    addViewToAlbum: jest.spyOn(AlbumsAPI, 'addViewToAlbum').mockResolvedValue(ADDED),
    removeFromAlbum: jest.spyOn(AlbumsAPI, 'removeFromAlbum').mockResolvedValue(OK),
    reorderAlbum: jest.spyOn(AlbumsAPI, 'reorderAlbum').mockResolvedValue({ ...OK, reordered: 3 }),
  };
  errorLog = jest.spyOn(console, 'error').mockImplementation(() => {});
  saves = fakeSaves();
});

afterEach(() => jest.restoreAllMocks());

const mount = async (albumId = null) => {
  const hook = renderHook(() => useAlbums(albumId, { saves }));
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
  if (albumId !== null) await waitFor(() => expect(hook.result.current.itemsLoading).toBe(false));
  return hook;
};

// ── the pure parts ────────────────────────────────────────────────────────

describe('an album id from a route and one from the server are one id', () => {
  test('a string and a number match; nothing matches nothing', () => {
    expect(sameAlbum('7', 7)).toBe(true);
    expect(sameAlbum(7, 8)).toBe(false);
    expect(sameAlbum(null, null)).toBe(false);
    expect(sameAlbum(undefined, 7)).toBe(false);
  });
});

describe('the cover of a list of items', () => {
  test('is the first one with a photograph', () => {
    expect(coverOf([{ image_path: '' }, { image_path: 'b.jpg' }, { image_path: 'c.jpg' }]))
      .toBe('b.jpg');
  });

  test('is null for an album of nothing but saved views', () => {
    expect(coverOf([{ kind: 'view', image_path: '' }])).toBeNull();
    expect(coverOf([])).toBeNull();
  });
});

describe('an item key', () => {
  test('is the content key, so one thing added two ways is one write', () => {
    // The same look, once as a saved row with an id and once as a target.
    expect(itemKeyOf(item(11, 1))).toBe(keyOf(look(GUCCI, 1)));
    expect(itemKeyOf(item(11, 1))).not.toBe(itemKeyOf(item(12, 2)));
  });

  test('falls back to the id when the row names nothing', () => {
    expect(itemKeyOf({ id: 5, kind: 'look' })).toBe('#5');
    expect(itemKeyOf({ kind: 'look' })).toBeNull();
  });
});

describe('an order applied to the rows there are', () => {
  test('puts them in the order named', () => {
    expect(ids(applyOrder([item(11, 1), item(12, 2), item(13, 3)], [13, 11, 12])))
      .toEqual([13, 11, 12]);
  });

  test('keeps anything unnamed at the end, in the order it was in', () => {
    const rows = [item(11, 1), item(12, 2), item(13, 3)];
    expect(ids(applyOrder(rows, [13]))).toEqual([13, 11, 12]);
  });

  test('an id for a row that is gone moves nothing', () => {
    expect(ids(applyOrder([item(11, 1), item(12, 2)], [99, 12, 11]))).toEqual([12, 11]);
  });
});

describe('whether the server made the change', () => {
  test('a 404, a 409 and a 400 are all failures', () => {
    expect(wrote(NOT_FOUND)).toBe(false);
    expect(wrote(TAKEN)).toBe(false);
    expect(wrote(BAD)).toBe(false);
  });

  test('a 200 saying success:false is a failure unless the refusal is the answer', () => {
    const refused = { ok: true, status: 200, success: false, message: 'Not in that album' };
    expect(wrote(refused)).toBe(false);
    expect(wrote(refused, { refusalMeansDone: true })).toBe(true);
  });

  test('an answer with neither field is taken at its word', () => {
    expect(wrote({})).toBe(true);
    expect(wrote({ success: true })).toBe(true);
  });
});

// ── loading ───────────────────────────────────────────────────────────────

describe('loading', () => {
  test('the shelf arrives and no album is open without one', async () => {
    const { result } = await mount();
    expect(result.current.albums).toHaveLength(2);
    expect(result.current.album).toBeNull();
    expect(result.current.items).toEqual([]);
    expect(api.getAlbum).not.toHaveBeenCalled();
    expect(result.current.error).toBeNull();
  });

  test('an open album arrives with its items in the order the server sent', async () => {
    const { result } = await mount(1);
    expect(api.getAlbum).toHaveBeenCalledWith(1);
    expect(result.current.album.name).toBe('Resort');
    expect(ids(result.current.items)).toEqual([11, 12, 13]);
  });

  test('an album that is not yours is dropped from the shelf, not shown empty', async () => {
    api.getAlbum.mockResolvedValue(null);          // the client's 404
    const { result } = await mount(1);
    expect(result.current.album).toBeNull();
    expect(result.current.items).toEqual([]);
    expect(ids(result.current.albums)).toEqual([2]);
  });

  test('a shelf that will not load leaves an error and an empty shelf', async () => {
    api.getAlbums.mockRejectedValue(new Error('down'));
    const { result } = await mount();
    expect(result.current.albums).toEqual([]);
    expect(result.current.error).toBeTruthy();
    expect(errorLog).toHaveBeenCalled();
  });
});

// ── the album itself ──────────────────────────────────────────────────────

describe('making an album', () => {
  test('the new album is on the shelf, first, with a count to render', async () => {
    const { result } = await mount();
    let made;
    await act(async () => { made = await result.current.createAlbum('New'); });
    expect(made.id).toBe(3);
    expect(ids(result.current.albums)).toEqual([3, 1, 2]);
    expect(result.current.albums[0].item_count).toBe(0);
    expect(result.current.albums[0].cover_image_path).toBeNull();
  });

  test('a name this user already has is refused and puts nothing on the shelf', async () => {
    api.createAlbum.mockResolvedValue(TAKEN);
    const { result } = await mount();
    let made;
    await act(async () => { made = await result.current.createAlbum('Resort'); });
    expect(made).toBeNull();
    expect(ids(result.current.albums)).toEqual([1, 2]);
    expect(String(result.current.error.message)).toContain('already exists');
  });

  test('a request that throws is an error, not a half-made album', async () => {
    api.createAlbum.mockRejectedValue(new Error('down'));
    const { result } = await mount();
    let made;
    await act(async () => { made = await result.current.createAlbum('New'); });
    expect(made).toBeNull();
    expect(ids(result.current.albums)).toEqual([1, 2]);
    expect(result.current.error).toBeTruthy();
  });
});

describe('renaming an album', () => {
  test('the new name shows before the server answers', async () => {
    let settle;
    api.renameAlbum.mockImplementation(() => new Promise(res => { settle = res; }));
    const { result } = await mount(1);

    await act(async () => { result.current.renameAlbum(1, 'Resort 2025'); });
    expect(shelfRow(result, 1).name).toBe('Resort 2025');
    expect(result.current.album.name).toBe('Resort 2025');      // and on the open album

    await act(async () => { settle(OK); });
    expect(shelfRow(result, 1).name).toBe('Resort 2025');
  });

  test('a name the server refuses goes back to the old one', async () => {
    api.renameAlbum.mockResolvedValue(TAKEN);
    const { result } = await mount(1);

    await act(async () => { await result.current.renameAlbum(1, 'Tailoring'); });

    expect(shelfRow(result, 1).name).toBe('Resort');
    expect(result.current.album.name).toBe('Resort');
    expect(String(result.current.error.message)).toContain('already exists');
  });

  test('a rename that throws goes back to the old one', async () => {
    api.renameAlbum.mockRejectedValue(new Error('down'));
    const { result } = await mount(1);
    await act(async () => { await result.current.renameAlbum(1, 'Whatever'); });
    expect(shelfRow(result, 1).name).toBe('Resort');
    expect(result.current.error).toBeTruthy();
  });

  test('a 404 puts the name back AND stops showing the album', async () => {
    api.renameAlbum.mockResolvedValue(NOT_FOUND);
    const { result } = await mount();
    await act(async () => { await result.current.renameAlbum(1, 'Gone'); });
    expect(ids(result.current.albums)).toEqual([2]);
  });
});

describe('the album options', () => {
  test('the new sort shows before the server answers', async () => {
    let settle;
    api.setAlbumOptions.mockImplementation(() => new Promise(res => { settle = res; }));
    const { result } = await mount(1);

    await act(async () => { result.current.setAlbumOptions(1, { sortBy: 'designer' }); });

    expect(api.setAlbumOptions).toHaveBeenCalledWith(1, { sortBy: 'designer' });
    expect(result.current.album.sort_by).toBe('designer');
    expect(shelfRow(result, 1).sort_by).toBe('designer');
    await act(async () => { settle(OK); });
  });

  // 'designer' and 'season' are an ORDER BY over columns the client does not
  // hold for every kind, so the order itself is read back rather than guessed.
  test('a sort that changed reads the items again, in the order the server sends', async () => {
    const { result } = await mount(1);
    expect(api.getAlbum).toHaveBeenCalledTimes(1);
    const resorted = openAlbum();
    resorted.album.sort_by = 'designer';
    resorted.items = [item(13, 3), item(11, 1), item(12, 2)];
    api.getAlbum.mockResolvedValue(resorted);

    await act(async () => { await result.current.setAlbumOptions(1, { sortBy: 'designer' }); });

    expect(api.getAlbum).toHaveBeenCalledTimes(2);
    expect(result.current.album.sort_by).toBe('designer');
    expect(ids(result.current.items)).toEqual([13, 11, 12]);
  });

  test('a refused sort goes back and does not read the items again', async () => {
    api.setAlbumOptions.mockResolvedValue(BAD);
    const { result } = await mount(1);
    await act(async () => { await result.current.setAlbumOptions(1, { sortBy: 'nonsense' }); });
    expect(result.current.album.sort_by).toBe('added');
    expect(api.getAlbum).toHaveBeenCalledTimes(1);
    expect(result.current.error).toBeTruthy();
  });

  test('changing the layout leaves the sort alone at both ends', async () => {
    const { result } = await mount(1);
    await act(async () => { await result.current.setAlbumOptions(1, { layoutMode: 'canvas' }); });
    expect(api.setAlbumOptions).toHaveBeenCalledWith(1, { layoutMode: 'canvas' });
    expect(result.current.album.layout_mode).toBe('canvas');
    expect(result.current.album.sort_by).toBe('added');
    expect(api.getAlbum).toHaveBeenCalledTimes(1);       // the order did not change
  });
});

describe('deleting an album', () => {
  test('it goes off the shelf at once and stays off', async () => {
    const { result } = await mount();
    await act(async () => { await result.current.deleteAlbum(1); });
    expect(api.deleteAlbum).toHaveBeenCalledWith(1);
    expect(ids(result.current.albums)).toEqual([2]);
  });

  test('a refused delete puts it back where it was', async () => {
    api.deleteAlbum.mockResolvedValue({ ok: true, status: 200, success: false, error: 'no' });
    const { result } = await mount();

    await act(async () => { await result.current.deleteAlbum(1); });

    expect(ids(result.current.albums)).toEqual([1, 2]);      // first again, not last
    expect(result.current.albums[0].name).toBe('Resort');
    expect(result.current.error).toBeTruthy();
  });

  test('a delete that throws puts it back', async () => {
    api.deleteAlbum.mockRejectedValue(new Error('down'));
    const { result } = await mount();
    await act(async () => { await result.current.deleteAlbum(2); });
    expect(ids(result.current.albums)).toEqual([1, 2]);
  });
});

// ── adding: one press, two server effects ────────────────────────────────

describe('adding something already saved', () => {
  test('the tile and the count move before the server answers', async () => {
    let settle;
    api.addSavedToAlbum.mockImplementation(() => new Promise(res => { settle = res; }));
    const { result } = await mount(1);

    await act(async () => { result.current.addToAlbum(1, item(21, 9)); });

    expect(api.addSavedToAlbum).toHaveBeenCalledWith(1, 21);
    expect(ids(result.current.items)).toEqual([11, 12, 13, 21]);
    expect(shelfRow(result, 1).item_count).toBe(4);

    await act(async () => { settle({ ...OK, favourite_id: 21, saved: false, added: true }); });
    expect(ids(result.current.items)).toEqual([11, 12, 13, 21]);
    expect(shelfRow(result, 1).item_count).toBe(4);
  });

  test('a refused add takes the tile and the count back', async () => {
    api.addSavedToAlbum.mockResolvedValue({ ...NOT_FOUND, error: 'no such favourite' });
    const { result } = await mount(1);

    await act(async () => { await result.current.addToAlbum(1, item(21, 9)); });

    expect(ids(result.current.items)).toEqual([11, 12, 13]);
    expect(shelfRow(result, 1).item_count).toBe(3);
    expect(result.current.error).toBeTruthy();
  });

  test("a 404 for a favourite does NOT take the album off the shelf", async () => {
    // The endpoint answers 404 for an album that is not yours AND for a
    // favourite that is not yours. Dropping the album for the second is a
    // wrong answer to a right refusal.
    api.addSavedToAlbum.mockResolvedValue({ ...NOT_FOUND, error: 'no such favourite' });
    const { result } = await mount(1);
    await act(async () => { await result.current.addToAlbum(1, item(21, 9)); });
    expect(ids(result.current.albums)).toEqual([1, 2]);
  });

  test('"already in album" is not a failure, and is not counted twice', async () => {
    api.addSavedToAlbum.mockResolvedValue({
      ...OK, favourite_id: 11, saved: false, added: false, message: 'Already in album',
    });
    const { result } = await mount(1);

    await act(async () => { await result.current.addToAlbum(1, item(11, 1)); });

    expect(ids(result.current.items)).toEqual([11, 12, 13]);    // one tile, not two
    expect(shelfRow(result, 1).item_count).toBe(3);
    expect(result.current.error).toBeNull();
  });

  test('adding to an album that is not open moves its count and its cover', async () => {
    const { result } = await mount(1);
    await act(async () => { await result.current.addToAlbum(2, item(21, 9)); });
    expect(shelfRow(result, 2).item_count).toBe(1);
    expect(shelfRow(result, 2).cover_image_path).toBe('x/look-9.jpg');
    expect(ids(result.current.items)).toEqual([11, 12, 13]);    // the open album is untouched
  });
});

describe('adding something that is not saved yet', () => {
  test('the look is written off one show, and the star lights with the tile', async () => {
    const { result } = await mount(1);
    const target = look(PRADA, 7, 27);

    await act(async () => { await result.current.addToAlbum(1, target); });

    expect(api.addLookToAlbum).toHaveBeenCalledWith(
      1, PRADA.season, PRADA.collection, { number: 7, total: 27 }, 'x/look-7.jpg');
    expect(api.addLookToAlbum.mock.calls[0][1]).not.toBe(GUCCI.season);
    expect(api.addLookToAlbum.mock.calls[0][2]).not.toBe(GUCCI.collection);
    expect(saves.isSaved(target)).toBe(true);
    expect(ids(result.current.items)).toEqual([11, 12, 13, 99]);   // the id the server gave
    expect(shelfRow(result, 1).item_count).toBe(4);
  });

  test('a show is added with no look number, a view with its canonical filters', async () => {
    const { result } = await mount(1);

    await act(async () => { await result.current.addToAlbum(1, showTarget(PRADA)); });
    expect(api.addShowToAlbum)
      .toHaveBeenCalledWith(1, PRADA.season, PRADA.collection, 'x/look-1.jpg');

    await act(async () => {
      await result.current.addToAlbum(1, viewTarget({ city: ' Paris ', year: 1997 }, 'P97'));
    });
    expect(api.addViewToAlbum).toHaveBeenCalledWith(1, { city: 'Paris', year: '1997' }, 'P97');
  });

  test('the tile is on screen before the server answers', async () => {
    let settle;
    api.addLookToAlbum.mockImplementation(() => new Promise(res => { settle = res; }));
    const { result } = await mount(1);

    await act(async () => { result.current.addToAlbum(1, look(PRADA, 7)); });
    expect(result.current.items).toHaveLength(4);
    expect(result.current.items[3].id).toBeNull();              // no id until the server says
    expect(result.current.items[3].collection.designer).toBe('Prada');

    await act(async () => { settle(ADDED); });
    expect(result.current.items[3].id).toBe(99);
  });

  // ── the rollback of both halves, at each half ──────────────────────────
  //
  // The server does the save and the add in one transaction, so a failure at
  // either leaves nothing behind on that side. What is tested here is that the
  // client agrees: no tile, no count, and no lit star.

  test('a save the server would not make rolls back the tile AND the star', async () => {
    api.addLookToAlbum.mockResolvedValue(BAD);        // the save half: 400, unknown kind
    const { result } = await mount(1);
    const target = look(PRADA, 7);

    await act(async () => { await result.current.addToAlbum(1, target); });

    expect(ids(result.current.items)).toEqual([11, 12, 13]);
    expect(shelfRow(result, 1).item_count).toBe(3);
    expect(saves.isSaved(target)).toBe(false);
    expect(saves.setSaved).toHaveBeenLastCalledWith(target, false);
    expect(result.current.error).toBeTruthy();
  });

  test('an add the server would not make rolls back the tile AND the star', async () => {
    api.addLookToAlbum.mockResolvedValue(NOT_FOUND);  // the add half: no such album
    const { result } = await mount(1);
    const target = look(PRADA, 7);

    await act(async () => { await result.current.addToAlbum(1, target); });

    expect(ids(result.current.items)).toEqual([11, 12, 13]);
    expect(shelfRow(result, 1).item_count).toBe(3);
    expect(saves.isSaved(target)).toBe(false);
  });

  test('a request that never arrives rolls back both halves', async () => {
    api.addLookToAlbum.mockRejectedValue(new Error('down'));
    const { result } = await mount(1);
    const target = look(PRADA, 7);
    await act(async () => { await result.current.addToAlbum(1, target); });
    expect(result.current.items).toHaveLength(3);
    expect(saves.isSaved(target)).toBe(false);
  });

  // The other direction of the same bug: un-starring a row that was already
  // saved would leave a dark star over a saved thing.
  test('a failure never puts out a star this add did not light', async () => {
    api.addLookToAlbum.mockResolvedValue(NOT_FOUND);
    const target = look(GUCCI, 1);
    saves.lit.add(keyOf(target));                    // already saved, by the star
    const { result } = await mount(1);

    await act(async () => { await result.current.addToAlbum(1, target); });

    expect(saves.isSaved(target)).toBe(true);
    expect(saves.setSaved).not.toHaveBeenCalled();
    expect(result.current.items).toHaveLength(3);    // and the album half still rolled back
  });

  test('a successful add of something already saved does not touch the star', async () => {
    const target = look(GUCCI, 1);
    saves.lit.add(keyOf(target));
    const { result } = await mount(1);
    await act(async () => { await result.current.addToAlbum(1, target); });
    expect(saves.setSaved).not.toHaveBeenCalled();
  });

  test('with no collaborator the album half still works', async () => {
    const hook = renderHook(() => useAlbums(1));
    await waitFor(() => expect(hook.result.current.itemsLoading).toBe(false));
    await act(async () => { await hook.result.current.addToAlbum(1, look(PRADA, 7)); });
    expect(hook.result.current.items).toHaveLength(4);
  });

  test('a target that names nothing is not a write', async () => {
    const { result } = await mount(1);
    let ok;
    await act(async () => { ok = await result.current.addToAlbum(1, { kind: 'look' }); });
    expect(ok).toBe(false);
    await act(async () => { ok = await result.current.addToAlbum(1, null); });
    expect(ok).toBe(false);
    expect(api.addLookToAlbum).not.toHaveBeenCalled();
  });
});

// ── removing ─────────────────────────────────────────────────────────────

describe('taking something out of an album', () => {
  test('the tile and the count go at once, and the cover follows the tiles', async () => {
    const { result } = await mount(1);

    await act(async () => { await result.current.removeFromAlbum(1, 11); });

    expect(api.removeFromAlbum).toHaveBeenCalledWith(1, 11);
    expect(ids(result.current.items)).toEqual([12, 13]);
    expect(shelfRow(result, 1).item_count).toBe(2);
    expect(shelfRow(result, 1).cover_image_path).toBe('x/look-2.jpg');
  });

  test('a refused remove puts the tile back where it was', async () => {
    api.removeFromAlbum.mockResolvedValue(BOOM);
    const { result } = await mount(1);

    await act(async () => { await result.current.removeFromAlbum(1, 12); });

    expect(ids(result.current.items)).toEqual([11, 12, 13]);    // second again, not last
    expect(shelfRow(result, 1).item_count).toBe(3);
    expect(result.current.error).toBeTruthy();
  });

  test('a remove that throws puts the tile back', async () => {
    api.removeFromAlbum.mockRejectedValue(new Error('down'));
    const { result } = await mount(1);
    await act(async () => { await result.current.removeFromAlbum(1, 12); });
    expect(ids(result.current.items)).toEqual([11, 12, 13]);
  });

  test('a 404 puts the tile back and stops showing the album', async () => {
    api.removeFromAlbum.mockResolvedValue(NOT_FOUND);
    const { result } = await mount(1);

    await act(async () => { await result.current.removeFromAlbum(1, 12); });

    expect(ids(result.current.albums)).toEqual([2]);
    expect(result.current.album).toBeNull();
  });

  // The refusal that means "already how you asked for it". Rolling this one
  // back would put a tile on screen for a membership row that does not exist.
  test('"Not in that album" leaves the tile gone and raises nothing', async () => {
    api.removeFromAlbum.mockResolvedValue({
      ok: true, status: 200, success: false, message: 'Not in that album',
    });
    const { result } = await mount(1);

    await act(async () => { await result.current.removeFromAlbum(1, 12); });

    expect(ids(result.current.items)).toEqual([11, 13]);
    expect(shelfRow(result, 1).item_count).toBe(2);
    expect(result.current.error).toBeNull();
  });
});

// ── the order ────────────────────────────────────────────────────────────

describe('reordering', () => {
  test('the new order shows before the server answers, and one request carries it', async () => {
    let settle;
    api.reorderAlbum.mockImplementation(() => new Promise(res => { settle = res; }));
    const { result } = await mount(1);

    await act(async () => { result.current.reorderAlbum(1, [13, 11, 12]); });

    expect(api.reorderAlbum).toHaveBeenCalledTimes(1);
    expect(api.reorderAlbum).toHaveBeenCalledWith(1, [13, 11, 12]);
    expect(ids(result.current.items)).toEqual([13, 11, 12]);

    await act(async () => { settle({ ...OK, reordered: 3 }); });
    expect(ids(result.current.items)).toEqual([13, 11, 12]);
  });

  test('a refused reorder goes back to the exact order it was in', async () => {
    api.reorderAlbum.mockResolvedValue(BOOM);
    const { result } = await mount(1);

    await act(async () => { await result.current.reorderAlbum(1, [13, 12, 11]); });

    expect(ids(result.current.items)).toEqual([11, 12, 13]);
    expect(result.current.error).toBeTruthy();
  });

  test('a reorder that throws goes back to the exact order it was in', async () => {
    api.reorderAlbum.mockRejectedValue(new Error('down'));
    const { result } = await mount(1);
    await act(async () => { await result.current.reorderAlbum(1, [12, 13, 11]); });
    expect(ids(result.current.items)).toEqual([11, 12, 13]);
  });

  // Two drags racing. The server is never asked for two orders at once, and
  // what lands is the last order the reader made — not an interleaving of the
  // two, which is an order nobody asked for.
  test('a second reorder waits for the first, then is sent whole', async () => {
    let settleFirst;
    api.reorderAlbum.mockImplementationOnce(() => new Promise(res => { settleFirst = res; }));
    const { result } = await mount(1);

    await act(async () => { result.current.reorderAlbum(1, [13, 11, 12]); });
    await act(async () => { result.current.reorderAlbum(1, [12, 13, 11]); });

    expect(api.reorderAlbum).toHaveBeenCalledTimes(1);        // not sent alongside
    expect(ids(result.current.items)).toEqual([12, 13, 11]);  // but shown at once

    await act(async () => { settleFirst({ ...OK, reordered: 3 }); });
    await waitFor(() => expect(api.reorderAlbum).toHaveBeenCalledTimes(2));
    expect(api.reorderAlbum.mock.calls[1][1]).toEqual([12, 13, 11]);
    expect(ids(result.current.items)).toEqual([12, 13, 11]);
  });

  test('when the first of two fails, the held one is dropped and the order is the old one',
    async () => {
      let settleFirst;
      api.reorderAlbum.mockImplementationOnce(() => new Promise(res => { settleFirst = res; }));
      const { result } = await mount(1);

      await act(async () => { result.current.reorderAlbum(1, [13, 11, 12]); });
      await act(async () => { result.current.reorderAlbum(1, [12, 13, 11]); });

      await act(async () => { settleFirst(BOOM); });

      expect(api.reorderAlbum).toHaveBeenCalledTimes(1);        // the held one never ran
      expect(ids(result.current.items)).toEqual([11, 12, 13]);  // the order the server holds
    });

  test('a reorder of an album that is not open is still written', async () => {
    const { result } = await mount(1);
    await act(async () => { await result.current.reorderAlbum(2, [5, 6]); });
    expect(api.reorderAlbum).toHaveBeenCalledWith(2, [5, 6]);
    expect(ids(result.current.items)).toEqual([11, 12, 13]);
  });
});

// ── one write at a time, per thing written ───────────────────────────────

describe('writes are serialised per thing, not globally', () => {
  test('two different tiles are written at the same time', async () => {
    api.removeFromAlbum.mockImplementation(() => new Promise(() => {}));   // never settles
    const { result } = await mount(1);

    await act(async () => { result.current.removeFromAlbum(1, 11); });
    await act(async () => { result.current.removeFromAlbum(1, 12); });

    expect(api.removeFromAlbum).toHaveBeenCalledTimes(2);
    expect(ids(result.current.items)).toEqual([13]);
  });

  test('a rename does not wait for a tile, and a tile does not wait for a rename', async () => {
    api.renameAlbum.mockImplementation(() => new Promise(() => {}));
    api.removeFromAlbum.mockImplementation(() => new Promise(() => {}));
    const { result } = await mount(1);

    await act(async () => { result.current.renameAlbum(1, 'Resort 2025'); });
    await act(async () => { result.current.removeFromAlbum(1, 11); });
    await act(async () => { result.current.reorderAlbum(1, [13, 12]); });

    expect(api.renameAlbum).toHaveBeenCalledTimes(1);
    expect(api.removeFromAlbum).toHaveBeenCalledTimes(1);
    expect(api.reorderAlbum).toHaveBeenCalledTimes(1);
  });

  test('the same tile twice is held, one deep, and runs when the first lands', async () => {
    let settleAdd;
    api.addSavedToAlbum.mockImplementationOnce(() => new Promise(res => { settleAdd = res; }));
    const { result } = await mount(1);

    await act(async () => { result.current.addToAlbum(1, item(21, 9)); });
    await act(async () => { result.current.removeFromAlbum(1, 21); });

    expect(api.addSavedToAlbum).toHaveBeenCalledTimes(1);
    expect(api.removeFromAlbum).not.toHaveBeenCalled();

    await act(async () => { settleAdd({ ...OK, favourite_id: 21, saved: false, added: true }); });
    await waitFor(() => expect(api.removeFromAlbum).toHaveBeenCalledTimes(1));
    expect(ids(result.current.items)).toEqual([11, 12, 13]);
  });
});
