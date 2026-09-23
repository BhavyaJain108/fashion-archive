import ApiClient from './client';

// The owner's view of the scrapers. Every call here returns 403 for anyone whose
// email is not in ADMIN_EMAILS on the server, so the page shows a plain notice
// rather than an error when someone else opens the URL.
//
// Two shapes only: a read and a command. Both answer with the same envelope —
// `{forbidden: true}`, `{error: '...'}`, or the server's body — so every page
// handles one thing.
async function envelope(response, fallback) {
  ApiClient.checkAuth(response);
  if (response.status === 403) return { forbidden: true };
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.success) {
    return { error: data.error || fallback || `Request failed (${response.status})`, code: data.code };
  }
  return data;
}

// The version of each answer this tab last received, by path. Sent back with the
// next request for the same path; the server answers 304 and no body when nothing
// has changed, which is most minutes. Held in memory only — a new tab asks fresh.
const versions = new Map();

async function read(path, fallback) {
  const headers = {};
  const known = versions.get(path);
  if (known) headers['If-None-Match'] = known;
  let response;
  try {
    response = await fetch(`${ApiClient.BASE_URL}/api/dev/${path}`, {
      credentials: 'include',
      headers,
    });
  } catch (e) {
    // The network, not the API: without this the page sat on "checking for
    // changes…" for ever over numbers of unknown age.
    return { error: `could not reach the API (${e.message})` };
  }
  if (response.status === 304) return { notModified: true };
  const tag = response.headers.get('ETag');
  if (tag && response.ok) versions.set(path, tag);
  return envelope(response, fallback);
}

async function command(path, fallback, body) {
  let response;
  try {
    response = await fetch(`${ApiClient.BASE_URL}/api/dev/${path}`, {
      method: 'POST',
      credentials: 'include',
      ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
    });
  } catch (e) {
    return { error: `could not reach the API (${e.message})` };
  }
  return envelope(response, fallback);
}

const brand = (domain) => `brands/${encodeURIComponent(domain)}`;

export class DevEndpoints {
  static getOverview() {
    return read('overview');
  }

  static getBrand(domain) {
    return read(brand(domain));
  }

  // Its own call because the server has to read that brand's whole catalogue to
  // answer it — 35 MB for the largest. Asked per brand, on demand.
  static getPhotographs(domain) {
    return read(`${brand(domain)}/photographs`, 'Could not count');
  }

  // Separately, because it reads the request ledger — hundreds of small objects —
  // and the brand page should not wait on it to paint.
  static getHosts(domain) {
    return read(`${brand(domain)}/hosts`);
  }

  static getRunLog(domain, runId) {
    return read(`${brand(domain)}/runs/${encodeURIComponent(runId)}/log`, 'No log for this run');
  }

  // `filters` is {facet: [values]} — colour, size, material, category, tag, stock,
  // sale — plus sizedInStock, priceMin and priceMax. Repeated params, so a facet
  // with several values is ?size=S&size=M.
  static getProducts(domain, {
    offset = 0, limit = 100, q = '', status = 'live', run = null,
    filters = {}, sizedInStock = false, priceMin = null, priceMax = null,
  } = {}) {
    const params = new URLSearchParams({ offset, limit, status });
    if (q) params.set('q', q);
    if (run) params.set('run', run);
    Object.entries(filters).forEach(([facet, values]) => (values || []).forEach((v) => params.append(facet, v)));
    if (sizedInStock) params.set('sized_in_stock', '1');
    if (priceMin != null && priceMin !== '') params.set('price_min', priceMin);
    if (priceMax != null && priceMax !== '') params.set('price_max', priceMax);
    return read(`${brand(domain)}/products?${params}`);
  }

  // What each run added and removed. Reads the catalogue, so asked on its own.
  static getChanges(domain) {
    return read(`${brand(domain)}/changes`);
  }

  static getCosts() {
    return read('costs');
  }

  // Commands. Each is an edit to the schedule object the daemon already reads,
  // so nothing here talks to a worker directly.
  static runNow(domain) {
    return command(`${brand(domain)}/run`, 'Could not schedule');
  }

  static learn(domain, retrySearched) {
    return command(`${brand(domain)}/learn`, 'Could not queue a learn run', { retry_searched: !!retrySearched });
  }

  static pause(domain) {
    return command(`${brand(domain)}/pause`, 'Could not pause');
  }

  static resume(domain) {
    return command(`${brand(domain)}/resume`, 'Could not resume');
  }

  // Take a dead worker's claim off a brand now, rather than when it goes stale.
  static release(domain) {
    return command(`${brand(domain)}/release`, 'Could not release');
  }

  // One command over several brands. The answer names what happened to each.
  static batch(action, domains) {
    return command('batch', 'Could not apply to the selection', { action, domains });
  }

  static addBrand(domain, displayName, show) {
    return command('brands', 'Could not add the brand', { domain, display_name: displayName, show });
  }

  // The owner's notes: what to change next, kept with the archive.
  static getNotes() {
    return read('notes');
  }

  static addNote(text) {
    return command('notes', 'Could not save the note', { text });
  }

  static setNoteDone(id, done) {
    return command(`notes/${encodeURIComponent(id)}`, 'Could not update the note', { done });
  }

  static deleteNote(id) {
    return command(`notes/${encodeURIComponent(id)}`, 'Could not remove the note', { delete: true });
  }
}

export default DevEndpoints;
