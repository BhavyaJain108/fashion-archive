// The recents drawer: the rectangle at the foot of the sidebar, what opening
// it does to the list above, and what clicking a row in it opens.
//
// Three things are pinned here, in three different ways, because no one way
// can reach all of them:
//
//   * the component's behaviour, in jsdom — collapsed is one rectangle,
//     open is a list, the state is remembered, a row calls back with the
//     row it is on;
//   * the page's wiring — a recent opens through handleCollectionSelect
//     itself, so the address bar is written and the show on screen stays put
//     while the new one streams. That is the "same path" requirement, and it
//     is only visible end to end;
//   * the geometry, as a CSS contract — the four declarations that make the
//     drawer take a fifth of the sidebar OUT OF THE LIST rather than off the
//     bottom of the viewport. jsdom lays nothing out, so this half is the
//     stylesheet read as text; the real measurement is in headless Chrome
//     against the built bundle and is recorded in the task report.
import React from 'react';
import fs from 'fs';
import path from 'path';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';

import RecentsDrawer from './RecentsDrawer';

// The page half of this file needs the API stubbed; the component half does
// not touch it. jest.mock is file-wide and hoisted, so it sits here.
jest.mock('../../shared/api', () => ({
  FashionArchiveAPI: {
    getSeasons: jest.fn(), getIndexStatus: jest.fn(), getDesigners: jest.fn(),
    getRecents: jest.fn(), getFavourites: jest.fn(), searchShows: jest.fn(),
    browseCatalog: jest.fn(), streamCollectionImages: jest.fn(),
    streamCatalog: jest.fn(), streamDesignerCollections: jest.fn(),
    downloadVideo: jest.fn(),
    addFavourite: jest.fn(), removeFavourite: jest.fn(),
    addShowFavourite: jest.fn(), removeShowFavourite: jest.fn(),
    addViewFavourite: jest.fn(), removeViewFavourite: jest.fn(),
    getImageUrl: (p) => `/images/${p}`,
  },
}));

// eslint-disable-next-line import/first
import HighFashionPage from './HighFashionPage';
// eslint-disable-next-line import/first
import { FashionArchiveAPI as API } from '../../shared/api';

const recentRow = (over = {}) => ({
  collection_id: '5678',
  designer: 'Raf Simons',
  season: 'Fall / Winter',
  year: 2001,
  gender: 'Women',
  url: 'https://example.test/show/5678',
  thumbnail_url: 'shows/5678/look-01.jpg',
  look_count: 38,
  viewed_at: '2026-09-13T10:00:00',
  ...over,
});

const head = () => screen.getByRole('button', { name: /RECENTLY SEEN/ });
const drawerList = () => document.querySelector('.hf2-recents-scroll');

// ── The component ─────────────────────────────────────────────────────────

describe('the drawer itself', () => {
  beforeEach(() => { window.localStorage.clear(); });

  test('closed, it is one rectangle and nothing else', () => {
    render(<RecentsDrawer recents={[recentRow()]} />);

    expect(head()).toHaveAttribute('aria-expanded', 'false');
    // No list at all when closed. A hidden list still costs its rows on
    // every render and is the thing the 20% would have to make room for.
    expect(drawerList()).toBeNull();
    expect(screen.queryByText('Raf Simons')).toBeNull();
    expect(document.querySelector('.hf2-recents.open')).toBeNull();
  });

  test('open, it is the list, and it says so on the element the CSS sizes', () => {
    render(<RecentsDrawer recents={[recentRow(), recentRow({
      collection_id: '1234', designer: 'Yohji Yamamoto', year: 1999,
    })]} />);

    fireEvent.click(head());

    // `.open` is the whole of the 20%: the class the stylesheet keys the
    // flex basis on. Lose it and the drawer silently stays collapsed.
    expect(document.querySelector('.hf2-recents.open')).not.toBeNull();
    expect(head()).toHaveAttribute('aria-expanded', 'true');
    expect(within(drawerList()).getByText('Raf Simons')).toBeInTheDocument();
    expect(within(drawerList()).getByText('Yohji Yamamoto')).toBeInTheDocument();
  });

  test('open or closed is remembered across a remount', () => {
    const { unmount } = render(<RecentsDrawer recents={[recentRow()]} />);
    fireEvent.click(head());
    expect(window.localStorage.getItem('fa:hf-recents-open')).toBe('true');
    unmount();

    render(<RecentsDrawer recents={[recentRow()]} />);
    expect(document.querySelector('.hf2-recents.open')).not.toBeNull();
    expect(within(drawerList()).getByText('Raf Simons')).toBeInTheDocument();
  });

  test('a row calls back with the row it is on', () => {
    const onOpen = jest.fn();
    const rows = [
      recentRow(),
      recentRow({ collection_id: '1234', designer: 'Yohji Yamamoto', year: 1999 }),
    ];
    render(<RecentsDrawer recents={rows} onOpen={onOpen} />);
    fireEvent.click(head());

    fireEvent.click(within(drawerList()).getByText('Yohji Yamamoto'));
    expect(onOpen).toHaveBeenCalledTimes(1);
    // The row, whole and unaltered: the page hands it straight to the same
    // handler the show list uses, and that handler reads `collection_id` and
    // `url` off it.
    expect(onOpen).toHaveBeenCalledWith(rows[1]);
  });

  test('it asks for the list again when it is opened, and not while closed', () => {
    const onReload = jest.fn();
    render(<RecentsDrawer recents={[]} onReload={onReload} />);
    // Closed on a fresh browser: the drawer does not ask for anything.
    expect(onReload).not.toHaveBeenCalled();

    fireEvent.click(head());
    expect(onReload).toHaveBeenCalledTimes(1);

    fireEvent.click(head());
    fireEvent.click(head());
    // Opened again — asked again. The server's list moves every time a show
    // is opened and nothing tells this client that it did.
    expect(onReload).toHaveBeenCalledTimes(2);
  });

  test('an empty history says so rather than showing an empty box', () => {
    render(<RecentsDrawer recents={[]} loading={false} />);
    fireEvent.click(head());
    expect(within(drawerList()).getByText('No shows opened yet')).toBeInTheDocument();
  });

  test('the count is the number of shows, and is absent when there are none', () => {
    const { unmount } = render(<RecentsDrawer recents={[recentRow(), recentRow({
      collection_id: '1234',
    })]} />);
    expect(document.querySelector('.hf2-recents-head .count').textContent).toBe('2');
    unmount();

    render(<RecentsDrawer recents={[]} />);
    expect(document.querySelector('.hf2-recents-head .count')).toBeNull();
  });
});

