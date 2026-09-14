// The album grid: Finder's icon view over the three kinds an album holds.
//
// The fake server below is a fake of the SERVER's ordering, not of the
// page's. `SORT_ORDERS` in backend/userdata/albums.py is restated here as
// three comparators — and deliberately not imported from AlbumGrid, because
// the whole point of the season test is that the page's order and the
// server's disagree, and a fake that sorted with the page's function could
// not fail when the page stopped re-ordering.
import React from 'react';
import { render, screen, waitFor, fireEvent, within, act } from '@testing-library/react';

jest.mock('../../shared/api', () => ({
  FashionArchiveAPI: {
    getMe: jest.fn(),
    logout: jest.fn(),
    // Not called by this page, and the test below says so out loud: taking a
    // tile out of an album must never reach the endpoint that unsaves.
    removeFavourite: jest.fn(),
    removeShowFavourite: jest.fn(),
    removeViewFavourite: jest.fn(),
    getImageUrl: (p) => `/images/${p}`,
  },
  AlbumsAPI: {
    getAlbums: jest.fn(),
    getAlbum: jest.fn(),
    setAlbumOptions: jest.fn(),
    deleteAlbum: jest.fn(),
    removeFromAlbum: jest.fn(),
  },
}));

// App's other three pages are stubs: the route test below is about which
// component App draws for /library/albums/<id> and where Back lands, and a
// real archive page would bring a catalogue and three streams to answer a
// question none of them is part of.
jest.mock('../high-fashion/HighFashionPage', () => ({
  __esModule: true,
  default: () => require('react').createElement('div', null, 'archive page'),
}));
jest.mock('./LibraryPage', () => ({
  __esModule: true,
  default: () => require('react').createElement('div', null, 'library page'),
}));
jest.mock('../brands/BrandsPage', () => ({
  __esModule: true,
  default: () => require('react').createElement('div', null, 'brands page'),
}));
jest.mock('../auth/AuthPanel', () => ({
  __esModule: true,
  default: () => require('react').createElement('div', null, 'sign in'),
}));

// eslint-disable-next-line import/first
import AlbumGrid, { orderItems, seasonKey } from './AlbumGrid';
// eslint-disable-next-line import/first
import App from '../../app/App';
// The page is handed `navigate`, so a navigation test checks the ROUTE it was
// asked for. `buildRoute` is what the real navigate puts through to history,
// so the URLs below are the URLs the address bar would have held.
// eslint-disable-next-line import/first
import { buildRoute } from '../../app/routes';

// eslint-disable-next-line import/first
const { AlbumsAPI, FashionArchiveAPI: API } = require('../../shared/api');

// ── The album's contents ─────────────────────────────────────────────────

const LOOK_A = {
  id: 101,
  kind: 'look',
  season: { name: 'Fall / Winter 1999', url: 'https://fv.test/season/fw1999' },
  collection: {
    designer: 'Yohji Yamamoto Ready To Wear Fall / Winter 1999',
    url: 'https://fv.test/collection_images.php?id=1234&list=all',
    id: '1234',
  },
  look: { number: 7, total: 40 },
  view: { name: '', filters: {} },
  image_path: 'shows/1234/look-07.jpg',
  date_added: '2026-09-01T10:00:00',
  sort_index: 0,
};

const SHOW_B = {
  id: 102,
  kind: 'show',
  season: { name: 'Spring / Summer 2020', url: 'https://fv.test/season/ss2020' },
  collection: {
    designer: 'Raf Simons Menswear Spring / Summer 2020',
    url: 'https://fv.test/collection_images.php?id=5678&list=all',
    id: '5678',
  },
  look: { number: null, total: null },
  view: { name: '', filters: {} },
  image_path: 'shows/5678/look-01.jpg',
  date_added: '2026-09-02T10:00:00',
  sort_index: 1024,
};

