import { FILTER_KEYS, buildRoute } from '../../app/routes';
import {
  EMPTY_FILTERS, showId, showSlug, sameShow, clickAction,
  initialUrlSync, deepLinkStarted, deepLinkSettled, deepLinkAbandoned,
  routeChanged, manualLook, urlWrite, lookToApply,
} from './showUrl';

// ── Which row a URL can name ──────────────────────────────────────────────

describe('showId', () => {
  test('a firstVIEW row is its bare integer id', () => {
    expect(showId({ collection_id: 1234 })).toBe('1234');
    expect(showId({ collection_id: '1234' })).toBe('1234');
  });

  test('anything that is not a bare integer is not addressable', () => {
    // A crawled row with no id, or one carrying a URL or a composite key:
    // none of these survive parseRoute, so none of them is written to a URL.
    expect(showId({})).toBeNull();
    expect(showId({ collection_id: null })).toBeNull();
    expect(showId({ collection_id: undefined })).toBeNull();
    expect(showId({ collection_id: '' })).toBeNull();
    expect(showId({ collection_id: 'abc' })).toBeNull();
    expect(showId({ collection_id: '12a' })).toBeNull();
    expect(showId({ collection_id: '12.5' })).toBeNull();
    expect(showId({ collection_id: '-12' })).toBeNull();
    expect(showId(null)).toBeNull();
    expect(showId(undefined)).toBeNull();
  });

  test('0 is a bare integer and stays addressable here', () => {
    // The look number rejects 0; a collection id has no such rule, and
    // inventing one here would silently drop a row the API accepts.
    expect(showId({ collection_id: 0 })).toBe('0');
  });
});

describe('showSlug', () => {
  test('reads the designer and the subtitle', () => {
    expect(showSlug({ designer: 'Gucci', subtitle: 'FW 2024' }))
      .toBe('gucci-fw-2024');
  });

  test('takes designer_name when the row spells it that way', () => {
    expect(showSlug({ designer_name: 'Acne Studios', subtitle: 'SS 2019' }))
      .toBe('acne-studios-ss-2019');
  });

  test('a missing subtitle still produces a segment', () => {
    expect(showSlug({ designer: 'Prada' })).toBe('prada');
  });

  test('a row with no designer at all still produces a segment', () => {
    // Never an empty string: /hf//1234 parses as a different shape.
    expect(showSlug({})).toBe('show');
    expect(showSlug({ designer: '', subtitle: '' })).toBe('show');
    expect(showSlug({ subtitle: 'FW 2024' })).toBe('fw-2024');
  });
});

describe('EMPTY_FILTERS', () => {
  test('is exactly FILTER_KEYS, every one of them empty', () => {
    expect(Object.keys(EMPTY_FILTERS).sort()).toEqual([...FILTER_KEYS].sort());
    expect(Object.values(EMPTY_FILTERS)).toEqual(
      [...FILTER_KEYS].map(() => ''));
  });
});

// ── Clicking a row ────────────────────────────────────────────────────────

describe('clickAction', () => {
  const gucci = { collection_id: 1, url: 'https://x/gucci', designer: 'Gucci' };
  const prada = { collection_id: 2, url: 'https://x/prada', designer: 'Prada' };

  test('a different show is a navigation the user made', () => {
    expect(clickAction({ clicked: prada, open: gucci })).toBe('open');
    expect(clickAction({ clicked: gucci, open: null })).toBe('open');
  });

  // Important 2: standing on /hf/x/1/7 and clicking that same row used to
  // build /hf/x/1, push it, reset the viewer to look 1 and land on
  // /hf/x/1/1 — a history entry Back could reach without changing the
  // screen, so Back looked broken and needed a second press.
  test('re-clicking the show that is already open is not a navigation', () => {
    expect(clickAction({ clicked: gucci, open: gucci })).toBe('ignore');
  });

  test('the same show as a fresh object from a refetched list is still open', () => {
    expect(clickAction({ clicked: { ...gucci }, open: gucci })).toBe('ignore');
  });

  test('a row the URL named is adopted without a write', () => {
    expect(clickAction({ clicked: gucci, open: null, fromUrl: true }))
      .toBe('adopt');
    // Even for the show already open: the URL is where it came from.
    expect(clickAction({ clicked: gucci, open: gucci, fromUrl: true }))
      .toBe('adopt');
  });
});

