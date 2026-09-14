import { pendingLooks } from './pendingLooks';

// The number the thumbnail strip draws as empty slots and the number the
// status bar turns into the word "arriving". One function, because they are
// one sentence and used to be two formulas that happened to agree.

test('what has been promised and not yet arrived', () => {
  expect(pendingLooks({ imagesLength: 12, expectedCount: 38 })).toBe(26);
});

test('nothing outstanding once everything promised has landed', () => {
  expect(pendingLooks({ imagesLength: 38, expectedCount: 38 })).toBe(0);
});

test('no meta yet means nothing has been promised', () => {
  expect(pendingLooks({ imagesLength: 0, expectedCount: 0 })).toBe(0);
});

// A completed stream that delivered fewer than it promised. A look whose
// download failed is logged and skipped, and the stream finishes normally —
// so without this the strip pulsed empty slots and the bar said "arriving"
// forever, on a stream that ended minutes ago.
test('a completed stream is owed nothing, whatever it promised', () => {
  expect(pendingLooks({ imagesLength: 12, expectedCount: 38, streamComplete: true }))
    .toBe(0);
});

// The stale window. `expectedCount` is already the show being fetched —
// meta arrives before the first photograph — while `imagesLength` is still
// the show on screen. The subtraction is between two different shows.
test('nothing is owed while the two numbers belong to different shows', () => {
  // The new show is longer: clamping would have drawn 26 slots behind the
  // old show's twelve thumbnails, under the new show's name.
  expect(pendingLooks({ imagesLength: 12, expectedCount: 38, isStale: true })).toBe(0);
  // And shorter, which a clamp would have hidden rather than answered.
  expect(pendingLooks({ imagesLength: 38, expectedCount: 12, isStale: true })).toBe(0);
});

test('never negative', () => {
  expect(pendingLooks({ imagesLength: 38, expectedCount: 12 })).toBe(0);
});