// A view carries no image path at all — there is no photograph of a set of
// filters — and that is the tile that must not draw a broken one.
const VIEW_C = {
  id: 103,
  kind: 'view',
  season: { name: '', url: '' },
  collection: { designer: '', url: '', id: null },
  look: { number: null, total: null },
  view: { name: 'Paris 2020', filters: { year: '2020', city: 'Paris' } },
  image_path: '',
  date_added: '2026-09-03T10:00:00',
  sort_index: 2048,
};

const LOOK_D = {
  id: 104,
  kind: 'look',
  season: { name: 'Cruise 2018', url: 'https://fv.test/season/cr2018' },
  collection: {
    designer: 'Comme des Garçons Ready To Wear Cruise 2018',
    url: 'https://fv.test/collection_images.php?id=9012&list=all',
    id: '9012',
  },
  look: { number: 3, total: 22 },
  view: { name: '', filters: {} },
  image_path: 'shows/9012/look-03.jpg',
  date_added: '2026-09-04T10:00:00',
  sort_index: 3072,
};

const ALL = [LOOK_A, SHOW_B, VIEW_C, LOOK_D];

// ── The fake server ──────────────────────────────────────────────────────

// backend/userdata/albums.py SORT_ORDERS, restated:
//   added     i.sort_index
//   designer  lower(f.collection_designer), i.sort_index
//   season    f.season_name, i.sort_index      <- ALPHABETICAL, by design
const SERVER_ORDER = {
  added: (a, b) => a.sort_index - b.sort_index,
  designer: (a, b) => (
    a.collection.designer.toLowerCase().localeCompare(b.collection.designer.toLowerCase())
    || a.sort_index - b.sort_index
  ),
  season: (a, b) => (
    a.season.name.localeCompare(b.season.name) || a.sort_index - b.sort_index
  ),
};

let albumRow;
let rows;

const serve = () => ({
  album: { ...albumRow },
  items: [...rows].sort(SERVER_ORDER[albumRow.sort_by]),
});

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState({}, '', '/library/albums/7');
  jest.clearAllMocks();

  albumRow = { id: 7, name: 'Resort', layout_mode: 'grid', sort_by: 'added' };
  rows = [...ALL];

  API.getMe.mockResolvedValue({ id: 1, username: 'reader' });
  API.logout.mockResolvedValue({});
  AlbumsAPI.getAlbums.mockImplementation(async () => [
    { ...albumRow, item_count: rows.length, cover_image_path: 'shows/1234/look-07.jpg' },
  ]);
  AlbumsAPI.getAlbum.mockImplementation(async () => serve());
  AlbumsAPI.setAlbumOptions.mockImplementation(async (id, opts) => {
    if (opts.sortBy !== undefined) albumRow.sort_by = opts.sortBy;
    return { ok: true, status: 200, success: true };
  });
  AlbumsAPI.removeFromAlbum.mockResolvedValue({ ok: true, status: 200, success: true });
  AlbumsAPI.deleteAlbum.mockResolvedValue({ ok: true, status: 200, success: true });
  navigate = jest.fn();
});

// The real address bar. Used by the route test at the foot of this file, which
// renders App and so exercises the wiring — App passing `navigate` down — that
// the spy below deliberately stands in for everywhere else.
const path = () => window.location.pathname + window.location.search;

// Where the page asked to go, as a URL. Not "navigate was called": a route
// assembled out of two different rows names a show that exists and opens it.
let navigate;
const wentTo = () => buildRoute(navigate.mock.calls[navigate.mock.calls.length - 1][0]);

const tiles = () => Array.from(document.querySelectorAll('.alb-tile'));
const names = () => Array.from(document.querySelectorAll('.alb-tile-name'))
  .map(n => n.textContent);
const subs = () => Array.from(document.querySelectorAll('.alb-tile-sub'))
  .map(n => n.textContent);

const openAlbum = async () => {
  render(
    <AlbumGrid
      currentPage="library"
      currentUser={{ username: 'reader' }}
      albumId="7"
      navigate={navigate}
    />,
  );
  await waitFor(() => expect(tiles().length).toBe(rows.length));
};