describe('sameShow', () => {
  test('matches on the addressable id', () => {
    expect(sameShow({ collection_id: 1 }, { collection_id: '1' })).toBe(true);
    expect(sameShow({ collection_id: 1 }, { collection_id: 2 })).toBe(false);
  });

  test('falls back to the collection url when either row has no id', () => {
    expect(sameShow({ url: 'u' }, { url: 'u' })).toBe(true);
    expect(sameShow({ url: 'u' }, { url: 'v' })).toBe(false);
    expect(sameShow({ collection_id: 1, url: 'u' }, { url: 'u' })).toBe(true);
  });

  test('two rows with neither an id nor a url are not assumed equal', () => {
    expect(sameShow({}, {})).toBe(false);
    expect(sameShow(null, null)).toBe(false);
    expect(sameShow({ url: 'u' }, null)).toBe(false);
  });
});

// ── Who is allowed to write the address bar ───────────────────────────────

describe('urlWrite on a plain load', () => {
  test('the first no-selection render leaves the arriving URL alone', () => {
    const s = initialUrlSync();
    const first = urlWrite(s, { hasSelection: false });
    expect(first.target).toBe('none');
    // ...and only the first. The next one is a change the page made.
    expect(urlWrite(first.state, { hasSelection: false }).target)
      .toBe('archive');
  });

  test('opening a show retires the guard too', () => {
    const s = urlWrite(initialUrlSync(), {
      hasSelection: true, imagesLength: 3, currentIndex: 0,
    }).state;
    expect(urlWrite(s, { hasSelection: false }).target).toBe('archive');
  });

  test('a show writes the look on screen, 1-based, once one has landed', () => {
    const s = initialUrlSync();
    expect(urlWrite(s, { hasSelection: true, imagesLength: 0, currentIndex: 0 }))
      .toMatchObject({ target: 'show', imageNumber: null });
    expect(urlWrite(s, { hasSelection: true, imagesLength: 9, currentIndex: 6 }))
      .toMatchObject({ target: 'show', imageNumber: 7 });
  });
});

describe('urlWrite while a deep link is in flight', () => {
  test('nothing is written, and the guard is not spent', () => {
    let s = deepLinkStarted(initialUrlSync(), { collectionId: '1234' });
    const mid = urlWrite(s, { hasSelection: false });
    expect(mid.target).toBe('none');
    expect(mid.state.firstWrite).toBe(true);
  });

  // Important 1: the mid-flight bail used to leave firstWrite standing, and
  // a deep link that resolved nothing left it standing for good. The user's
  // next real write — a year filter, with no show open — was eaten by it,
  // so the query string did not move until they changed a filter twice.
  test('a deep link that resolves nothing does not eat the next write', () => {
    let s = deepLinkStarted(initialUrlSync(), { collectionId: '999999999' });
    expect(urlWrite(s, { hasSelection: false }).target).toBe('none');
    s = deepLinkSettled(s, { found: false });
    expect(urlWrite(s, { hasSelection: false }).target).toBe('archive');
  });

  test('a deep link that fails outright does not eat it either', () => {
    let s = deepLinkStarted(initialUrlSync(), { collectionId: '1234' });
    s = deepLinkSettled(s, { found: false });
    expect(urlWrite(s, { hasSelection: false }).target).toBe('archive');
  });

  test('a deep link that resolves writes the show it opened', () => {
    let s = deepLinkStarted(initialUrlSync(), { collectionId: '1234' });
    s = deepLinkSettled(s, { found: true });
    expect(urlWrite(s, { hasSelection: true, imagesLength: 2, currentIndex: 0 }))
      .toMatchObject({ target: 'show' });
  });

  test('a superseded deep link stops blocking writes', () => {
    let s = deepLinkStarted(initialUrlSync(), { collectionId: '1234' });
    s = deepLinkAbandoned(s);
    expect(s.pending).toBeNull();
  });
});

// ── The look a link asked for ─────────────────────────────────────────────

