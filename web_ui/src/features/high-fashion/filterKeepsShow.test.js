// Changing a filter must not close the show you are reading.
//
// This is a render test rather than a unit test of a decision function, and
// that is deliberate. The decision itself — "does this act on the list close
// the open show?" — resolves to the same answer at all four sites (no), so a
// pure function holding it would be `() => false` and a test of it would
// restate its own body. The thing worth pinning is the behaviour: four
// pieces of state that used to be reset together now come apart, and the two
// address-bar effects have to agree with the result. Only a render exercises
// that.
//
// The URL half of it — that a show still in state still gets written to the
// address bar, filters and all — is also pinned at the pure level in
// showUrl.test.js, where it is a composition of urlWrite and buildRoute.
import React from 'react';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';

import HighFashionPage from './HighFashionPage';

// Two shows, and a catalogue where the second gender filter excludes the
// first of them. That is the awkward case on purpose: after the filter
// change the open show is not in the list any more.
const YOHJI = {
  collection_id: '1234',
  url: 'https://example.test/show/1234',
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
  designer: 'Raf Simons',
  designer_name: 'Raf Simons',
  year: '2001',
  season: 'Fall / Winter',
  gender: 'Men',
  subtitle: 'Runway Collection — Paris',
};

const CATALOGUE = [YOHJI, RAF];

const rowsFor = (filters) => {
  let rows = CATALOGUE;
  if (filters && filters.gender) rows = rows.filter(c => c.gender === filters.gender);
  if (filters && filters.designer) rows = rows.filter(c => c.designer === filters.designer);
  return rows;
};

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
    getImageUrl: (path) => `/images/${path}`,
  },
}));

// eslint-disable-next-line import/first
const { FashionArchiveAPI: API } = require('../../shared/api');

const path = () => window.location.pathname + window.location.search;

beforeEach(() => {
  window.localStorage.clear();
  // The page loads the YouTube iframe API by inserting a <script> before the
  // first one in the document. A jsdom document has none, so it needs one to
  // insert before. (Worth noting rather than fixing here: a real page with no
  // script tag at all would hit the same null.)
  if (!document.getElementsByTagName('script')[0]) {
    document.head.appendChild(document.createElement('script'));
  }
  window.history.replaceState({}, '', '/');

  API.getSeasons.mockResolvedValue([]);
  // Indexed: the one query path, which is the path the app actually runs.
  API.getIndexStatus.mockResolvedValue({ shows: 55700 });
  API.getDesigners.mockResolvedValue([{ id: 42, name: 'Raf Simons', entries: 31 }]);
  API.getRecents.mockResolvedValue([]);
  API.getFavourites.mockResolvedValue([]);
  API.searchShows.mockResolvedValue({ success: true, shows: [], total: 0 });
  API.downloadVideo.mockResolvedValue(null);
  API.addFavourite.mockResolvedValue({});
  API.removeFavourite.mockResolvedValue({});
  API.streamCatalog.mockResolvedValue({ nextPage: 0, hasMore: false });
  API.streamDesignerCollections.mockResolvedValue({});

  API.browseCatalog.mockImplementation(async (filters, options = {}) => {
    // The deep-link lookup asks for one row by id; everything else is the
    // list under the current filters.
    if (options.collectionId) {
      return { success: true,
               collections: CATALOGUE.filter(c => c.collection_id === options.collectionId) };
    }
    const collections = rowsFor(filters);
    return { success: true, collections, hasMore: false, total: collections.length,
             facets: null };
  });

  API.streamCollectionImages.mockImplementation(async (url, { onMeta, onImage } = {}) => {
    const id = url.split('/').pop();
    if (onMeta) onMeta({ count: 2 });
    if (onImage) {
      onImage({ index: 0, path: `shows/${id}/look-01.jpg` });
      onImage({ index: 1, path: `shows/${id}/look-02.jpg` });
    }
    return {};
  });
});

const renderPage = async () => {
  render(<HighFashionPage currentUser={{ email: 'test@example.test' }} />);
  // The list has arrived and the archive is on screen.
  await screen.findByText('Yohji Yamamoto');
};

const openYohji = async () => {
  fireEvent.click(screen.getByText('Yohji Yamamoto'));
  // The status bar only names a designer when a show is open, and the look
  // readout ("01 / 2") only appears once images have landed.
  await waitFor(() => expect(lookReadout()).toBe('01 / 2'));
  expect(statusPath()).toContain('Yohji Yamamoto');
  expect(path()).toBe('/hf/yohji-yamamoto-runway-collection-paris/1234/1');
};

const statusPath = () => document.querySelector('.hf2-status-path').textContent;
// "01 / 2" once the show's two looks have landed, empty before that.
const lookReadout = () => document.querySelector('.hf2-status-look').textContent;
const selectedRow = () => document.querySelector('.hf2-collection-item.selected');
const listedDesigners = () => Array.from(
  document.querySelectorAll('.hf2-collection-item .name')).map(n => n.textContent);