// ── A render test per kind of tile ───────────────────────────────────────

test('a look renders as its photograph, with a designer and its number under it', async () => {
  rows = [LOOK_A];
  await openAlbum();

  const [tile] = tiles();
  expect(tile).toHaveClass('alb-tile-look');
  const photo = tile.querySelector('img.alb-tile-photo');
  expect(photo).toHaveAttribute('src', '/images/shows/1234/look-07.jpg');
  expect(within(tile).getByText('Yohji Yamamoto')).toBeInTheDocument();
  expect(within(tile).getByText('07 · Fall / Winter 1999')).toBeInTheDocument();
  // A look is the unmarked kind. Tagging it too would leave the word doing
  // no work on the two kinds that need it.
  expect(tile.querySelector('.alb-tile-tag')).toBeNull();
});

test('a saved show renders as a show — its cover, tagged, not a look with no number', async () => {
  rows = [SHOW_B];
  await openAlbum();

  const [tile] = tiles();
  expect(tile).toHaveClass('alb-tile-show');
  expect(tile.querySelector('img.alb-tile-photo'))
    .toHaveAttribute('src', '/images/shows/5678/look-01.jpg');
  expect(tile.querySelector('.alb-tile-tag').textContent).toBe('Show');
  expect(within(tile).getByText('Raf Simons')).toBeInTheDocument();
  expect(within(tile).getByText('Spring / Summer 2020')).toBeInTheDocument();
  // The number a show does not have must not be drawn as an empty label.
  expect(subs()).not.toContain('');
});

test('a saved view renders as its filters, and writes no image element at all', async () => {
  rows = [VIEW_C];
  await openAlbum();

  const [tile] = tiles();
  expect(tile).toHaveClass('alb-tile-view');
  expect(tile.querySelector('.alb-tile-tag').textContent).toBe('View');
  // The filters themselves, labelled the way the archive's own facets are.
  expect(within(tile).getByText('Year')).toBeInTheDocument();
  expect(within(tile).getByText('2020')).toBeInTheDocument();
  expect(within(tile).getByText('City')).toBeInTheDocument();
  expect(within(tile).getByText('Paris')).toBeInTheDocument();
  expect(within(tile).getByText('Paris 2020')).toBeInTheDocument();
  expect(within(tile).getByText('2 filters')).toBeInTheDocument();
  // The whole of step 5: no <img>, so no src of '', no request for the page
  // itself, and no broken-image glyph where a photograph would be.
  expect(tile.querySelector('img')).toBeNull();
});

// ── The reserved box ─────────────────────────────────────────────────────

// Measured for real in headless Chrome against the built bundle — see the
// task report for the numbers. This is what keeps it true as the page
// changes: the box is the class, nothing sizes its own box, and no kind
// writes an <img> it has no src for.
test('every kind is the same box, and no kind draws an image it has not got', async () => {
  // A look whose photograph never reached storage: the case that would draw
  // a broken image if the <img> were unconditional.
  const LOOK_NO_IMAGE = { ...LOOK_A, id: 105, image_path: '', sort_index: 4096 };
  rows = [LOOK_A, SHOW_B, VIEW_C, LOOK_NO_IMAGE];
  await openAlbum();

  const boxes = Array.from(document.querySelectorAll('.alb-tile-box'));
  expect(boxes).toHaveLength(4);
  // Nothing sizes its own box. Every rule about this rectangle is in one
  // class in one stylesheet, so the four boxes cannot disagree.
  boxes.forEach(box => expect(box.getAttribute('style')).toBeNull());

  const images = Array.from(document.querySelectorAll('.alb-tile img'));
  expect(images).toHaveLength(2);                       // A and B, and only those
  images.forEach(img => {
    expect(img).toHaveClass('alb-tile-photo');
    expect(img.getAttribute('style')).toBeNull();
    expect(img.getAttribute('src')).not.toBe('');
  });
});

// ── Sorting ──────────────────────────────────────────────────────────────

