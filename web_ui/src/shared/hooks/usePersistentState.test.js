import { renderHook, act } from '@testing-library/react';
import { usePersistentState } from './usePersistentState';

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('usePersistentState', () => {
  test('returns initialValue when nothing is stored', () => {
    const { result } = renderHook(() => usePersistentState('widget', 'default'));
    expect(result.current[0]).toBe('default');
  });

  test('returns the stored value when there is one', () => {
    window.localStorage.setItem('fa:widget', JSON.stringify('stored'));
    const { result } = renderHook(() => usePersistentState('widget', 'default'));
    expect(result.current[0]).toBe('stored');
  });

  test('writing updates both the state and localStorage', () => {
    const { result } = renderHook(() => usePersistentState('widget', 'default'));
    act(() => {
      result.current[1]('updated');
    });
    expect(result.current[0]).toBe('updated');
    expect(window.localStorage.getItem('fa:widget')).toBe(JSON.stringify('updated'));
  });

  test('the functional-update form works', () => {
    const { result } = renderHook(() => usePersistentState('counter', 1));
    act(() => {
      result.current[1](v => v + 1);
    });
    expect(result.current[0]).toBe(2);
    expect(window.localStorage.getItem('fa:counter')).toBe(JSON.stringify(2));
  });

  test('initialValue may be a function (lazy initialiser)', () => {
    const init = jest.fn(() => 'lazy');
    const { result } = renderHook(() => usePersistentState('lazy-key', init));
    expect(result.current[0]).toBe('lazy');
    expect(init).toHaveBeenCalledTimes(1);
  });

  test('a corrupt stored value falls back to initialValue instead of throwing', () => {
    window.localStorage.setItem('fa:corrupt', '{not json');
    let result;
    expect(() => {
      ({ result } = renderHook(() => usePersistentState('corrupt', 'fallback')));
    }).not.toThrow();
    expect(result.current[0]).toBe('fallback');
  });

  test('a localStorage that throws is survivable', () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage blocked');
    });
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage blocked');
    });

    let result;
    expect(() => {
      ({ result } = renderHook(() => usePersistentState('throws', 'fallback')));
    }).not.toThrow();
    expect(result.current[0]).toBe('fallback');

    expect(() => {
      act(() => {
        result.current[1]('updated');
      });
    }).not.toThrow();
    expect(result.current[0]).toBe('updated');
  });

  test('two hooks with different keys do not interfere', () => {
    const a = renderHook(() => usePersistentState('key-a', 'A'));
    const b = renderHook(() => usePersistentState('key-b', 'B'));

    act(() => {
      a.result.current[1]('A2');
    });

    expect(a.result.current[0]).toBe('A2');
    expect(b.result.current[0]).toBe('B');
    expect(window.localStorage.getItem('fa:key-a')).toBe(JSON.stringify('A2'));
    expect(window.localStorage.getItem('fa:key-b')).toBe(JSON.stringify('B'));
  });
});
