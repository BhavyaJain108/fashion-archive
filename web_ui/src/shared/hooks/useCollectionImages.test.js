import { renderHook, act } from '@testing-library/react';
import { FashionArchiveAPI } from '../api';
import { useCollectionImages } from './useCollectionImages';

const A = { collection_id: '1', url: 'https://example.test/show/a' };
const B = { collection_id: '2', url: 'https://example.test/show/b' };
const C = { collection_id: '3', url: 'https://example.test/show/c' };

// Every call the hook makes, each with the handlers it passed and the two
// ends of the promise it is waiting on. The stream is driven by hand from
// the tests — onMeta, onImage, then resolve or reject — which is the only
// way to observe the states that exist *between* those events, and those
// states are what this hook is for.
let calls;

function driveStream() {
  calls = [];
  jest.spyOn(FashionArchiveAPI, 'streamCollectionImages')
    .mockImplementation((url, handlers = {}) => {
      let resolve;
      let reject;
      const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
      calls.push({ url, handlers, resolve, reject });
      return promise;
    });
  return calls;
}

// The hook's own catch logs. Tests that fail a stream on purpose do not
// need the noise, and a silent spy also proves nothing else is logging.
let errorLog;

beforeEach(() => {
  driveStream();
  errorLog = jest.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  jest.restoreAllMocks();
});

const meta = (call, count) => act(() => { call.handlers.onMeta({ type: 'meta', count }); });
const image = (call, index, path) =>
  act(() => { call.handlers.onImage({ type: 'image', index, path }); });
const done = (call) => act(async () => { call.resolve({ type: 'done' }); });
const fail = (call, error) => act(async () => { call.reject(error); });
// The 'done' SSE event, fired mid-stream — before the returned promise ever
// settles. This is the signal the hook was discarding: a look that failed to
// download does not reject the promise, it is just skipped, so the stream
// can say "no more are coming" long before (or even without) `done()` below
// ever resolving anything.
const streamDone = (call) => act(() => { call.handlers.onDone({ type: 'done' }); });

function mount(initial) {
  return renderHook(({ collection }) => useCollectionImages(collection), {
    initialProps: { collection: initial },
  });
}