test('changing a filter leaves the open show open', async () => {
  await renderPage();
  await openYohji();

  // Narrow the list to menswear — which the open womenswear show is not in.
  fireEvent.click(screen.getByRole('button', { name: 'Men' }));
  await screen.findByText('Raf Simons');

  // Still open: the status bar still names it, and the viewer still has its
  // two looks.
  expect(statusPath()).toContain('Yohji Yamamoto');
  // Its two looks are still in the viewer: images and expectedLookCount
  // belong to the show, not to the list.
  expect(lookReadout()).toBe('01 / 2');
  expect(screen.getAllByAltText('Look 1').length).toBeGreaterThan(0);

  // And the URL still names it, now carrying the filter.
  expect(path()).toBe(
    '/hf/yohji-yamamoto-runway-collection-paris/1234/1?gender=Men');
});

test('a show that the filters exclude is simply not highlighted', async () => {
  // ShowList marks the selected row by comparing urls against the rows it is
  // rendering, so a selection that is not among them highlights nothing.
  // That is the whole of its handling, and it is the right one.
  await renderPage();
  await openYohji();
  expect(selectedRow()).not.toBeNull();

  fireEvent.click(screen.getByRole('button', { name: 'Men' }));
  await screen.findByText('Raf Simons');

  expect(listedDesigners()).toEqual(['Raf Simons']);   // gone from the list
  expect(selectedRow()).toBeNull();                    // nothing highlighted
  expect(statusPath()).toContain('Yohji Yamamoto');    // still open
});

test('clearing the filters leaves the open show open', async () => {
  await renderPage();
  await openYohji();

  // Gender is not a counted filter — it is never empty — so narrow on the
  // brand letter, which is, to get a live "Clear 1 filter" button.
  fireEvent.change(screen.getByDisplayValue('A–Z'), { target: { value: 'R' } });
  await waitFor(() => expect(path()).toContain('letter=R'));

  fireEvent.click(screen.getByRole('button', { name: 'Clear 1 filter' }));

  await waitFor(() => expect(path()).not.toContain('letter='));
  expect(statusPath()).toContain('Yohji Yamamoto');
  expect(lookReadout()).toBe('01 / 2');
  expect(path()).toBe('/hf/yohji-yamamoto-runway-collection-paris/1234/1');
});

test('selecting a different show is what replaces it', async () => {
  await renderPage();
  await openYohji();

  fireEvent.click(screen.getByText('Raf Simons'));
  await waitFor(() => expect(statusPath()).toContain('Raf Simons'));

  expect(statusPath()).not.toContain('Yohji Yamamoto');
  expect(path()).toBe('/hf/raf-simons-runway-collection-paris/5678/1');
});

test('going back out of the viewer is what closes it', async () => {
  // The other way a show closes, and the reason the filter sites can stop
  // closing it without leaving the viewer unclosable.
  await renderPage();
  await openYohji();

  await act(async () => {
    window.history.replaceState({}, '', '/');
    window.dispatchEvent(new PopStateEvent('popstate'));
  });

  await waitFor(() => expect(statusPath()).not.toContain('Yohji Yamamoto'));
});

// ── Designer mode ─────────────────────────────────────────────────────────
//
// The arguable pair. Opening one designer's history and coming back out of
// it sound like navigation, but with the archive held locally a designer is
// an argument to the same catalogue query as the year and the city, so they
// move the same window the filters move. They are treated as filter changes,
// and these pin that.

const openRafsHistory = async () => {
  const box = document.querySelector('.hf2-search-input');
  fireEvent.focus(box);
  fireEvent.change(box, { target: { value: 'raf' } });
  const option = await screen.findByText('Raf Simons', { selector: '.label' });
  fireEvent.click(option.closest('button'));
  await waitFor(() => expect(document.querySelector('.hf2-designer-name')).not.toBeNull());
};

test("opening a designer's history leaves the open show open", async () => {
  await renderPage();
  await openYohji();

  await openRafsHistory();
  await waitFor(() => expect(listedDesigners()).toEqual(['Raf Simons']));

  expect(statusPath()).toContain('Yohji Yamamoto');
  expect(lookReadout()).toBe('01 / 2');
  expect(path()).toBe('/hf/yohji-yamamoto-runway-collection-paris/1234/1');
});

test('coming back out to the archive leaves it open too', async () => {
  await renderPage();
  await openYohji();
  await openRafsHistory();

  fireEvent.click(screen.getByRole('button', { name: '← Archive' }));
  await waitFor(() => expect(document.querySelector('.hf2-designer-name')).toBeNull());

  expect(statusPath()).toContain('Yohji Yamamoto');
  expect(lookReadout()).toBe('01 / 2');
  // exitDesigner puts gender back to a real choice, and that rides along.
  expect(path()).toBe(
    '/hf/yohji-yamamoto-runway-collection-paris/1234/1?gender=Women');
});
