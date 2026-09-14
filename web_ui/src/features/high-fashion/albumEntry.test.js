// The archive page's way into an album, and the wiring underneath it.
//
// THE TEST THIS FILE EXISTS FOR is the first one. `useAlbums` takes an
// optional `{ isSaved, setSaved }` collaborator so that adding something
// UNSAVED to an album can light its star without `useAlbums` becoming a
// second owner of the saved list. Nothing supplied it. The add worked, the
// row was saved — the album endpoint saves and files in one transaction —
// and the star over the photograph stayed dark until the next load of the
// favourites list. A reader watching the star they just filled in stay empty.
//
// Nothing that existed before could see that: `useAlbums.test.js` passes a
// fake collaborator, so it proves the hook asks; `useSaves.test.js` never
// hears of albums. The gap was the one line of JSX between them, which is
// the same class of bug `pageWiring.test.js` was written for.
//
// The harness is pageWiring's, for pageWiring's reason: a stream per show,
// one of which never answers, so the STALE WINDOW is reachable. An album
// write has to be keyed on the show whose photographs are on screen, exactly
// as the star beside it is, and outside that window the two are the same
// object and a mix-up is invisible.
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

import HighFashionPage from './HighFashionPage';

const YOHJI = {
  collection_id: '1234',
  url: 'https://example.test/show/1234',
  season_url: 'https://example.test/season/fw1999',
  designer: 'Yohji Yamamoto',
  designer_name: 'Yohji Yamamoto',
  year: '1999',
  season: 'Fall / Winter',
  gender: 'Women',
  subtitle: 'Runway Collection — Paris',
};

const RAF = {
  collection_id: '5678',
  url: 'https://example.test/show/5678',
  season_url: 'https://example.test/season/fw2001',
  designer: 'Raf Simons',
  designer_name: 'Raf Simons',
  year: '2001',
  season: 'Fall / Winter',
  gender: 'Women',
  subtitle: 'Runway Collection — Paris',
};

const CATALOGUE = [YOHJI, RAF];

jest.mock('../../shared/api', () => ({
  FashionArchiveAPI: {
    getSeasons: jest.fn(),
    getIndexStatus: jest.fn(),
    getDesigners: jest.fn(),
    getRecents: jest.fn(),
    getFavourites: jest.fn(),
    getFavouriteKeys: jest.fn(),
    getFavouritesPage: jest.fn(),
    searchShows: jest.fn(),
    browseCatalog: jest.fn(),
    streamCollectionImages: jest.fn(),
    streamCatalog: jest.fn(),
    streamDesignerCollections: jest.fn(),
    downloadVideo: jest.fn(),
    addFavourite: jest.fn(),
    removeFavourite: jest.fn(),
    addShowFavourite: jest.fn(),
    removeShowFavourite: jest.fn(),
    addViewFavourite: jest.fn(),
    removeViewFavourite: jest.fn(),
    getImageUrl: (p) => `/images/${p}`,
  },
  AlbumsAPI: {
    getAlbums: jest.fn(),
    getAlbum: jest.fn(),
    createAlbum: jest.fn(),
    addSavedToAlbum: jest.fn(),
    addLookToAlbum: jest.fn(),
    addShowToAlbum: jest.fn(),
    addViewToAlbum: jest.fn(),
    removeFromAlbum: jest.fn(),
  },
}));

// eslint-disable-next-line import/first
const { FashionArchiveAPI: API, AlbumsAPI } = require('../../shared/api');

const streams = new Map();

const partial = (id, delivered, promised) => ({ onMeta, onImage }) => {
  if (onMeta) onMeta({ count: promised });
  for (let i = 0; i < delivered; i += 1) {
    if (onImage) {
      onImage({ index: i, path: `shows/${id}/look-${String(i + 1).padStart(2, '0')}.jpg` });
    }
  }
  return {};
};

const silent = () => new Promise(() => {});

if (!Element.prototype.scrollTo) Element.prototype.scrollTo = () => {};

// The shelf, as GET /api/albums sends it.
const SHELF = [
  { id: 7, name: 'Resort', item_count: 4, cover_image_path: null,
    layout_mode: 'grid', sort_by: 'added' },
  { id: 9, name: 'Tailoring', item_count: 0, cover_image_path: null,
    layout_mode: 'grid', sort_by: 'added' },
];

