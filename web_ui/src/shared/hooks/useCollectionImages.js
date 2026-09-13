import { useCallback, useEffect, useRef, useState } from 'react';
import { FashionArchiveAPI } from '../api';

// The looks of one collection, streamed, without ever taking the previous
// collection off the screen first.
//
//   useCollectionImages(collection)
//     -> { images, expectedCount, loading, isStale, error, imagesKey, reload }
//
// The rule this hook exists for: a request for a new collection never
// clears `images`. What is on screen stays on screen until there is
// something new to put there — the first image of the new stream, or a
// stream that completed and said there are none. A failure puts nothing
// there at all, so a reader whose connection blipped can still look at the
// show they had.
//
// `isStale` is how the page knows the difference. It means "what you are
// looking at is not what you asked for yet" — a cue to dim or mark, never
// an instruction to render nothing.
//
// The four values move together and are meaningless apart — an image list
// with another collection's expected count describes nothing — so they are
// one state object, swapped in one commit, rather than four useStates that
// can be observed half-updated.
const EMPTY = {
  images: [],
  imagesKey: null,
  expectedCount: 0,
  loading: false,
  error: null,
};

// Collections are identified by url: it is what the stream is keyed on, and
// it is stable across the several different objects that describe the same
// show — the row in the list and the row a deep link refetches are never
// the same reference. Keying on identity would refetch on every one of
// those and flicker the viewer for nothing.
const keyOf = (collection) => (collection && collection.url) || null;

export function useCollectionImages(collection) {
  const key = keyOf(collection);
  const [state, setState] = useState(EMPTY);
  // reload() is a request for the same key, so the key alone cannot
  // retrigger the effect. Bumping a counter is the whole mechanism.
  const [reloadNonce, setReloadNonce] = useState(0);

  // The one request whose results are allowed to land. Clicking through
  // shows faster than a stream completes leaves the old ones running; their
  // callbacks keep firing, and without this they wrote a previous show's
  // photographs into the show on screen. Everything a stream does is
  // guarded on still being the current one.
  const live = useRef(null);

  useEffect(() => {
    if (!key) {
      // No show open. This is the reader leaving the viewer rather than
      // asking for something else, so the screen is cleared — there is
      // nothing "not yet arrived" to keep it warm for. EMPTY is a constant
      // so this is an Object.is no-op when there was nothing there anyway.
      if (live.current) live.current.abort();
      live.current = null;
      setState(EMPTY);
      return undefined;
    }

    const controller = new AbortController();
    live.current = controller;
    const isCurrent = () => live.current === controller;

    // Note what is not set here: `images` and `imagesKey`. That omission is
    // the feature. `expectedCount` does reset, because it describes the
    // collection being asked for and the old collection's count must not be
    // read as this one's.
    setState(prev => ({ ...prev, loading: true, error: null, expectedCount: 0 }));

    // Images arrive in completion order and are held in look order, so the
    // sparse array is the accumulator and the dense copy is what renders.
    const paths = [];
    let landed = false;

    FashionArchiveAPI.streamCollectionImages(key, {
      signal: controller.signal,
      onMeta: (metaEvent) => {
        if (!isCurrent()) return;
        setState(prev => ({ ...prev, expectedCount: metaEvent.count || 0 }));
      },
      onImage: (img) => {
        if (!isCurrent()) return;
        paths[img.index] = img.path;
        landed = true;
        // The swap: the first image of the new collection is the first
        // moment there is something new to show, so it is the moment the
        // old collection leaves and `isStale` goes false.
        setState(prev => ({
          ...prev,
          images: paths.filter(Boolean),
          imagesKey: key,
          loading: false,
        }));
      },
    }).then(() => {
      if (!isCurrent()) return;
      // A stream that finished having sent nothing is an answer — this show
      // has no looks — not a failure. It is committed, because keeping the
      // previous show's photographs under this show's name is a lie the
      // status bar would tell. Only an error keeps them.
      setState(prev => (landed
        ? { ...prev, loading: false }
        : { ...prev, images: [], imagesKey: key, loading: false }));
    }).catch((error) => {
      // Superseded by a newer request, which has already taken over the
      // state. Nothing to report and nothing to clear.
      if (error && error.name === 'AbortError') return;
      if (!isCurrent()) return;
      console.error('Failed to load images:', error);
      // `images` survives deliberately. The previous collection is still
      // worth looking at, and `isStale` stays true to say it is not the one
      // that was asked for.
      setState(prev => ({ ...prev, loading: false, error }));
    });

    return () => {
      controller.abort();
      // Cleanup runs before the next effect, so clearing the ref here can
      // never clear a newer request's claim. It is what makes every late
      // callback above return at isCurrent() — including after unmount,
      // when there is no next effect to replace it.
      live.current = null;
    };
  }, [key, reloadNonce]);

  const reload = useCallback(() => { setReloadNonce(n => n + 1); }, []);

  return {
    images: state.images,
    expectedCount: state.expectedCount,
    loading: state.loading,
    error: state.error,
    // True from the render on which a different collection is asked for
    // until that collection's first image lands. With nothing selected
    // there is nothing to be stale against.
    isStale: Boolean(key) && state.imagesKey !== key,
    // Which collection `images` belongs to. The page owns the current look
    // — the URL, the keyboard, the strip and the grid all drive it — so the
    // hook cannot reset it, and this is how it says when to: look 1 of a
    // new show, and not on a reload of the same one.
    imagesKey: state.imagesKey,
    reload,
  };
}

export default useCollectionImages;