describe('the requested look', () => {
  // Minor 4: /hf/x/1/12 used to drop to /hf/x/1 while the stream loaded, so
  // a stream that failed lost the shared look altogether.
  test('stays in the URL while the images it needs are still arriving', () => {
    // The row resolved, so the show is open and state -> URL is writing
    // again — but the 12th image has not landed yet and currentIndex is
    // still 0. The URL must keep saying 12.
    let s = deepLinkStarted(initialUrlSync(), {
      collectionId: '1', imageNumber: 12,
    });
    s = deepLinkSettled(s, { found: true });
    expect(urlWrite(s, { hasSelection: true, imagesLength: 3, currentIndex: 0 }))
      .toMatchObject({ target: 'show', imageNumber: 12 });
    expect(urlWrite(s, { hasSelection: true, imagesLength: 0, currentIndex: 0 }))
      .toMatchObject({ target: 'show', imageNumber: 12 });
  });

  test('is not applied until it has actually arrived', () => {
    const s = deepLinkStarted(initialUrlSync(), {
      collectionId: '1', imageNumber: 12,
    });
    expect(lookToApply(s, { imagesLength: 0, expectedLookCount: 40 }).index)
      .toBeNull();
    expect(lookToApply(s, { imagesLength: 3, expectedLookCount: 40 }).index)
      .toBeNull();
    expect(lookToApply(s, { imagesLength: 12, expectedLookCount: 40 }).index)
      .toBe(11);
  });

  test('is clamped once the show is known to be shorter', () => {
    const s = deepLinkStarted(initialUrlSync(), {
      collectionId: '1', imageNumber: 200,
    });
    expect(lookToApply(s, { imagesLength: 40, expectedLookCount: 40 }).index)
      .toBe(39);
  });

  test('is spent once applied, so it cannot yank the reader twice', () => {
    const s = deepLinkStarted(initialUrlSync(), {
      collectionId: '1', imageNumber: 3,
    });
    const applied = lookToApply(s, { imagesLength: 3, expectedLookCount: 40 });
    expect(applied.index).toBe(2);
    expect(lookToApply(applied.state, { imagesLength: 12, expectedLookCount: 40 }).index)
      .toBeNull();
  });

  // Minor 5: arrowing during a deep-link load used to leave the requested
  // look standing, so the reader was yanked to it when that image landed.
  test('a look chosen by hand cancels the one the link asked for', () => {
    let s = deepLinkStarted(initialUrlSync(), {
      collectionId: '1', imageNumber: 12,
    });
    s = deepLinkSettled(s, { found: true });
    s = manualLook(s);
    expect(lookToApply(s, { imagesLength: 12, expectedLookCount: 40 }).index)
      .toBeNull();
    expect(urlWrite(s, { hasSelection: true, imagesLength: 5, currentIndex: 4 }))
      .toMatchObject({ imageNumber: 5 });
  });
});

// ── Tail cases ────────────────────────────────────────────────────────────

describe('clickAction while a deep link is fetching', () => {
  const gucci = { collection_id: 1, url: 'https://x/gucci', designer: 'Gucci' };
  const prada = { collection_id: 2, url: 'https://x/prada', designer: 'Prada' };

  // Minor 2: standing on /hf/x/1/12 with the row fetch still in flight,
  // nothing is open yet, so clicking that very row used to read as a fresh
  // navigation and push /hf/x/1 over the /hf/x/1/12 already shown. The id
  // did not change, so URL -> state never re-ran, and Back later reached
  // that entry and changed nothing on screen.
  test('clicking the show the link is already fetching is not a navigation', () => {
    expect(clickAction({ clicked: gucci, open: null, pendingId: '1' }))
      .toBe('ignore');
  });

  test('a different show is still a navigation the user made', () => {
    expect(clickAction({ clicked: prada, open: null, pendingId: '1' }))
      .toBe('open');
  });

  test('the row the link itself resolved is still adopted', () => {
    expect(clickAction({ clicked: gucci, open: null, pendingId: '1', fromUrl: true }))
      .toBe('adopt');
  });

  test('nothing pending leaves the old answers alone', () => {
    expect(clickAction({ clicked: gucci, open: null, pendingId: null }))
      .toBe('open');
  });
});

describe('clickAction on a show whose images did not arrive', () => {
  const gucci = { collection_id: 1, url: 'https://x/gucci', designer: 'Gucci' };

  // Minor 3: "No images found" plus a click that does nothing reads as
  // broken. Re-clicking the highlighted row was the de facto retry until
  // re-click became a flat no-op.
  test('re-clicking it reloads, and replaces rather than pushes', () => {
    expect(clickAction({ clicked: gucci, open: gucci, hasImages: false }))
      .toBe('reload');
  });

  test('a show that is still loading is not retried underneath the reader', () => {
    expect(clickAction({
      clicked: gucci, open: gucci, hasImages: false, imagesLoading: true,
    })).toBe('ignore');
  });

  test('a show with looks on screen is still left alone', () => {
    expect(clickAction({ clicked: gucci, open: gucci, hasImages: true }))
      .toBe('ignore');
    // The default: a caller that says nothing about images means the show
    // is on screen, which is the reading every other call site has.
    expect(clickAction({ clicked: gucci, open: gucci })).toBe('ignore');
  });

  test('a row the URL named is adopted, not reloaded', () => {
    expect(clickAction({
      clicked: gucci, open: gucci, hasImages: false, fromUrl: true,
    })).toBe('adopt');
  });
});