describe('useCollectionImages', () => {
  test('no collection selected asks for nothing', () => {
    const { result } = mount(null);
    expect(FashionArchiveAPI.streamCollectionImages).not.toHaveBeenCalled();
    expect(result.current.images).toEqual([]);
    expect(result.current.loading).toBe(false);
    expect(result.current.isStale).toBe(false);
    expect(result.current.expectedCount).toBe(0);
    expect(result.current.error).toBe(null);
  });

  test('selecting a collection when nothing is loaded shows nothing, loading', () => {
    const { result } = mount(A);
    expect(FashionArchiveAPI.streamCollectionImages).toHaveBeenCalledTimes(1);
    expect(calls[0].url).toBe(A.url);
    expect(result.current.images).toEqual([]);
    expect(result.current.loading).toBe(true);
    expect(result.current.expectedCount).toBe(0);
  });

  test('meta sets expectedCount before any image lands', () => {
    const { result } = mount(A);
    meta(calls[0], 42);
    expect(result.current.expectedCount).toBe(42);
    expect(result.current.images).toEqual([]);
    expect(result.current.loading).toBe(true);
  });

  test('the first image ends the loading state and is no longer stale', () => {
    const { result } = mount(A);
    image(calls[0], 0, 'a/look-01.jpg');
    expect(result.current.images).toEqual(['a/look-01.jpg']);
    expect(result.current.loading).toBe(false);
    expect(result.current.isStale).toBe(false);
    expect(result.current.imagesKey).toBe(A.url);
  });

  test('images arriving out of order are held in look order', () => {
    const { result } = mount(A);
    image(calls[0], 2, 'a/look-03.jpg');
    image(calls[0], 0, 'a/look-01.jpg');
    image(calls[0], 1, 'a/look-02.jpg');
    expect(result.current.images)
      .toEqual(['a/look-01.jpg', 'a/look-02.jpg', 'a/look-03.jpg']);
  });

  // The complaint this hook exists to answer.
  test('a new collection does not take the old one off the screen', async () => {
    const { result, rerender } = mount(A);
    image(calls[0], 0, 'a/look-01.jpg');
    await done(calls[0]);
    expect(result.current.images).toEqual(['a/look-01.jpg']);

    rerender({ collection: B });

    expect(calls).toHaveLength(2);
    expect(calls[1].url).toBe(B.url);
    expect(result.current.images).toEqual(['a/look-01.jpg']);   // still A's
    expect(result.current.isStale).toBe(true);
    expect(result.current.loading).toBe(true);
    expect(result.current.expectedCount).toBe(0);
  });

  test('the first image of the new collection replaces the old one', async () => {
    const { result, rerender } = mount(A);
    image(calls[0], 0, 'a/look-01.jpg');
    await done(calls[0]);

    rerender({ collection: B });
    image(calls[1], 0, 'b/look-01.jpg');

    expect(result.current.images).toEqual(['b/look-01.jpg']);
    expect(result.current.isStale).toBe(false);
    expect(result.current.loading).toBe(false);
    expect(result.current.imagesKey).toBe(B.url);
  });

  test('a failed load leaves the previous collection on screen', async () => {
    const { result, rerender } = mount(A);
    image(calls[0], 0, 'a/look-01.jpg');
    await done(calls[0]);

    rerender({ collection: B });
    const boom = new Error('the network blipped');
    await fail(calls[1], boom);

    expect(result.current.images).toEqual(['a/look-01.jpg']);   // not destroyed
    expect(result.current.error).toBe(boom);
    expect(result.current.isStale).toBe(true);
    expect(result.current.loading).toBe(false);
    expect(errorLog).toHaveBeenCalled();
  });

  test('a failed first load leaves an empty screen and an error', async () => {
    const { result } = mount(A);
    await fail(calls[0], new Error('nope'));
    expect(result.current.images).toEqual([]);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeInstanceOf(Error);
  });

  test('an error is cleared by the next request', async () => {
    const { result, rerender } = mount(A);
    await fail(calls[0], new Error('nope'));
    rerender({ collection: B });
    expect(result.current.error).toBe(null);
  });

  // B's stream is left running and answers late. Its images must be dropped
  // on the floor, not merged into C's — two shows sharing one strip of
  // photographs is the bug the guard was written for.
  test('B then C: C wins and B arriving late is discarded', async () => {
    const { result, rerender } = mount(B);
    rerender({ collection: C });

    expect(calls).toHaveLength(2);
    expect(calls[1].url).toBe(C.url);

    image(calls[1], 0, 'c/look-01.jpg');
    expect(result.current.images).toEqual(['c/look-01.jpg']);

    // B, late.
    meta(calls[0], 99);
    image(calls[0], 1, 'b/look-02.jpg');
    image(calls[0], 0, 'b/look-01.jpg');
    await done(calls[0]);

    expect(result.current.images).toEqual(['c/look-01.jpg']);
    expect(result.current.images).not.toContain('b/look-01.jpg');
    expect(result.current.images).not.toContain('b/look-02.jpg');
    expect(result.current.expectedCount).not.toBe(99);
    expect(result.current.imagesKey).toBe(C.url);
    expect(result.current.isStale).toBe(false);
  });

  test('the superseded stream is aborted', () => {
    const { rerender } = mount(B);
    expect(calls[0].handlers.signal.aborted).toBe(false);
    rerender({ collection: C });
    expect(calls[0].handlers.signal.aborted).toBe(true);
  });

  test('an abort does not surface as an error', async () => {
    const { result, rerender } = mount(B);
    rerender({ collection: C });
    const aborted = new Error('aborted');
    aborted.name = 'AbortError';
    await fail(calls[0], aborted);
    expect(result.current.error).toBe(null);
    expect(errorLog).not.toHaveBeenCalled();
  });

  test('the same collection again is not refetched', () => {
    const { result, rerender } = mount(A);
    image(calls[0], 0, 'a/look-01.jpg');
    // A different object for the same show — a row re-fetched by a deep link
    // is never the same reference as the row in the list.
    rerender({ collection: { ...A } });
    expect(FashionArchiveAPI.streamCollectionImages).toHaveBeenCalledTimes(1);
    expect(result.current.images).toEqual(['a/look-01.jpg']);
    expect(result.current.isStale).toBe(false);
  });

  test('reload refetches the collection without blanking it', async () => {
    const { result } = mount(A);
    image(calls[0], 0, 'a/look-01.jpg');
    await done(calls[0]);

    act(() => { result.current.reload(); });

    expect(calls).toHaveLength(2);
    expect(calls[1].url).toBe(A.url);
    expect(result.current.images).toEqual(['a/look-01.jpg']);
    expect(result.current.loading).toBe(true);
    // Same collection, so nothing on screen belongs to anyone else.
    expect(result.current.isStale).toBe(false);

    image(calls[1], 0, 'a/look-01b.jpg');
    expect(result.current.images).toEqual(['a/look-01b.jpg']);
  });

  // A stream that finishes having sent nothing is an answer, not a failure:
  // this show has no looks. Keeping the previous show's photographs under
  // the new show's name would be a lie the status bar tells.
  test('a stream that completes with no images commits the empty result', async () => {
    const { result, rerender } = mount(A);
    image(calls[0], 0, 'a/look-01.jpg');
    await done(calls[0]);

    rerender({ collection: B });
    await done(calls[1]);

    expect(result.current.images).toEqual([]);
    expect(result.current.isStale).toBe(false);
    expect(result.current.loading).toBe(false);
  });

  test('clearing the selection empties the viewer and aborts the stream', () => {
    const { result, rerender } = mount(A);
    image(calls[0], 0, 'a/look-01.jpg');

    rerender({ collection: null });

    expect(result.current.images).toEqual([]);
    expect(result.current.expectedCount).toBe(0);
    expect(result.current.loading).toBe(false);
    expect(result.current.isStale).toBe(false);
    expect(calls[0].handlers.signal.aborted).toBe(true);
  });

  // Named for what it actually pins. It used to be called "...and sets no
  // state afterwards", which it never checked: after unmount RTL freezes
  // `result.current`, and React 18 makes setState on an unmounted component
  // a silent no-op, so deleting `live.current = null` from the cleanup left
  // every assertion here green. Neither the frozen snapshot nor a
  // console.error spy can see a late write, and the hook exposes no seam
  // that can. What is real is that the request is aborted and that the
  // late callbacks are harmless, so that is what the name claims.
  test('unmounting mid-stream aborts the request', () => {
    const { result, unmount } = mount(A);
    meta(calls[0], 10);
    const before = result.current.images;

    unmount();
    expect(calls[0].handlers.signal.aborted).toBe(true);

    // Late callbacks from a stream nobody is listening to any more.
    expect(() => {
      calls[0].handlers.onImage({ type: 'image', index: 0, path: 'a/look-01.jpg' });
      calls[0].handlers.onMeta({ type: 'meta', count: 3 });
    }).not.toThrow();
    expect(result.current.images).toBe(before);
    expect(errorLog).not.toHaveBeenCalled();
  });

  // Which collection the photographs on screen belong to, as an object and
  // not just a url. Favourites are written against it: a star is about the
  // photograph the reader is looking at, and during the stale window that
  // is not the collection that was asked for.
  describe('imagesCollection', () => {
    test('is null while nothing has landed', () => {
      const { result } = mount(A);
      expect(result.current.imagesCollection).toBe(null);
      meta(calls[0], 12);
      expect(result.current.imagesCollection).toBe(null);
    });

    test('is the collection whose first image landed', () => {
      const { result } = mount(A);
      image(calls[0], 0, 'a/look-01.jpg');
      expect(result.current.imagesCollection).toBe(A);
    });

    test('stays on the show still being looked at while the next one loads',
      async () => {
        const { result, rerender } = mount(A);
        image(calls[0], 0, 'a/look-01.jpg');
        await done(calls[0]);

        rerender({ collection: B });

        expect(result.current.isStale).toBe(true);
        expect(result.current.images).toEqual(['a/look-01.jpg']);
        // The looks on screen are A's, so this is A's — not the B that was
        // asked for.
        expect(result.current.imagesCollection).toBe(A);

        image(calls[1], 0, 'b/look-01.jpg');
        expect(result.current.imagesCollection).toBe(B);
      });

    // The window a failed load opens never closes on its own: imagesKey
    // stays on the old show forever. Anything keyed on the requested
    // collection is wrong for as long as the reader sits there.
    test('stays on the show still being looked at after a failed load', async () => {
      const { result, rerender } = mount(A);
      image(calls[0], 0, 'a/look-01.jpg');
      await done(calls[0]);

      rerender({ collection: B });
      await fail(calls[1], new Error('the network blipped'));

      expect(result.current.isStale).toBe(true);
      expect(result.current.imagesCollection).toBe(A);
    });

    test('a stream that completed empty commits the collection it emptied for',
      async () => {
        const { result, rerender } = mount(A);
        image(calls[0], 0, 'a/look-01.jpg');
        await done(calls[0]);

        rerender({ collection: B });
        await done(calls[1]);

        expect(result.current.images).toEqual([]);
        expect(result.current.imagesCollection).toBe(B);
      });

    // A deep link refetches the open show and hands back a different object
    // for the same url, carrying fields the list row did not have —
    // season_url among them, which a favourite write needs. Once the images
    // on screen are that show's, the freshest object for it is the answer.
    test('upgrades to the newest object for the same show', () => {
      const { result, rerender } = mount(A);
      image(calls[0], 0, 'a/look-01.jpg');

      const fuller = { ...A, season_url: 'https://example.test/season/a' };
      rerender({ collection: fuller });

      expect(FashionArchiveAPI.streamCollectionImages).toHaveBeenCalledTimes(1);
      expect(result.current.imagesCollection).toBe(fuller);
    });

    test('is null once the selection is cleared', () => {
      const { result, rerender } = mount(A);
      image(calls[0], 0, 'a/look-01.jpg');
      rerender({ collection: null });
      expect(result.current.imagesCollection).toBe(null);
    });
  });

  // A collection's stream can skip a look — the API logs an `image_error`
  // and moves on rather than failing the whole download — so `expectedCount`
  // can stay permanently above `images.length` even though nothing else is
  // ever coming. Nothing before this flag distinguished "still arriving"
  // from "finished, and this is all there is"; `loading` cannot do it,
  // because it clears on the FIRST image, not the last.
  describe('streamComplete', () => {
    test('starts false', () => {
      const { result } = mount(A);
      expect(result.current.streamComplete).toBe(false);
    });

    // The defect this flag exists to fix: 12 of 38 land, one look's
    // download failed, and the stream still calls onDone — normally,
    // because a skipped look never rejects the promise. That call alone,
    // before the promise it returns has settled, is what must flip the
    // flag; nothing here ever resolves or rejects calls[0].
    test('onDone marks the stream complete, ahead of the promise settling', () => {
      const { result } = mount(A);
      meta(calls[0], 38);
      for (let i = 0; i < 12; i++) image(calls[0], i, `a/look-${i}.jpg`);
      expect(result.current.streamComplete).toBe(false);

      streamDone(calls[0]);

      expect(result.current.streamComplete).toBe(true);
      expect(result.current.images).toHaveLength(12);
      expect(result.current.expectedCount).toBe(38);
    });

    // The existing behaviour a stream mid-flight relies on: with no onDone
    // yet, there is nothing to say the rest is not still coming.
    test('stays false while the stream is still running', () => {
      const { result } = mount(A);
      meta(calls[0], 38);
      image(calls[0], 0, 'a/look-01.jpg');
      expect(result.current.streamComplete).toBe(false);
    });

    // A failed stream is also an answer — this is all there is going to
    // be — not a permanent "arriving". Left unset, the defect this flag
    // fixes would apply to every failed load as well as every skipped look.
    test('a failed stream marks complete rather than leaving it arriving forever', async () => {
      const { result } = mount(A);
      image(calls[0], 0, 'a/look-01.jpg');
      await fail(calls[0], new Error('the network blipped'));
      expect(result.current.streamComplete).toBe(true);
    });

    // A new request is a new answer pending. Without the reset, a reload of
    // a show whose previous stream had completed would start already
    // "complete" and show its ghosts as gone before the new stream has said
    // anything at all.
    test('a new request resets the flag', () => {
      const { result, rerender } = mount(A);
      streamDone(calls[0]);
      expect(result.current.streamComplete).toBe(true);

      rerender({ collection: B });
      expect(result.current.streamComplete).toBe(false);
    });

    // The guard this hook exists for, applied to the new signal: B is
    // superseded by C, and B's stream answering late — however it answers —
    // must never mark C's request complete. Aborting to pick another show is
    // not "this show has finished loading".
    test('an aborted request does not mark the superseding request complete', async () => {
      const { result, rerender } = mount(B);
      rerender({ collection: C });

      // B, late: a done event fired after B lost the race.
      streamDone(calls[0]);
      expect(result.current.streamComplete).toBe(false);

      // And B's promise itself, settling as an abort.
      const aborted = new Error('aborted');
      aborted.name = 'AbortError';
      await fail(calls[0], aborted);
      expect(result.current.streamComplete).toBe(false);

      // C is still genuinely running.
      image(calls[1], 0, 'c/look-01.jpg');
      expect(result.current.streamComplete).toBe(false);
    });
  });
});