// What POST /api/albums/<id>/items answers. `saved: true` is the half this
// whole file is about: the server saved the favourite as part of filing it,
// so there is no second request for the client to make and the star has to
// light off this one answer.
const FILED = {
  ok: true, status: 201, success: true,
  favourite_id: 555, saved: true, added: true, message: 'Added to album',
};

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState({}, '', '/');
  jest.clearAllMocks();

  streams.clear();
  streams.set('1234', partial('1234', 2, 5));
  streams.set('5678', silent);

  API.getSeasons.mockResolvedValue([]);
  API.getIndexStatus.mockResolvedValue({ shows: 55700 });
  API.getDesigners.mockResolvedValue([]);
  API.getRecents.mockResolvedValue([]);
  API.getFavourites.mockResolvedValue([]);
  // The star reads the KEYS, whole; the rows come a page at a time and the
  // archive page draws none of them. Both are seeded so a suite that sees a
  // dark star is seeing the page's own bug and not a missing mock.
  API.getFavouriteKeys.mockResolvedValue([]);
  API.getFavouritesPage.mockResolvedValue(
    { favourites: [], total: 0, hasMore: false, nextCursor: null });
  API.searchShows.mockResolvedValue({ success: true, shows: [], total: 0 });
  API.downloadVideo.mockResolvedValue(null);
  API.addFavourite.mockResolvedValue({});
  API.removeFavourite.mockResolvedValue({});
  API.addShowFavourite.mockResolvedValue({});
  API.removeShowFavourite.mockResolvedValue({});
  API.addViewFavourite.mockResolvedValue({});
  API.removeViewFavourite.mockResolvedValue({});
  API.streamCatalog.mockResolvedValue({ nextPage: 0, hasMore: false });
  API.streamDesignerCollections.mockResolvedValue({});

  AlbumsAPI.getAlbums.mockResolvedValue(SHELF);
  AlbumsAPI.createAlbum.mockResolvedValue({
    ok: true, status: 201, success: true,
    album: { id: 11, name: 'Archive', layout_mode: 'grid', sort_by: 'added' },
  });
  AlbumsAPI.addLookToAlbum.mockResolvedValue(FILED);
  AlbumsAPI.addShowToAlbum.mockResolvedValue(FILED);
  AlbumsAPI.addSavedToAlbum.mockResolvedValue(FILED);

  API.browseCatalog.mockImplementation(async (filters, options = {}) => {
    if (options.collectionId) {
      return { success: true,
               collections: CATALOGUE.filter(c => c.collection_id === options.collectionId) };
    }
    return { success: true, collections: CATALOGUE, hasMore: false,
             total: CATALOGUE.length, facets: null };
  });

  API.streamCollectionImages.mockImplementation(async (url, handlers = {}) => {
    const id = url.split('/').pop();
    const plan = streams.get(id);
    if (!plan) return {};
    return plan(handlers);
  });
});

const realThumbs = () => document.querySelectorAll('.hf2-thumb:not(.hf2-thumb-ghost)');
const selectedRow = () => {
  const row = document.querySelector('.hf2-collection-item.selected');
  return row && row.querySelector('.name').textContent;
};
const lookStar = (n) => screen.getByRole('button', { name: `Save look ${n}` });
const rowStar = (designer) =>
  screen.getByRole('button', { name: `Save this show — ${designer}` });

const renderPage = async () => {
  render(<HighFashionPage currentUser={{ email: 'test@example.test' }} />);
  await screen.findByText('Yohji Yamamoto');
  // The shelf has landed, so the picker has something to list.
  await waitFor(() => expect(AlbumsAPI.getAlbums).toHaveBeenCalled());
};

const openYohji = async () => {
  fireEvent.click(screen.getByText('Yohji Yamamoto'));
  await waitFor(() => expect(realThumbs()).toHaveLength(2));
};

const askForRaf = async () => {
  fireEvent.click(screen.getByText('Raf Simons'));
  await waitFor(() => expect(selectedRow()).toBe('Raf Simons'));
};

// Open the picker from the control beside the star.
const openPicker = async () => {
  fireEvent.click(screen.getByRole('button', { name: 'Add to album' }));
  await screen.findByRole('dialog');
};

const albumButton = (name) => Array.from(document.querySelectorAll('.alp-album'))
  .find(node => node.querySelector('.alp-album-name').textContent === name);

// ── The wiring ────────────────────────────────────────────────────────────