describe('the first-write guard once the user has navigated', () => {
  // Minor 1: arrive on /hf/x/1234/12, press Back to / before the row fetch
  // returns. Cleanup abandons the deep link, the effect returns at !wanted,
  // and state -> URL's deps never change — so the guard was never spent and
  // ate the user's next filter change, exactly the Important 1 symptom in a
  // narrower sequence.
  test('an abandoned deep link no longer eats the next write', () => {
    let s = initialUrlSync('/hf/x/1234/12');
    s = deepLinkStarted(s, { collectionId: '1234', imageNumber: 12 });
    expect(urlWrite(s, { hasSelection: false }).target).toBe('none');
    s = deepLinkAbandoned(s);
    s = routeChanged(s, { path: '/' });
    expect(urlWrite(s, { hasSelection: false }).target).toBe('archive');
  });

  test('the URL the page mounted on does not retire the guard', () => {
    const s = initialUrlSync('/hf/x/1234/12');
    const same = routeChanged(s, { path: '/hf/x/1234/12' });
    expect(same).toBe(s);
    expect(urlWrite(same, { hasSelection: false }).target).toBe('none');
  });

  test('a page that recorded no arrival URL keeps the old behaviour', () => {
    const s = routeChanged(initialUrlSync(), { path: '/anything' });
    expect(s.firstWrite).toBe(true);
  });

  test('it retires the guard and nothing else', () => {
    let s = initialUrlSync('/hf/x/1234/12');
    s = deepLinkStarted(s, { collectionId: '1234', imageNumber: 12 });
    const moved = routeChanged(s, { path: '/hf/y/99' });
    expect(moved.firstWrite).toBe(false);
    expect(moved.pending).toBe('1234');
    expect(moved.look).toBe(12);
  });

  test('a second route change is a no-op once the guard is spent', () => {
    let s = routeChanged(initialUrlSync('/'), { path: '/hf/x/1' });
    expect(s.firstWrite).toBe(false);
    expect(routeChanged(s, { path: '/hf/x/2' })).toBe(s);
  });
});


// ── The URL a filter change writes while a show is open ───────────────────
//
// Changing a filter used to close the show, so this composition never came
// up: with nothing open urlWrite answered 'archive' and the address bar fell
// back to "/" with the filters behind it. The show stays now, and the two
// halves have to agree — the URL must still name the show *and* carry the
// new filters, or the next reload opens something the reader was not
// looking at. buildRoute is the other half, so it is composed here rather
// than assumed.
describe('the URL a filter change writes while a show is open', () => {
  const OPEN = {
    collection_id: '1234',
    designer: 'Yohji Yamamoto',
    subtitle: 'Runway Collection — Paris',
  };

  // Past the first-write guard, no deep link in flight: an ordinary page
  // with a show open and the reader changing a filter.
  const settled = () => ({ ...initialUrlSync('/'), firstWrite: false });

  const urlFor = ({ filters, imagesLength = 2, currentIndex = 0 }) => {
    const decided = urlWrite(settled(), { hasSelection: true, imagesLength, currentIndex });
    expect(decided.target).toBe('show');
    return buildRoute({
      page: 'high-fashion',
      slug: showSlug(OPEN),
      collectionId: showId(OPEN),
      imageNumber: decided.imageNumber,
      filters,
    });
  };

  test('names the show, and carries the filter that was just set', () => {
    expect(urlFor({ filters: { gender: 'Men' } }))
      .toBe('/hf/yohji-yamamoto-runway-collection-paris/1234/1?gender=Men');
  });

  test('several filters ride along, and the look on screen is kept', () => {
    expect(urlFor({ filters: { gender: 'Men', year: '1999', city: 'Paris' },
                    imagesLength: 12, currentIndex: 6 }))
      .toBe('/hf/yohji-yamamoto-runway-collection-paris/1234/7'
            + '?city=Paris&gender=Men&year=1999');
  });

  test('clearing the filters leaves the show and drops the query string', () => {
    expect(urlFor({ filters: {} }))
      .toBe('/hf/yohji-yamamoto-runway-collection-paris/1234/1');
  });

  test('with nothing open it is still the archive that gets written', () => {
    // The other branch, unchanged. A show closing is what used to send every
    // filter change down here; only Back and a different row do now.
    const decided = urlWrite(settled(), { hasSelection: false });
    expect(decided.target).toBe('archive');
    expect(buildRoute({ page: 'high-fashion', filters: { gender: 'Men' } }))
      .toBe('/?gender=Men');
  });
});