// ── The CSS contract ──────────────────────────────────────────────────────
//
// jsdom does not lay out, so these read the stylesheet. Each one is a
// declaration that carries part of "20% of the sidebar, taken out of the
// list": delete any of them and the built page is wrong in a way no jsdom
// test can see. The numbers themselves are measured in headless Chrome
// against the built bundle — see the task report.

describe('the geometry, as declarations that must not go', () => {
  const css = fs.readFileSync(
    path.join(__dirname, 'HighFashionPage.css'), 'utf8');

  const ruleFor = (selector) => {
    const at = css.indexOf(`\n${selector} {`);
    expect(at).toBeGreaterThan(-1);
    return css.slice(at, css.indexOf('}', at));
  };

  test('the open drawer is a fixed fifth of the sidebar', () => {
    // 0 0 20%: no growth, NO SHRINK, and a basis that is a percentage of
    // .hf2-sidebar's own height. Shrink would let a short window squeeze the
    // drawer to a sliver instead of shortening the list, which is the one
    // thing the request is specific about.
    expect(ruleFor('.hf2-recents.open')).toMatch(/flex:\s*0\s+0\s+20%/);
  });

  test('the show list is what is left, and is allowed to be smaller than its rows', () => {
    const rule = ruleFor('.hf2-collections-area');
    expect(rule).toMatch(/flex:\s*1/);
    // Without min-height: 0 a flex item refuses to shrink below its content,
    // so the sidebar grows a scrollbar and the drawer pushes off the bottom
    // of the viewport rather than the list shrinking. This single
    // declaration is the difference.
    expect(rule).toMatch(/min-height:\s*0/);
  });

  test('the drawer scrolls inside itself and never spills', () => {
    expect(ruleFor('.hf2-recents')).toMatch(/overflow:\s*hidden/);
    const scroll = ruleFor('.hf2-recents-scroll');
    expect(scroll).toMatch(/overflow-y:\s*auto/);
    expect(scroll).toMatch(/min-height:\s*0/);
  });

  test('the collapsed drawer is its header and no more', () => {
    expect(ruleFor('.hf2-recents')).toMatch(/flex:\s*0\s+0\s+auto/);
  });
});

// ── The page: one way to open a show ──────────────────────────────────────
//
// The requirement this pins is "the same path as clicking a row in the show
// list". Not a similar path: the same function. What that buys is two
// things a second implementation would have to remember and would eventually
// forget — the address bar is written, and the show already on screen stays
// there until the new one has a photograph of its own.

const YOHJI = {
  collection_id: '1234',
  url: 'https://example.test/show/1234',
  season_url: 'https://example.test/season/fw1999',
  designer: 'Yohji Yamamoto',
  designer_name: 'Yohji Yamamoto',
  year: '1999', season: 'Fall / Winter', gender: 'Women',
  subtitle: 'Runway Collection — Paris',
};

const RAF = {
  collection_id: '5678',
  url: 'https://example.test/show/5678',
  season_url: 'https://example.test/season/fw2001',
  designer: 'Raf Simons',
  designer_name: 'Raf Simons',
  year: '2001', season: 'Fall / Winter', gender: 'Women',
  subtitle: 'Runway Collection — Paris',
};