test('an album opens in the order it was stored in, not in the order it arrived', async () => {
  albumRow.sort_by = 'designer';
  await openAlbum();

  expect(screen.getByLabelText('Sort by')).toHaveValue('designer');
  expect(names()).toEqual(['Paris 2020', 'Comme des Garçons', 'Raf Simons', 'Yohji Yamamoto']);
});

test('the sort control changes the order and stores the choice on the album', async () => {
  await openAlbum();
  expect(names()).toEqual(['Yohji Yamamoto', 'Raf Simons', 'Paris 2020', 'Comme des Garçons']);

  fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'designer' } });

  await waitFor(() => expect(names())
    .toEqual(['Paris 2020', 'Comme des Garçons', 'Raf Simons', 'Yohji Yamamoto']));
  expect(AlbumsAPI.setAlbumOptions).toHaveBeenCalledWith(7, { sortBy: 'designer' });
});

test('the stored choice is what the album opens with next time', async () => {
  const first = await (async () => {
    const r = render(
      <AlbumGrid currentPage="library" currentUser={{ username: 'reader' }} albumId="7" />);
    await waitFor(() => expect(tiles().length).toBe(rows.length));
    return r;
  })();

  fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'designer' } });
  await waitFor(() => expect(AlbumsAPI.setAlbumOptions).toHaveBeenCalled());
  first.unmount();

  // A second visit, with nothing carried across in the client: the order
  // comes back off the album row the server kept.
  await openAlbum();
  expect(screen.getByLabelText('Sort by')).toHaveValue('designer');
  expect(names()).toEqual(['Paris 2020', 'Comme des Garçons', 'Raf Simons', 'Yohji Yamamoto']);
});

// The one the server cannot do. Its 'season' is ORDER BY season_name, which
// is alphabetical over a display string, so it answers Cruise 2018 before
// Fall / Winter 1999 before Spring / Summer 2020.
test('sorting by season is chronological, not alphabetical', async () => {
  await openAlbum();
  fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'season' } });

  await waitFor(() => expect(names()).toEqual([
    'Yohji Yamamoto',       // Fall / Winter 1999
    'Comme des Garçons',    // Cruise 2018
    'Raf Simons',           // Spring / Summer 2020
    'Paris 2020',           // no season at all — last, in the server's order
  ]));
});

test('the season order is a total one, and the calendar runs inside a year', () => {
  expect(seasonKey('Prefall 2016')).toEqual({ year: 2016, rank: 3 });
  expect(seasonKey('Fall / Winter 2016')).toEqual({ year: 2016, rank: 4 });
  expect(seasonKey('Spring / Summer 2016')).toEqual({ year: 2016, rank: 2 });
  expect(seasonKey('Cruise 2016')).toEqual({ year: 2016, rank: 1 });
  // No year to stand on: a saved view, or a spelling from some other source.
  expect(seasonKey('')).toBeNull();
  expect(seasonKey('Autumn')).toBeNull();

  const row = (name, at) => ({ id: at, season: { name } });
  const one = row('Cruise 2016', 1);
  const two = row('Prefall 2016', 2);
  const three = row('Fall / Winter 2015', 3);
  const none = row('', 4);
  const alsoNone = row('Ancient', 5);

  expect(orderItems([none, two, alsoNone, one, three], 'season'))
    .toEqual([three, one, two, none, alsoNone]);
  // And the other two orders are the server's, untouched.
  expect(orderItems([none, two, one], 'added')).toEqual([none, two, one]);
  expect(orderItems([none, two, one], 'designer')).toEqual([none, two, one]);
});

// ── Selection, and opening ───────────────────────────────────────────────

test('clicking a tile selects it, and only it', async () => {
  await openAlbum();
  const [yohji, raf] = tiles();

  fireEvent.click(yohji);
  expect(yohji).toHaveClass('selected');
  expect(yohji).toHaveAttribute('aria-pressed', 'true');
  expect(raf).not.toHaveClass('selected');
  expect(document.querySelectorAll('.alb-tile.selected')).toHaveLength(1);

  fireEvent.click(raf);
  expect(raf).toHaveClass('selected');
  expect(yohji).not.toHaveClass('selected');
});

