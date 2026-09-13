import { renderHook } from '@testing-library/react';
import { usePersistentState } from '../../shared/hooks/usePersistentState';
import { migrateLegacySidebarOpen } from './legacySidebar';

beforeEach(() => {
  window.localStorage.clear();
});

describe('migrateLegacySidebarOpen', () => {
  test('a legacy "closed" value migrates to false', () => {
    window.localStorage.setItem('hf2-sidebar', 'closed');
    expect(migrateLegacySidebarOpen()).toBe(false);
  });

  test('a legacy "open" value migrates to true', () => {
    window.localStorage.setItem('hf2-sidebar', 'open');
    expect(migrateLegacySidebarOpen()).toBe(true);
  });

  test('no legacy value defaults to true, same as before this change', () => {
    expect(migrateLegacySidebarOpen()).toBe(true);
  });

  test('an unrecognised legacy value falls back to the default rather than throwing', () => {
    window.localStorage.setItem('hf2-sidebar', 'garbage');
    expect(migrateLegacySidebarOpen()).toBe(true);
  });

  test('a localStorage that throws on read is survivable', () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage blocked');
    });
    expect(() => migrateLegacySidebarOpen()).not.toThrow();
    expect(migrateLegacySidebarOpen()).toBe(true);
    jest.restoreAllMocks();
  });

  // The end-to-end path: a real user with the old hand-rolled sidebar
  // persistence reloads the app after this change ships. HighFashionPage
  // wires this function in as usePersistentState's initialValue, exactly
  // as below — proving the actual hook call the component makes produces a
  // collapsed sidebar, not just that the migration function alone does.
  test('a stored "closed" still produces a collapsed sidebar through usePersistentState', () => {
    window.localStorage.setItem('hf2-sidebar', 'closed');
    const { result } = renderHook(() => usePersistentState('sidebarOpen', migrateLegacySidebarOpen));
    const [sidebarOpen] = result.current;
    expect(sidebarOpen).toBe(false);
  });

  test('a stored "open" still produces an expanded sidebar through usePersistentState', () => {
    window.localStorage.setItem('hf2-sidebar', 'open');
    const { result } = renderHook(() => usePersistentState('sidebarOpen', migrateLegacySidebarOpen));
    const [sidebarOpen] = result.current;
    expect(sidebarOpen).toBe(true);
  });

  test('after the hook mounts once, the migrated value is what persists on reload', () => {
    window.localStorage.setItem('hf2-sidebar', 'closed');
    const first = renderHook(() => usePersistentState('sidebarOpen', migrateLegacySidebarOpen));
    expect(first.result.current[0]).toBe(false);

    // Simulate a reload: a fresh hook call, same storage. It should read
    // the new namespaced key this time, not re-run the legacy migration —
    // and land on the same value.
    const second = renderHook(() => usePersistentState('sidebarOpen', migrateLegacySidebarOpen));
    expect(second.result.current[0]).toBe(false);
    expect(window.localStorage.getItem('fa:sidebarOpen')).toBe('false');
  });
});
