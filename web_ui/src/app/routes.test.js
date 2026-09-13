import { parseRoute, buildRoute, slugify, FILTER_KEYS } from './routes';

describe('slugify', () => {
  test('lowercases and hyphenates', () => {
    expect(slugify('Alexander McQueen')).toBe('alexander-mcqueen');
  });

  test('drops punctuation rather than encoding it', () => {
    expect(slugify("Alessandro Dell' Acqua")).toBe('alessandro-dell-acqua');
  });

  test('joins parts and collapses runs of separators', () => {
    expect(slugify('Comme des Garçons', 'Fall / Winter', 2000, 'Women'))
      .toBe('comme-des-garcons-fall-winter-2000-women');
  });

  test('survives empty and nullish parts', () => {
    expect(slugify('Gucci', '', null, undefined, 2024)).toBe('gucci-2024');
  });

  test('never returns an empty string', () => {
    expect(slugify('', null)).toBe('show');
  });
});

describe('parseRoute', () => {
  test('bare root is high fashion with nothing open', () => {
    expect(parseRoute('/', '')).toEqual({
      page: 'high-fashion',
      collectionId: null,
      imageNumber: null,
      brandId: null,
      category: null,
      albumId: null,
      token: null,
      slug: null,
      filters: {},
    });
  });

  test('reads the collection id from the segment after the slug', () => {
    const r = parseRoute('/hf/alexander-mcqueen-fw-2000-women/3', '');
    expect(r.page).toBe('high-fashion');
    expect(r.collectionId).toBe('3');
    expect(r.imageNumber).toBe(null);
  });

  test('reads the image number', () => {
    const r = parseRoute('/hf/gucci-fw-2024/1234/12', '');
    expect(r.collectionId).toBe('1234');
    expect(r.imageNumber).toBe(12);
  });

  // Image numbers are 1-based (the page builds them as currentImageIndex +
  // 1), so 0 never denotes a real image. A URL carrying /0 is malformed, not
  // "image zero" — reject it the same way non-numeric input is rejected.
  test('an image number of 0 is rejected', () => {
    const r = parseRoute('/hf/gucci/1234/0', '');
    expect(r.imageNumber).toBe(null);
  });

  test('an image number of 1 is accepted', () => {
    const r = parseRoute('/hf/gucci/1234/1', '');
    expect(r.imageNumber).toBe(1);
  });

  // The slug is decoration for identity purposes — it never changes what a
  // URL means — but it is still carried through so a parse-modify-rebuild
  // cycle doesn't silently drop it back to the placeholder.
  test('ignores the slug for identity, but carries it through', () => {
    const a = parseRoute('/hf/gucci-fw-2024/1234/12', '');
    const b = parseRoute('/hf/total-nonsense/1234/12', '');
    const { slug: slugA, ...restA } = a;
    const { slug: slugB, ...restB } = b;
    expect(restA).toEqual(restB);
    expect(slugA).toBe('gucci-fw-2024');
    expect(slugB).toBe('total-nonsense');
  });

  test('the slug is null when there is no show open', () => {
    expect(parseRoute('/', '').slug).toBe(null);
    expect(parseRoute('/brands/acne', '').slug).toBe(null);
  });

  test('a non-numeric collection id is rejected, not passed through', () => {
    const r = parseRoute('/hf/gucci/not-an-id', '');
    expect(r.collectionId).toBe(null);
  });

  test('a non-numeric image number is rejected', () => {
    const r = parseRoute('/hf/gucci/1234/abc', '');
    expect(r.collectionId).toBe('1234');
    expect(r.imageNumber).toBe(null);
  });

  test('brands with and without a category', () => {
    expect(parseRoute('/brands', '').page).toBe('brands');
    expect(parseRoute('/brands/acne', '').brandId).toBe('acne');
    const r = parseRoute('/brands/acne/knitwear', '');
    expect(r.brandId).toBe('acne');
    expect(r.category).toBe('knitwear');
  });

  test('a category with slashes survives encoding', () => {
    const r = parseRoute('/brands/acne/' + encodeURIComponent('men/knitwear'), '');
    expect(r.category).toBe('men/knitwear');
  });

  test('library and one album', () => {
    expect(parseRoute('/library', '').page).toBe('library');
    const r = parseRoute('/library/albums/7', '');
    expect(r.page).toBe('album');
    expect(r.albumId).toBe('7');
  });

  test('a share token', () => {
    const r = parseRoute('/s/AbC123', '');
    expect(r.page).toBe('shared');
    expect(r.token).toBe('AbC123');
  });

  test('an unknown path falls back to high fashion', () => {
    expect(parseRoute('/nonsense/deep/path', '').page).toBe('high-fashion');
  });

  // A stale bookmark or a bot probe with a stray "%" must not white-screen
  // the app — decodeURIComponent throws on malformed percent-encoding, so
  // each segment is decoded defensively and the raw segment is kept on
  // failure rather than letting the exception propagate.
  test('malformed percent-encoding does not throw', () => {
    expect(() => parseRoute('/hf/50%/1234', '')).not.toThrow();
    const r = parseRoute('/hf/50%/1234', '');
    expect(r.collectionId).toBe('1234');
  });

  test('valid percent-encoding still decodes correctly', () => {
    const r = parseRoute('/brands/100%25pure', '');
    expect(r.brandId).toBe('100%pure');
  });

  test('filters come out of the query string', () => {
    const r = parseRoute('/', '?year=2024&season=Fall+%2F+Winter&city=Paris');
    expect(r.filters).toEqual({
      year: '2024',
      season: 'Fall / Winter',
      city: 'Paris',
    });
  });

  // Auth params share the query string with filters and must not leak in.
  test('non-filter query params are dropped', () => {
    const r = parseRoute('/', '?year=2024&token=secret&verified=1&junk=x');
    expect(r.filters).toEqual({ year: '2024' });
  });

  test('empty filter values are dropped', () => {
    expect(parseRoute('/', '?year=&season=Resort').filters).toEqual({ season: 'Resort' });
  });
});