test('opening a look opens its show at that look', async () => {
  await openAlbum();
  fireEvent.doubleClick(tiles()[0]);
  // The whole route, not only the URL: `imageNumber` is what makes this the
  // look and not the show, and `slug` is decoration parseRoute never reads
  // back — a route carrying one row's slug and another's id opens the wrong
  // show and looks right in the address bar doing it.
  expect(navigate).toHaveBeenCalledWith({
    page: 'high-fashion',
    collectionId: '1234',
    imageNumber: 7,
    slug: 'yohji-yamamoto-fall-winter-1999',
  });
  expect(wentTo()).toBe('/hf/yohji-yamamoto-fall-winter-1999/1234/7');
});

test('opening a show opens the show, with no look number on it', async () => {
  await openAlbum();
  fireEvent.doubleClick(tiles()[1]);
  // No look number at all — a saved show opens at the top of the run.
  expect(navigate).toHaveBeenCalledWith({
    page: 'high-fashion',
    collectionId: '5678',
    imageNumber: null,
    slug: 'raf-simons-spring-summer-2020',
  });
  expect(wentTo()).toBe('/hf/raf-simons-spring-summer-2020/5678');
});

test('opening a view opens the archive with those filters applied', async () => {
  await openAlbum();
  fireEvent.doubleClick(tiles()[2]);
  expect(navigate).toHaveBeenCalledWith({
    page: 'high-fashion',
    filters: { year: '2020', city: 'Paris' },
  });
  expect(wentTo()).toBe('/?city=Paris&year=2020');
});

test('the second look opens its own show, not the first row show', async () => {
  await openAlbum();
  fireEvent.doubleClick(tiles()[3]);
  expect(wentTo()).toBe('/hf/comme-des-garcons-cruise-2018/9012/3');
});

// ── Empty, and gone ──────────────────────────────────────────────────────

test('an empty album says it is empty, and says what goes in one', async () => {
  rows = [];
  render(
    <AlbumGrid
      currentPage="library"
      currentUser={{ username: 'reader' }}
      albumId="7"
      navigate={navigate}
    />,
  );

  await screen.findByText('This album is empty');
  expect(screen.getByText(/add a\s+saved look, a show or a view/)).toBeInTheDocument();
  expect(tiles()).toHaveLength(0);
  // Still an album: its name, its count and its sort control are all there.
  expect(screen.getByText('Resort · 0 items')).toBeInTheDocument();
  expect(screen.getByLabelText('Sort by')).toBeInTheDocument();
});

test("an album that is not yours is not an album, and offers the way out", async () => {
  AlbumsAPI.getAlbum.mockResolvedValue(null);   // 404: gone, or never yours
  render(
    <AlbumGrid
      currentPage="library"
      currentUser={{ username: 'reader' }}
      albumId="7"
      navigate={navigate}
    />,
  );

  await screen.findByText('No such album');
  fireEvent.click(screen.getByRole('button', { name: 'Back to library' }));
  expect(navigate).toHaveBeenCalledWith({ page: 'library' });
  expect(wentTo()).toBe('/library');
});

// ── The route ────────────────────────────────────────────────────────────