test('a look put in an album is starred at once, and is not saved twice', async () => {
  await renderPage();
  await openYohji();

  // Nothing is saved yet, so the star over the photograph is dark.
  expect(lookStar(1)).toHaveAttribute('aria-pressed', 'false');

  await openPicker();
  fireEvent.click(albumButton('Resort'));

  await waitFor(() => expect(AlbumsAPI.addLookToAlbum).toHaveBeenCalled());
  const [albumId, season, collection, look] = AlbumsAPI.addLookToAlbum.mock.calls[0];
  expect(albumId).toBe(7);
  expect(collection.url).toBe(YOHJI.url);
  expect(season.url).toBe(YOHJI.season_url);
  expect(look.number).toBe(1);

  // THE ASSERTION. The star is lit now — not after a reload, not after the
  // list the star reads is fetched again. `getFavouriteKeys` is that list, and
  // it has been called exactly once, on mount, so nothing has re-read it since
  // the add.
  await waitFor(() => expect(lookStar(1)).toHaveAttribute('aria-pressed', 'true'));
  expect(API.getFavouriteKeys).toHaveBeenCalledTimes(1);

  // And the save was the album endpoint's, inside its own transaction. A
  // separate addFavourite here would be a second copy of the same look — the
  // exact bug the collaborator exists to avoid having to risk.
  expect(API.addFavourite).not.toHaveBeenCalled();
});

test('the whole show can go in instead, and its row star lights', async () => {
  await renderPage();
  await openYohji();

  expect(rowStar('Yohji Yamamoto')).toHaveAttribute('aria-pressed', 'false');

  await openPicker();
  fireEvent.click(screen.getByRole('button', { name: 'Whole show' }));
  fireEvent.click(albumButton('Resort'));

  await waitFor(() => expect(AlbumsAPI.addShowToAlbum).toHaveBeenCalled());
  const [albumId, season, collection] = AlbumsAPI.addShowToAlbum.mock.calls[0];
  expect(albumId).toBe(7);
  expect(collection.url).toBe(YOHJI.url);
  expect(season.url).toBe(YOHJI.season_url);

  // The show's own star, lit off the same one answer.
  await waitFor(() => expect(rowStar('Yohji Yamamoto')).toHaveAttribute('aria-pressed', 'true'));
  // A saved show is not a saved look, so the look star is untouched.
  expect(lookStar(1)).toHaveAttribute('aria-pressed', 'false');
  expect(API.addShowFavourite).not.toHaveBeenCalled();
  expect(AlbumsAPI.addLookToAlbum).not.toHaveBeenCalled();
});

test('an album made from here is filled in the same press', async () => {
  await renderPage();
  await openYohji();

  await openPicker();
  fireEvent.click(screen.getByRole('button', { name: 'New album' }));
  fireEvent.change(screen.getByLabelText('New album name'), { target: { value: 'Archive' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create and add' }));

  await waitFor(() => expect(AlbumsAPI.createAlbum).toHaveBeenCalledWith('Archive', {}));
  // The id is the server's, and the add goes to the one it minted.
  await waitFor(() => expect(AlbumsAPI.addLookToAlbum).toHaveBeenCalled());
  expect(AlbumsAPI.addLookToAlbum.mock.calls[0][0]).toBe(11);
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});

// ── The stale window ──────────────────────────────────────────────────────

test('a look filed while the next show loads goes under the show on screen', async () => {
  await renderPage();
  await openYohji();
  await askForRaf();

  await openPicker();
  fireEvent.click(albumButton('Resort'));

  await waitFor(() => expect(AlbumsAPI.addLookToAlbum).toHaveBeenCalled());
  const [, season, collection, look] = AlbumsAPI.addLookToAlbum.mock.calls[0];
  // Yohji's, because Yohji's photographs are what the reader is looking at.
  // Reading the target off `selectedCollection` files the photograph in front
  // of them under Raf Simons, in an album, permanently.
  expect(collection.url).toBe(YOHJI.url);
  expect(season.url).toBe(YOHJI.season_url);
  expect(look.number).toBe(1);
});

// ── The star stays a star ─────────────────────────────────────────────────

test('the star saves and asks nothing — no album, no panel, no menu', async () => {
  await renderPage();
  await openYohji();

  fireEvent.click(lookStar(1));

  await waitFor(() => expect(API.addFavourite).toHaveBeenCalled());
  // No question was asked and no album was written. One click, one saved
  // look. The spec is explicit about this and it is the reason the album
  // control beside it is a separate, labelled thing.
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(AlbumsAPI.addLookToAlbum).not.toHaveBeenCalled();
  expect(AlbumsAPI.addSavedToAlbum).not.toHaveBeenCalled();
  expect(AlbumsAPI.addShowToAlbum).not.toHaveBeenCalled();
});

test('a row star saves the show and asks nothing either', async () => {
  await renderPage();
  await openYohji();

  fireEvent.click(rowStar('Raf Simons'));

  await waitFor(() => expect(API.addShowFavourite).toHaveBeenCalled());
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(AlbumsAPI.addShowToAlbum).not.toHaveBeenCalled();
});
