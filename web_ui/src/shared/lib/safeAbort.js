// Abort a controller without letting anything it triggers escape.
//
// controller.abort() dispatches its `abort` event synchronously. If a listener
// the browser registered for an in-flight fetch throws — Chrome does this for a
// body stream that is mid-read — the exception is reported with abort() at the
// top of the stack, and in development the overlay presents it as an
// application error. A cleanup that aborts a live stream must never take the
// commit phase down with it.
export function safeAbort(controller) {
  if (!controller) return;
  try {
    controller.abort();
  } catch (e) {
    // Already aborted, or a listener objected. Either way the request is done.
  }
}

export default safeAbort;
