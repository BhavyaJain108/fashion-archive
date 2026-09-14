import { renderHook, act, waitFor } from '@testing-library/react';
import { FashionArchiveAPI } from '../api';
import { useRecents } from './useRecents';

// Rows as GET /api/recents returns them: the show as it was last opened.
const YOHJI = {
  collection_id: '1234',
  designer: 'Yohji Yamamoto',
  season: 'Fall / Winter',
  year: 1999,
  gender: 'Women',
  url: 'https://ex.test/show/1234',
  thumbnail_url: 'shows/1234/look-01.jpg',
  look_count: 42,
  viewed_at: '2026-09-13T10:00:00',
};

const RAF = { ...YOHJI, collection_id: '5678', designer: 'Raf Simons', year: 2001 };

let getRecents;
let errorLog;

beforeEach(() => {
  getRecents = jest.spyOn(FashionArchiveAPI, 'getRecents').mockResolvedValue([]);
  errorLog = jest.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => jest.restoreAllMocks());

const mount = async () => {
  const hook = renderHook(() => useRecents());
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
  return hook;
};

test('loads the list once, newest first, exactly as the server ordered it', async () => {
  getRecents.mockResolvedValue([YOHJI, RAF]);
  const { result } = await mount();

  expect(getRecents).toHaveBeenCalledTimes(1);
  // Not re-sorted here. `viewed_at DESC` is the server's ORDER BY and a
  // second opinion about the order is a second answer to drift from it.
  expect(result.current.recents.map(r => r.designer))
    .toEqual(['Yohji Yamamoto', 'Raf Simons']);
  expect(result.current.error).toBeNull();
});

test('a list that has not arrived is an empty list, not undefined', async () => {
  // Held before the first response, and the shape a caller maps over.
  const hook = renderHook(() => useRecents());
  expect(hook.result.current.recents).toEqual([]);
  expect(hook.result.current.loading).toBe(true);
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
});

test('a body with no rows is an empty list rather than a throw', async () => {
  getRecents.mockResolvedValue(undefined);
  const { result } = await mount();
  expect(result.current.recents).toEqual([]);
});

test('reload asks again and replaces the list', async () => {
  getRecents.mockResolvedValue([YOHJI]);
  const { result } = await mount();
  expect(result.current.recents).toHaveLength(1);

  getRecents.mockResolvedValue([RAF, YOHJI]);
  await act(async () => { result.current.reload(); });
  await waitFor(() => expect(result.current.recents).toHaveLength(2));
  expect(getRecents).toHaveBeenCalledTimes(2);
  expect(result.current.recents[0].designer).toBe('Raf Simons');
});

test('a failed reload leaves the last good list on screen', async () => {
  getRecents.mockResolvedValue([YOHJI, RAF]);
  const { result } = await mount();

  getRecents.mockRejectedValue(new Error('offline'));
  await act(async () => { result.current.reload(); });
  await waitFor(() => expect(result.current.error).toBeTruthy());

  // Two rows still. Blanking the drawer on a failed refresh takes away the
  // way back to a show for no reason — the old list is still true, it is
  // just old.
  expect(result.current.recents.map(r => r.designer))
    .toEqual(['Yohji Yamamoto', 'Raf Simons']);
  expect(result.current.loading).toBe(false);
  expect(errorLog).toHaveBeenCalled();
});

test('a reload that answers late does not overwrite a newer one', async () => {
  getRecents.mockResolvedValue([]);
  const { result } = await mount();

  // Two reloads in flight; the FIRST one settles last. Without a ticket per
  // request the stale answer is the one that ends up on screen.
  let releaseSlow;
  const slow = new Promise(resolve => { releaseSlow = resolve; });
  getRecents.mockReturnValueOnce(slow);
  await act(async () => { result.current.reload(); });

  getRecents.mockResolvedValueOnce([RAF]);
  await act(async () => { result.current.reload(); });
  await waitFor(() => expect(result.current.recents).toHaveLength(1));

  await act(async () => { releaseSlow([YOHJI, YOHJI, YOHJI]); await slow; });

  expect(result.current.recents.map(r => r.designer)).toEqual(['Raf Simons']);
});

test('an answer that lands after unmount is dropped', async () => {
  let release;
  getRecents.mockReturnValue(new Promise(resolve => { release = resolve; }));
  const { unmount } = renderHook(() => useRecents());
  unmount();
  await act(async () => { release([YOHJI]); });
  // Nothing to assert on the hook itself; the point is that React did not
  // warn about a state update on an unmounted component.
  expect(errorLog).not.toHaveBeenCalled();
});
