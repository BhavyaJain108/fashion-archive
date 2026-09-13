import { useEffect, useRef, useState } from 'react';

// Every key this hook touches lives under one prefix, so the app's
// persisted state can never collide with anything else written to the
// same origin.
const STORAGE_PREFIX = 'fa:';

function defaultSerialize(value) {
  return JSON.stringify(value);
}

function defaultDeserialize(raw) {
  return JSON.parse(raw);
}

function resolveInitial(initialValue) {
  return typeof initialValue === 'function' ? initialValue() : initialValue;
}

// A useState that persists to localStorage under a namespaced key.
//
// Signature matches useState, including the functional-update form of the
// setter: usePersistentState(key, initialValue, options?) -> [value, setValue].
// `options.serialize` / `options.deserialize` default to JSON, but can be
// swapped for something else — a caller migrating a key that already holds a
// bare (non-JSON) string can round-trip through that format instead.
//
// Reads happen exactly once, in the lazy useState initialiser, not on every
// render. Writes happen in an effect keyed on the value.
//
// Every storage call is wrapped in try/catch: a corrupt stored value (a
// half-written value from an old release) falls back to initialValue
// instead of throwing, and a localStorage that throws on read or write
// (Safari private mode throws on setItem) degrades to in-memory-only state
// rather than breaking the page.
export function usePersistentState(key, initialValue, options = {}) {
  const { serialize = defaultSerialize, deserialize = defaultDeserialize } = options;
  const storageKey = `${STORAGE_PREFIX}${key}`;

  const [value, setValue] = useState(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw === null) {
        return resolveInitial(initialValue);
      }
      return deserialize(raw);
    } catch (e) {
      // Corrupt stored value, or storage itself is unavailable — either
      // way, start from the initial value rather than throwing.
      return resolveInitial(initialValue);
    }
  });

  // Keep the latest serialize in a ref so the write effect below does not
  // need it in its dependency array. Callers commonly pass an options
  // object built inline, which is a new reference every render; depending
  // on it directly would re-run the effect (and re-hit storage) on every
  // render instead of just when the value actually changes.
  const serializeRef = useRef(serialize);
  serializeRef.current = serialize;

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, serializeRef.current(value));
    } catch (e) {
      // Storage is unavailable, blocked, or full (Safari private mode,
      // quota exceeded). The preference just will not persist; the state
      // above has already updated in memory.
    }
  }, [storageKey, value]);

  return [value, setValue];
}

export default usePersistentState;