describe('buildRoute', () => {
  test('high fashion with nothing open is the root', () => {
    expect(buildRoute({ page: 'high-fashion' })).toBe('/');
  });

  test('a show, with a slug supplied by the caller', () => {
    expect(buildRoute({
      page: 'high-fashion',
      slug: 'gucci-fw-2024',
      collectionId: '1234',
    })).toBe('/hf/gucci-fw-2024/1234');
  });

  test('a show at an image', () => {
    expect(buildRoute({
      page: 'high-fashion',
      slug: 'gucci-fw-2024',
      collectionId: '1234',
      imageNumber: 12,
    })).toBe('/hf/gucci-fw-2024/1234/12');
  });

  // 0 is not a valid image number anywhere in this app, so a route carrying
  // it builds the same URL as no image number at all.
  test('an image number of 0 builds no image segment', () => {
    expect(buildRoute({
      page: 'high-fashion',
      slug: 'gucci-fw-2024',
      collectionId: '1234',
      imageNumber: 0,
    })).toBe('/hf/gucci-fw-2024/1234');
  });

  test('a missing slug gets a placeholder rather than an empty segment', () => {
    expect(buildRoute({ page: 'high-fashion', collectionId: '1234' }))
      .toBe('/hf/show/1234');
  });

  test('brands', () => {
    expect(buildRoute({ page: 'brands' })).toBe('/brands');
    expect(buildRoute({ page: 'brands', brandId: 'acne' })).toBe('/brands/acne');
    expect(buildRoute({ page: 'brands', brandId: 'acne', category: 'men/knitwear' }))
      .toBe('/brands/acne/men%2Fknitwear');
  });

  test('library and album', () => {
    expect(buildRoute({ page: 'library' })).toBe('/library');
    expect(buildRoute({ page: 'album', albumId: '7' })).toBe('/library/albums/7');
  });

  test('share', () => {
    expect(buildRoute({ page: 'shared', token: 'AbC123' })).toBe('/s/AbC123');
  });

  test('filters become a sorted query string', () => {
    const url = buildRoute({
      page: 'high-fashion',
      filters: { year: '2024', city: 'Paris' },
    });
    expect(url).toBe('/?city=Paris&year=2024');
  });

  test('empty filter values are omitted', () => {
    expect(buildRoute({ page: 'high-fashion', filters: { year: '', city: 'Paris' } }))
      .toBe('/?city=Paris');
  });

  test('unknown filter keys are omitted', () => {
    expect(buildRoute({ page: 'high-fashion', filters: { year: '2024', evil: 'x' } }))
      .toBe('/?year=2024');
  });
});

describe('round trip', () => {
  test.each([
    '/',
    '/?city=Paris&year=2024',
    '/hf/gucci-fw-2024/1234',
    '/hf/gucci-fw-2024/1234/12',
    '/brands',
    '/brands/acne',
    '/library',
    '/library/albums/7',
    '/s/AbC123',
  ])('%s survives parse then build', (url) => {
    const [pathname, search] = url.split('?');
    const route = parseRoute(pathname, search ? `?${search}` : '');
    // parseRoute now carries the slug it saw, so the parsed route can be fed
    // straight back into buildRoute without the caller re-extracting it from
    // the raw pathname.
    expect(buildRoute(route)).toBe(url);
  });
});

describe('FILTER_KEYS', () => {
  // These must match the filter state in HighFashionPage exactly. A key
  // missing here is a filter that silently will not survive a reload.
  test('covers every filter the archive has', () => {
    expect([...FILTER_KEYS].sort()).toEqual([
      'category', 'city', 'gender', 'letter', 'season', 'shootType', 'year',
    ]);
  });
});
