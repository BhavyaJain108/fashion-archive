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
  const response = await fetch(`${ApiClient.BASE_URL}/api/dev/${path}`, {
    credentials: 'include',
    headers,
  });
  if (response.status === 304) return { notModified: true };
  const tag = response.headers.get('ETag');
  if (tag && response.ok) versions.set(path, tag);
  return envelope(response, fallback);
}

async function command(path, fallback) {
  const response = await fetch(`${ApiClient.BASE_URL}/api/dev/${path}`, {
    method: 'POST',
    credentials: 'include',
  });
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

  static getProducts(domain, { offset = 0, limit = 100, q = '' } = {}) {
    const params = new URLSearchParams({ offset, limit });
    if (q) params.set('q', q);
    return read(`${brand(domain)}/products?${params}`);
  }

  static getCosts() {
    return read('costs');
  }

  // Commands. Each is an edit to the schedule object the daemon already reads,
  // so nothing here talks to a worker directly.
  static runNow(domain) {
    return command(`${brand(domain)}/run`, 'Could not schedule');
  }

  static pause(domain) {
    return command(`${brand(domain)}/pause`, 'Could not pause');
  }

  static resume(domain) {
    return command(`${brand(domain)}/resume`, 'Could not resume');
  }
}

export default DevEndpoints;
