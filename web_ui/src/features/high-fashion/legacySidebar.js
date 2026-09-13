// Migration for the sidebar's pre-usePersistentState storage.
//
// Before Task 3, HighFashionPage hand-rolled its own persistence: a bare
// (non-JSON) string at the bare (non-namespaced) key `hf2-sidebar`, holding
// literally 'open' or 'closed'. Anyone who has toggled the sidebar already
// has one of those two strings sitting in their browser.
//
// usePersistentState always reads/writes under the `fa:` prefix and speaks
// JSON, so it can never see that old key on its own. This is the one-time
// bridge: read the legacy value, if any, and translate it into the boolean
// usePersistentState's lazy initialiser expects. It only runs when the new
// key (`fa:sidebarOpen`) has nothing stored yet — usePersistentState's write
// effect fires on first mount, so the new key gets a value immediately and
// this function is never consulted again after that.
const LEGACY_KEY = 'hf2-sidebar';

export function migrateLegacySidebarOpen() {
  try {
    const legacy = window.localStorage.getItem(LEGACY_KEY);
    if (legacy === 'closed') return false;
    if (legacy === 'open') return true;
  } catch (e) {
    // Private-mode/blocked storage throws on read; fall through to the
    // same default a first-time visitor gets.
  }
  return true;
}

export default migrateLegacySidebarOpen;