// Raf is in the history but NOT in the list on screen: the archive list is
// only Yohji. That is the whole reason the drawer exists — a way back to a
// show the current filters do not show — and it also means "Raf Simons" in
// the document can only have come from the drawer.
const CATALOGUE = [YOHJI];

const streams = new Map();

// Yohji: two photographs of a promised five, then silence.
const partial = (id, delivered, promised) => ({ onMeta, onImage }) => {
  if (onMeta) onMeta({ count: promised });
  for (let i = 0; i < delivered; i += 1) {
    if (onImage) onImage({ index: i, path: `shows/${id}/look-0${i + 1}.jpg` });
  }
  return {};
};

// Raf: asked for, and nothing ever comes back. The stale window, held open.
const silent = () => new Promise(() => {});

if (!Element.prototype.scrollTo) Element.prototype.scrollTo = () => {};

describe('opening a recent', () => {
  let pushes;

  afterEach(() => { pushes.mockRestore(); });

  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState({}, '', '/');
    jest.clearAllMocks();
    // Every push, kept. Opening a show is the one thing this page pushes;
    // everything else about the address bar replaces. That asymmetry is what
    // makes Back leave the show rather than walk backwards through forty
    // photographs, and it is the part of "the same path" that a drawer
    // setting the selection itself would silently lose — the URL would still
    // be right, because the state -> URL effect replaces into it.
    pushes = jest.spyOn(window.history, 'pushState');

    streams.clear();
    streams.set('1234', partial('1234', 2, 5));
    streams.set('5678', silent);

    API.getSeasons.mockResolvedValue([]);
    API.getIndexStatus.mockResolvedValue({ shows: 55700 });
    API.getDesigners.mockResolvedValue([]);
    API.getFavourites.mockResolvedValue([]);
    API.searchShows.mockResolvedValue({ success: true, shows: [], total: 0 });
    API.downloadVideo.mockResolvedValue(null);
    API.streamCatalog.mockResolvedValue({ nextPage: 0, hasMore: false });
    API.streamDesignerCollections.mockResolvedValue({});
    API.getRecents.mockResolvedValue([recentRow()]);

    API.browseCatalog.mockImplementation(async (filters, options = {}) => {
      if (options.collectionId) {
        return { success: true,
                 collections: [YOHJI, RAF].filter(
                   c => c.collection_id === options.collectionId) };
      }
      return { success: true, collections: CATALOGUE, hasMore: false,
               total: CATALOGUE.length, facets: null };
    });

    API.streamCollectionImages.mockImplementation(async (url, handlers = {}) => {
      const plan = streams.get(url.split('/').pop());
      return plan ? plan(handlers) : {};
    });
  });

  const realThumbs = () => document.querySelectorAll('.hf2-thumb:not(.hf2-thumb-ghost)');
  const statusPath = () => document.querySelector('.hf2-status-path').textContent;

  const openYohjiFromTheList = async () => {
    render(<HighFashionPage currentUser={{ email: 'test@example.test' }} />);
    await screen.findByText('Yohji Yamamoto');
    fireEvent.click(screen.getByText('Yohji Yamamoto'));
    await waitFor(() => expect(realThumbs()).toHaveLength(2));
  };

  test('a recent writes the address bar and keeps the show on screen', async () => {
    await openYohjiFromTheList();
    expect(window.location.pathname).toContain('1234');

    fireEvent.click(head());
    const raf = await waitFor(() => within(drawerList()).getByText('Raf Simons'));
    fireEvent.click(raf);

    // The URL, and the history entry under it.
    await waitFor(() => expect(window.location.pathname).toContain('5678'));
    expect(window.location.pathname).toContain('raf-simons');
    const pushed = pushes.mock.calls.map(c => String(c[2]));
    expect(pushed.some(u => u.includes('5678'))).toBe(true);

    // And the keep-previous behaviour. Raf's stream never answers, so the
    // pane still holds Yohji's two photographs, dimmed and named as Yohji.
    // A drawer that called setSelectedCollection itself would get this
    // right by accident; one that blanked the viewer first would not.
    expect(realThumbs()).toHaveLength(2);
    expect(document.querySelector('.hf2-main.stale')).not.toBeNull();
    expect(statusPath()).toContain('Yohji Yamamoto');
  });

  test('the drawer offers a show the filtered list does not', async () => {
    await openYohjiFromTheList();
    // Before the drawer is opened there is no Raf Simons anywhere: he is not
    // in the archive list these filters produced.
    expect(screen.queryByText('Raf Simons')).toBeNull();

    fireEvent.click(head());
    expect(await waitFor(() => within(drawerList()).getByText('Raf Simons')))
      .toBeInTheDocument();
  });
});
