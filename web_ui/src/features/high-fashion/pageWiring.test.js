// The wiring between HighFashionPage and the hooks and components it drives.
//
// Every prop on this page is a line of JSX, and until this file existed a
// reviewer could rewrite ten of them — hand `selectedCollection` where
// `imagesCollection` belongs, hard-code `isStale` to false, drop a count —
// and the whole suite stayed green. The unit tests below them are all
// honest: useFavourites is tested against the collection it is given,
// StatusBar against the props it is handed. What nothing tested was which
// values the page hands them, and that is where the bug lives.
//
// The state these pin is the STALE WINDOW: another show has been asked for
// and its first photograph has not landed, so the pane still holds the
// previous show. Almost every wiring mistake on this page is invisible
// outside that window, because outside it `selectedCollection` and
// `imagesCollection` are the same object (see useCollectionImages).
// filterKeepsShow.test.js cannot reach it — its stream delivers everything
// synchronously — so the harness here is the same one with a stream per
// show, one of which never answers.
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

import HighFashionPage from './HighFashionPage';

// Two shows with different season urls as well as different collection urls.
// A favourite is written as (season url, collection url, look number), all
// three positional — so a mix-up that took the season from one show and the
// collection from the other would still name a row, and both halves have to
// be asserted.
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
}));

// eslint-disable-next-line import/first
const { FashionArchiveAPI: API } = require('../../shared/api');

// How each show's stream behaves, by collection id. A stream is not a
// function that returns a list here — it is a sequence of events over time,
// and which of them have happened is the whole of what `isStale`,
// `streamComplete` and `expectedCount` mean.
const streams = new Map();

// Yohji: meta says five looks, two photographs land, and the stream then
// goes quiet without ever saying it is done. That is a real mid-flight show
// — the three that have not landed are the ghost slots — and it is the state
// the counter and the strip are specified against.
const partial = (id, delivered, promised) => ({ onMeta, onImage }) => {
  if (onMeta) onMeta({ count: promised });
  for (let i = 0; i < delivered; i += 1) {
    if (onImage) {
      onImage({ index: i, path: `shows/${id}/look-${String(i + 1).padStart(2, '0')}.jpg` });
    }
  }
  return {};
};

// Raf: asked for, and nothing comes back. No meta, no photograph, no done,
// no failure. This is the stale window held open — the state a real reader
// sits in for a second or two on every click, and indefinitely on a slow
// connection.
const silent = () => new Promise(() => {});

// jsdom implements Element.scrollTo on window but not on elements, and the
// page centres the active thumbnail by calling it on the strip whenever the
// look changes. Every browser this ships to has it; only the test document
// does not, so it is filled in here rather than guarded in the page.
if (!Element.prototype.scrollTo) Element.prototype.scrollTo = () => {};

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

const statusPath = () => document.querySelector('.hf2-status-path').textContent;
const statusLook = () => document.querySelector('.hf2-status-look').textContent;
const selectedRow = () => {
  const row = document.querySelector('.hf2-collection-item.selected');
  return row && row.querySelector('.name').textContent;
};
const realThumbs = () => document.querySelectorAll('.hf2-thumb:not(.hf2-thumb-ghost)');
const ghosts = () => document.querySelectorAll('.hf2-thumb-ghost');
const activeThumbIndex = () => Array.from(document.querySelectorAll('.hf2-thumb'))
  .findIndex(t => t.classList.contains('active'));

const renderPage = async () => {
  render(<HighFashionPage currentUser={{ email: 'test@example.test' }} />);
  await screen.findByText('Yohji Yamamoto');
};

// Open Yohji and wait for its two photographs to be on screen.
const openYohji = async () => {
  fireEvent.click(screen.getByText('Yohji Yamamoto'));
  await waitFor(() => expect(realThumbs()).toHaveLength(2));
};

// Ask for Raf, whose stream never answers, and wait only for the click to
// have been taken — the list's own highlight, which no prop under test here
// feeds. Everything else on screen is still Yohji's, and that is the point.
const askForRaf = async () => {
  fireEvent.click(screen.getByText('Raf Simons'));
  await waitFor(() => expect(selectedRow()).toBe('Raf Simons'));
};

// ── The stale window ──────────────────────────────────────────────────────

test('a look kept while the next show loads is filed under the show on screen', async () => {
  // The data-corruption bug, end to end. Star a look of the show you are
  // reading while another one is being fetched, and it must be filed under
  // the show you are reading. Keying the write on the selected show instead
  // files Yohji's look 1 under Raf Simons — and removeFavourite is
  // positional, so the row it later deletes is a real row that exists.
  await renderPage();
  await openYohji();
  await askForRaf();

  fireEvent.keyDown(document.body, { key: 'f' });
  await waitFor(() => expect(API.addFavourite).toHaveBeenCalled());

  const [season, collection, look] = API.addFavourite.mock.calls[0];
  expect(collection.url).toBe(YOHJI.url);
  expect(collection.designer).toBe('Yohji Yamamoto');
  expect(season.url).toBe(YOHJI.season_url);
  // The look number came off the photograph on screen, so it belongs to the
  // same show as the urls beside it.
  expect(look.number).toBe(1);
});

