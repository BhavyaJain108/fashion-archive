import ApiClient from './client';

// The owner's view of the scrapers. Every call here returns 403 for anyone whose
// email is not in ADMIN_EMAILS on the server, so the page shows a plain notice
// rather than an error when someone else opens the URL.
export class DevEndpoints {
  static async getOverview() {
    const response = await fetch(`${ApiClient.BASE_URL}/api/dev/overview`, {
      credentials: 'include',
    });
    ApiClient.checkAuth(response);
    if (response.status === 403) return { forbidden: true };
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) {
      return { error: data.error || `Request failed (${response.status})` };
    }
    return data;
  }

  // Its own call because the server has to read that brand's whole catalogue to
  // answer it — 35 MB for the largest. Asked per brand, on demand.
  static async getPhotographs(domain) {
    const response = await fetch(
      `${ApiClient.BASE_URL}/api/dev/brands/${encodeURIComponent(domain)}/photographs`,
      { credentials: 'include' },
    );
    ApiClient.checkAuth(response);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) return { error: data.error || 'Could not count' };
    return data;
  }
}

export default DevEndpoints;
