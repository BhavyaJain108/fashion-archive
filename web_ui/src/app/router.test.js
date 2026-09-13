import { getRoute, navigate, subscribe } from './router';

const at = (url) => window.history.replaceState({}, '', url);

beforeEach(() => at('/'));

describe('getRoute', () => {
  test('reads the current address', () => {
    at('/hf/gucci-fw-2024/1234/12');
    const r = getRoute();
    expect(r.page).toBe('high-fashion');
    expect(r.collectionId).toBe('1234');
    expect(r.imageNumber).toBe(12);
  });

  test('reads filters out of the query string', () => {
    at('/?year=2024&city=Paris');
    expect(getRoute().filters).toEqual({ year: '2024', city: 'Paris' });
  });
});

describe('navigate', () => {
  test('writes the address bar', () => {
    navigate({ page: 'brands', brandId: 'acne' });
    expect(window.location.pathname).toBe('/brands/acne');
  });

  test('pushes a history entry by default', () => {
    const before = window.history.length;
    navigate({ page: 'library' });
    expect(window.history.length).toBeGreaterThan(before);
  });

  test('replace: true does not push', () => {
    navigate({ page: 'library' });
    const before = window.history.length;
    navigate({ page: 'brands' }, { replace: true });
    expect(window.history.length).toBe(before);
    expect(window.location.pathname).toBe('/brands');
  });

  // Without this guard an effect that navigates on every render fills the
  // history stack and the back button stops working.
  test('navigating to the current URL is a no-op', () => {
    navigate({ page: 'brands', brandId: 'acne' });
    const before = window.history.length;
    navigate({ page: 'brands', brandId: 'acne' });
    navigate({ page: 'brands', brandId: 'acne' });
    expect(window.history.length).toBe(before);
  });

  test('notifies subscribers with the new route', () => {
    const seen = [];
    const off = subscribe((r) => seen.push(r));
    navigate({ page: 'library' });
    off();
    expect(seen).toHaveLength(1);
    expect(seen[0].page).toBe('library');
  });

  test('a no-op navigation does not notify', () => {
    navigate({ page: 'library' });
    const seen = [];
    const off = subscribe((r) => seen.push(r));
    navigate({ page: 'library' });
    off();
    expect(seen).toHaveLength(0);
  });
});

describe('subscribe', () => {
  test('fires on popstate', () => {
    const seen = [];
    const off = subscribe((r) => seen.push(r));
    at('/brands/acne');
    window.dispatchEvent(new PopStateEvent('popstate'));
    off();
    expect(seen).toHaveLength(1);
    expect(seen[0].brandId).toBe('acne');
  });

  test('a no-op navigation compares canonical URLs, ignoring filter key order', () => {
    at('/?year=2024&city=Paris');
    const before = window.history.length;
    const seen = [];
    const off = subscribe((r) => seen.push(r));
    // Same filters, different key order than the address bar currently holds
    // (buildRoute sorts keys, so this reproduces city-before-year, the
    // opposite of the address bar's current year-before-city order).
    navigate({ page: 'high-fashion', filters: { city: 'Paris', year: '2024' } });
    off();
    expect(window.history.length).toBe(before);
    expect(seen).toHaveLength(0);
  });

  test('unsubscribe stops delivery', () => {
    const seen = [];
    subscribe((r) => seen.push(r))();
    navigate({ page: 'library' });
    expect(seen).toHaveLength(0);
  });

  test('one subscriber throwing does not stop the others', () => {
    const seen = [];
    const offA = subscribe(() => { throw new Error('boom'); });
    const offB = subscribe((r) => seen.push(r));
    navigate({ page: 'library' });
    offA(); offB();
    expect(seen).toHaveLength(1);
  });
});

describe('getRoute caching', () => {
  test('two calls with no navigation in between return the identical object', () => {
    at('/brands/acne');
    const first = getRoute();
    const second = getRoute();
    expect(second).toBe(first);
  });

  test('after navigate, getRoute() returns a different object', () => {
    at('/brands/acne');
    const first = getRoute();
    navigate({ page: 'library' });
    const second = getRoute();
    expect(second).not.toBe(first);
    expect(second.page).toBe('library');
  });

  test('a replaceState done outside navigate is picked up after a popstate', () => {
    at('/brands/acne');
    const first = getRoute();
    // Bypasses navigate() entirely, the way the browser's own back/forward
    // or a hand-edited address bar would.
    at('/library');
    window.dispatchEvent(new PopStateEvent('popstate'));
    const second = getRoute();
    expect(second).not.toBe(first);
    expect(second.page).toBe('library');
  });
});