test('the status bar names the show on screen and refuses to count', async () => {
  await renderPage();
  await openYohji();
  expect(statusLook()).toBe('01 / 5 arriving');

  await askForRaf();

  // The name follows the photographs, not the click.
  expect(statusPath()).toContain('Yohji Yamamoto');
  expect(statusPath()).not.toContain('Raf Simons');
  // And no numbers at all: Raf's total has already arrived in some other
  // universe and Yohji's position is the one on screen, so printing them
  // together would be "01 / 38" with the two halves from different shows.
  expect(statusLook()).toBe('loading');
});

test('the viewer marks the looks on screen as not the ones asked for', async () => {
  await renderPage();
  await openYohji();
  expect(document.querySelector('.hf2-main.stale')).toBeNull();

  await askForRaf();

  // Dimmed, not emptied. Without the flag the previous show sits there
  // undimmed and indistinguishable from the show that was clicked.
  expect(document.querySelector('.hf2-main.stale')).not.toBeNull();
});

test('the look being read does not jump while the next show loads', async () => {
  await renderPage();
  await openYohji();

  fireEvent.keyDown(document.body, { key: 'ArrowRight' });
  await waitFor(() => expect(activeThumbIndex()).toBe(1));

  await askForRaf();

  // Still look 2 of the show still on screen. Resetting on the selection
  // instead of on the photographs yanks the reader back to look 1 of a show
  // they are still reading, seconds before it is replaced anyway.
  expect(activeThumbIndex()).toBe(1);
});

// ── Mid-flight, before any of that ────────────────────────────────────────

test('the strip holds a slot for every look the stream has promised', async () => {
  await renderPage();
  await openYohji();

  // Two of five landed, so three empty slots: the strip is its final width
  // from the first photograph. Hand the strip a zero count and the show
  // appears to be two looks long until it suddenly is not.
  expect(realThumbs()).toHaveLength(2);
  expect(ghosts()).toHaveLength(3);
});

// ── The stars, where the page joins them up ───────────────────────────────
//
// The four stars are tested as components in saveStars.test.js. What is
// pinned here is the join: which of this page's values each one is handed.
// A row star wired to the show on screen rather than to its own row, or a
// view star wired to a stale filter object, is invisible to a component test
// and is exactly the kind of prop mistake this file exists for.

const rowStar = (designer) =>
  screen.getByRole('button', { name: `Save this show — ${designer}` });

test('a row star keeps that row, and does not open it', async () => {
  await renderPage();
  await openYohji();

  // Raf's row, while Yohji is the show on screen and Raf's own stream will
  // never answer. Pressing the star must save RAF — the row it is on — and
  // must not open him, which is the thing pressing the row does.
  fireEvent.click(rowStar('Raf Simons'));
  await waitFor(() => expect(API.addShowFavourite).toHaveBeenCalled());

  const [season, collection] = API.addShowFavourite.mock.calls[0];
  expect(collection.url).toBe(RAF.url);
  expect(collection.designer).toBe('Raf Simons');
  expect(season.url).toBe(RAF.season_url);

  // The show on screen is still Yohji and the list's own highlight never
  // moved: the click stopped at the star.
  expect(selectedRow()).toBe('Yohji Yamamoto');
  expect(statusPath()).toContain('Yohji Yamamoto');
  // And no look was written. A saved show is not a saved look.
  expect(API.addFavourite).not.toHaveBeenCalled();
});

test('a saved show lights its own row and nobody else', async () => {
  API.getFavourites.mockResolvedValue([{
    kind: 'show',
    season: { url: YOHJI.season_url },
    collection: { url: YOHJI.url, designer: 'Yohji Yamamoto' },
  }]);
  await renderPage();

  await waitFor(() => expect(rowStar('Yohji Yamamoto'))
    .toHaveAttribute('aria-pressed', 'true'));
  expect(rowStar('Raf Simons')).toHaveAttribute('aria-pressed', 'false');

  // The show is saved; its looks are not.
  await openYohji();
  expect(screen.getByRole('button', { name: 'Save look 1' }))
    .toHaveAttribute('aria-pressed', 'false');
});

test('the view star keeps the filters that are actually set', async () => {
  await renderPage();
  const star = screen.getByRole('button', { name: 'Save this view' });
  // Nothing narrowed yet, so there is no view to keep.
  expect(star).toBeDisabled();

  fireEvent.change(screen.getByRole('combobox', { name: 'Brand' }), { target: { value: 'A' } });
  await waitFor(() => expect(star).not.toBeDisabled());

  fireEvent.click(star);
  await waitFor(() => expect(API.addViewFavourite).toHaveBeenCalled());
  const [filters] = API.addViewFavourite.mock.calls[0];
  expect(filters).toEqual(expect.objectContaining({ letter: 'A' }));
});
