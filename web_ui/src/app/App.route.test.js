import { parseRoute } from './routes';
import { pageKeyForRoute } from './App';

// App.js's own mapping from a parsed route to the page key the three page
// components and TopBar use — imported, not restated. It used to be copied
// into this file, which meant the test agreed with itself no matter what
// App.js did. This tests the mapping, not React: rendering App would need a
// backend, a cookie and three pages' worth of fetches to answer, none of
// which is what is interesting here.
const pageKeyFor = pageKeyForRoute;

test.each([
  ['/', 'high-fashion'],
  ['/hf/gucci/1234', 'high-fashion'],
  ['/hf/gucci/1234/12', 'high-fashion'],
  ['/brands', 'my-brands'],
  ['/brands/acne/knitwear', 'my-brands'],
  ['/library', 'library'],
  ['/library/albums/7', 'library'],
  ['/nonsense', 'high-fashion'],
])('%s renders the %s page', (path, expected) => {
  expect(pageKeyFor(parseRoute(path, ''))).toBe(expected);
});

// A share link has no page of its own yet. It must land somewhere real
// rather than on a blank screen.
test('an unfinished share route still renders a page', () => {
  expect(pageKeyFor(parseRoute('/s/AbC123', ''))).toBe('high-fashion');
});

// The filters ride in the query string and the page still has to be decided
// from the path — a filtered library link is the library, not the archive.
test('a query string does not change which page is decided', () => {
  expect(pageKeyFor(parseRoute('/library', '?year=2020'))).toBe('library');
  expect(pageKeyFor(parseRoute('/', '?year=2020&city=Paris'))).toBe('high-fashion');
});
