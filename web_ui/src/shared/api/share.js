import ApiClient from './client';

// Share links. Minting and revoking need a session; resolving does not, and
// deliberately skips checkAuth so an anonymous viewer is never bounced into
// the sign-in flow by a 401 that was never theirs.
export class ShareEndpoints {
  static async mintShare(kind, target) {
    const response = await fetch(`${ApiClient.BASE_URL}/api/share`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, target }),
    });
    ApiClient.checkAuth(response);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.token) throw new Error(data.error || `Share failed (${response.status})`);
    return data.token;
  }

  static async revokeShare(token) {
    const response = await fetch(`${ApiClient.BASE_URL}/api/share/${encodeURIComponent(token)}`, {
      method: 'DELETE', credentials: 'include',
    });
    ApiClient.checkAuth(response);
    return response.ok;
  }

  static async resolveShare(token) {
    const response = await fetch(`${ApiClient.BASE_URL}/api/s/${encodeURIComponent(token)}`);
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`Could not open this link (${response.status})`);
    return response.json();
  }

  static shareUrl(token) {
    return `${window.location.origin}/s/${token}`;
  }
}

export default ShareEndpoints;
