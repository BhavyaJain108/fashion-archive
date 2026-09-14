import { collectionIdOf, showIdOf, kindOf, filterPairs } from './savedRow';

// One rule for "which show is this", written three times: once in
// `favourites_collection_id` in backend/userdata/schema.sql, once in
// `firstview.collection_id_from_url`, and once here. The column is the
// authority — a CHECK constraint keeps it equal to the SQL expression — so
// what is pinned below is that the client agrees with it, case for case.
//
// The two rows this file exists for are the two the client used to read
// differently from the server:
//
//   …?id=1234#top             SQL 1234, the old client regex null
//   …?collection=99&id=1234   SQL 1234, the old client regex 99
//
// For such a row the album tile opened and the library tile, on the other
// spelling, silently did nothing.

const at = (url, id) => (id === undefined ? { url } : { url, id });

describe('firstVIEW\'s id for a show, off the url', () => {
  test('the ordinary collection url', () => {
    expect(collectionIdOf(at('https://fv.test/collection_images.php?id=1234&list=all')))
      .toBe('1234');
    expect(collectionIdOf(at('https://fv.test/collection_images.php?id=1234')))
      .toBe('1234');
  });

  // The SQL says `[&#]|$`, because a fragment ends a query parameter exactly
  // as an ampersand does.
  test('a fragment ends the parameter, as the database says it does', () => {
    expect(collectionIdOf(at('https://fv.test/collection_images.php?id=1234#top')))
      .toBe('1234');
  });

  // `qs.get("id") or qs.get("collection")` — id wins wherever both are there,
  // whichever order they arrive in.
  test('id wins over collection, in either order', () => {
    expect(collectionIdOf(at('https://fv.test/x.php?collection=99&id=1234'))).toBe('1234');
    expect(collectionIdOf(at('https://fv.test/x.php?id=1234&collection=99'))).toBe('1234');
  });

  test('collection answers when it is the only one there', () => {
    expect(collectionIdOf(at('https://fv.test/x.php?collection=99'))).toBe('99');
  });

  test('anything that is not a whole number is not a show id', () => {
    expect(collectionIdOf(at('https://fv.test/x.php?id=123abc'))).toBeNull();
    expect(collectionIdOf(at('https://fv.test/x.php'))).toBeNull();
    expect(collectionIdOf(at(''))).toBeNull();
    expect(collectionIdOf(null)).toBeNull();
  });
});

describe('the id a saved row carries', () => {
  test('the stored column wins over the parse', () => {
    // The row the server sent says 1234; the url would be read as 99 by
    // anything that only parses. The column is the authority.
    expect(showIdOf(at('https://fv.test/x.php?collection=99&id=1234', '1234'))).toBe('1234');
    expect(showIdOf(at('https://fv.test/x.php?id=1234#top', '1234'))).toBe('1234');
  });

  test('a number from the server is read as the text a route is built from', () => {
    expect(showIdOf({ url: '', id: 1234 })).toBe('1234');
  });

  test('a row saved before the column existed falls back to the url', () => {
    expect(showIdOf(at('https://fv.test/collection_images.php?id=1234&list=all')))
      .toBe('1234');
    expect(showIdOf({ url: 'https://fv.test/x.php?id=1234', id: null })).toBe('1234');
    expect(showIdOf({ url: 'https://fv.test/x.php?id=1234', id: '' })).toBe('1234');
  });

  test('a row that names no show has no id at all', () => {
    expect(showIdOf(at('https://fv.test/x.php'))).toBeNull();
    expect(showIdOf(null)).toBeNull();
  });
});

describe('the rest of a saved row', () => {
  test('a row old enough not to say what it is, is a look', () => {
    expect(kindOf({})).toBe('look');
    expect(kindOf(null)).toBe('look');
    expect(kindOf({ kind: 'show' })).toBe('show');
  });

  test('filters are drawn in one order, whatever order they arrived in', () => {
    expect(filterPairs({ city: 'Paris', year: '2019' }))
      .toEqual([['Year', '2019'], ['City', 'Paris']]);
    expect(filterPairs(null)).toEqual([]);
  });
});
