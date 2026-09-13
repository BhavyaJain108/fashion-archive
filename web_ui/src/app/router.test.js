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