test('/library/albums/:id renders the album, and Back returns to the library', async () => {
  window.history.replaceState({}, '', '/library/albums/7');
  render(<App />);

  // The album, not the library — the two are different components and the
  // route is what chooses between them.
  await waitFor(() => expect(tiles().length).toBe(4));
  expect(screen.queryByText('library page')).toBeNull();
  expect(AlbumsAPI.getAlbum).toHaveBeenCalledWith('7');
  // The nav still says Library: an album is inside it.
  expect(screen.getByRole('button', { name: 'Library' })).toHaveClass('active');

  fireEvent.click(screen.getByRole('button', { name: 'Back to library' }));

  await screen.findByText('library page');
  expect(path()).toBe('/library');
  expect(document.querySelectorAll('.alb-tile')).toHaveLength(0);

  // And the browser's own Back walks straight back into the album, because
  // going in and coming out were both history entries and not state.
  await act(async () => {
    window.history.back();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
  await waitFor(() => expect(path()).toBe('/library/albums/7'));
  await waitFor(() => expect(tiles().length).toBe(4));
});

// ── Taking a tile out, which is not unsaving ─────────────────────────────
//
// The two destructive acts of this feature sit one page apart and one of them
// cannot be undone. REMOVE FROM ALBUM takes a tile out of this album and
// leaves the favourite exactly where it was; UNSAVE, in the library, ends the
// favourite and the cascade on `album_items` takes it out of every album on
// the way past. A control wired to the wrong one of those looks identical
// until somebody's saved look is gone.

const removeButton = () => screen.getByRole('button', { name: 'Remove from album' });

test('removing a tile takes it out of the album and leaves the favourite saved', async () => {
  rows = [LOOK_A, SHOW_B];
  await openAlbum();

  // It names the thing it is about, and does nothing until one is chosen.
  expect(removeButton()).toBeDisabled();
  fireEvent.click(tiles()[0]);
  await waitFor(() => expect(removeButton()).not.toBeDisabled());
  expect(removeButton()).toHaveAttribute(
    'title', 'Take Yohji Yamamoto out of this album');

  fireEvent.click(removeButton());

  await waitFor(() => expect(AlbumsAPI.removeFromAlbum).toHaveBeenCalledWith(7, 101));
  // Not the endpoint that unsaves, and not the one that deletes the album.
  expect(API.removeFavourite).not.toHaveBeenCalled();
  expect(API.removeShowFavourite).not.toHaveBeenCalled();
  expect(AlbumsAPI.deleteAlbum).not.toHaveBeenCalled();

  // The tile goes; the album stays, with the other tile in it.
  await waitFor(() => expect(tiles()).toHaveLength(1));
  expect(screen.getByText('Resort')).toBeInTheDocument();
});

test('the control does not dress itself as the one that cannot be undone', async () => {
  rows = [LOOK_A];
  await openAlbum();

  // `--ar-danger` is spent on unsaving and on nothing else. This act is one
  // press of the picker away from being undone, and a red button over it
  // would teach the reader that both buttons mean the same thing.
  expect(removeButton()).not.toHaveClass('ar-btn-danger');
  expect(document.querySelectorAll('.ar-btn-danger')).toHaveLength(0);
  // And it says which of the two it is, in the words the act uses.
  expect(screen.getByText(/It stays in your library/)).toBeInTheDocument();
});

// ── what opening one album costs ──────────────────────────────────────────
//
// This page draws one album. It has no shelf on it — the shelf is the
// library's sidebar — and `useAlbums` was fetching one anyway, so opening an
// album made two requests and threw the answer to one of them away.

test('opening an album asks for that album and not for the shelf', async () => {
  await openAlbum();

  expect(AlbumsAPI.getAlbum).toHaveBeenCalledTimes(1);
  expect(AlbumsAPI.getAlbums).not.toHaveBeenCalled();
});

test('and the sort control still works without one', async () => {
  await openAlbum();

  fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'designer' } });

  await waitFor(() => expect(AlbumsAPI.setAlbumOptions).toHaveBeenCalledWith(
    7, { sortBy: 'designer' }));
  expect(AlbumsAPI.getAlbums).not.toHaveBeenCalled();
});

test('and taking a tile out still works without one', async () => {
  await openAlbum();

  fireEvent.click(tiles()[0]);
  fireEvent.click(screen.getByRole('button', { name: /Remove from album/ }));

  await waitFor(() => expect(AlbumsAPI.removeFromAlbum).toHaveBeenCalled());
  await waitFor(() => expect(tiles()).toHaveLength(ALL.length - 1));
  expect(AlbumsAPI.getAlbums).not.toHaveBeenCalled();
});
