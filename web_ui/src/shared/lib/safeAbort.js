// Abort a controller with a named reason, and let nothing it triggers escape.
//
// The reason matters: Chrome reports an unhandled rejection carrying an
// AbortError with the message of the reason it was aborted with, and the
// default is the useless "signal is aborted without reason". Naming the
// effect turns that into a pointer at the promise that was left unobserved.
export function safeAbort(controller, why = 'cleanup') {
  if (!controller) return;
  try {
    controller.abort(new DOMException(`aborted: ${why}`, 'AbortError'));
  } catch (e) {
    // Already aborted, or a listener objected. Either way the request is over.
  }
}

export default safeAbort;
