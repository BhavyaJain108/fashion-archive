// The shared half of the API: the base URL, the session-expiry hook, and the
// three request shapes every endpoint is built from.
//
// Sign-in itself is a browser redirect to Google or Apple, so it is a URL
// here rather than a request; everything after it is a normal call.
//
// Every request sends `credentials: 'include'` so the browser attaches the
// session cookie. The cookie is HttpOnly, which means this file cannot read it
// and neither can anything else running on the page — that is the point. The
// previous version read a token out of localStorage and set an Authorization
// header by hand in eight separate places; any XSS on the page could have read
// that token straight out of storage.

export class ApiClient {
  static BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8081';

  // Called when the API reports the session is gone, so the app can show the
  // login screen instead of rendering empty data. Set once by App.js.
  static onUnauthorized = null;

  // Single place that notices a dead session. Handlers below call this rather
  // than each deciding for themselves what a 401 means.
  static checkAuth(response) {
    if (response.status === 401 && this.onUnauthorized) {
      this.onUnauthorized();
    }
    return response;
  }

  // ---------------------------------------------------------------- auth ---

  static async authRequest(path, body) {
    const response = await fetch(`${this.BASE_URL}/api/auth/${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, ...data };
  }

  // Who am I? A 200 here is what "remembered the user" looks like on boot.
  static async getMe() {
    const response = await fetch(`${this.BASE_URL}/api/auth/me`, {
      credentials: 'include',
    });
    if (!response.ok) return null;
    const data = await response.json();
    return data.user || null;
  }

  // Which sign-in providers the API has credentials for.
  static async getProviders() {
    const response = await fetch(`${this.BASE_URL}/api/auth/providers`, {
      credentials: 'include',
    });
    if (!response.ok) throw new Error(`providers: HTTP ${response.status}`);
    const data = await response.json();
    return data.providers || [];
  }

  // Where to send the browser to start signing in. A URL rather than a fetch:
  // the provider shows its own page and redirects back to the API's callback,
  // which sets the cookie. None of that can happen inside XHR.
  static oauthStartUrl(provider) {
    return `${this.BASE_URL}/api/auth/oauth/${encodeURIComponent(provider)}/start`;
  }

  static logout() {
    return this.authRequest('logout', {});
  }

  // Helper to call Python backend.
  //
  // `acceptErrors` returns the parsed body on a 4xx/5xx instead of throwing.
  // Some endpoints answer a failure with a reason worth showing — "quota
  // spent for today", "no API key configured" — and throwing discards it,
  // which is how a missing YOUTUBE_API_KEY in production showed up as
  // "NOT FOUND", indistinguishable from a show with no video.
  static async callPython(endpoint, data = {}, { acceptErrors = false } = {}) {
    try {
      // The session cookie rides along via credentials: 'include'.
      const headers = { 'Content-Type': 'application/json' };

      const response = await fetch(`${this.BASE_URL}${endpoint}`, {
        credentials: 'include',
        method: 'POST',
        headers: headers,
        body: JSON.stringify(data),
      });

      if (!response.ok) {
        this.checkAuth(response);
        if (acceptErrors) {
          // A body is not guaranteed on an error — a proxy 502 is HTML.
          return await response.json().catch(() => ({
            success: false,
            error: `Request failed (${response.status})`,
          }));
        }
        throw new Error(`API call failed: ${response.statusText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Python API Error:', error);
      throw error;
    }
  }

  // Consume a Server-Sent Events endpoint, invoking onEvent per frame.
  // Shared by the collection and image streams.
  static async consumeSSE(endpoint, body, onEvent, signal) {
    const response = await fetch(`${this.BASE_URL}${endpoint}`, {
      method: 'POST',
      credentials: 'include',          // session cookie, as everywhere else
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
    if (!response.ok) {
      this.checkAuth(response);
      throw new Error(`Stream failed: ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    // Aborting a fetch mid-body errors the stream. Two promises reject with the
    // abort reason: the pending read(), which the loop below catches, and the
    // reader's `closed` promise, which nothing awaits — so the rejection was
    // reported as an uncaught error every time the archive page unmounted
    // mid-stream. Observe it, and cancel the reader explicitly on abort rather
    // than leaving the browser to tear it down underneath a pending read.
    reader.closed.catch(() => {});
    const onAbort = () => { reader.cancel().catch(() => {}); };
    if (signal) {
      if (signal.aborted) onAbort();
      else signal.addEventListener('abort', onAbort, { once: true });
    }

    try {
      while (true) {
        let chunk;
        try {
          chunk = await reader.read();
        } catch (error) {
          // The caller aborted. That is a stop, not a failure: every caller
          // already treats an aborted stream as "nothing more to apply".
          if (error && error.name === 'AbortError') return;
          throw error;
        }
        const { done, value } = chunk;
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Frames are "data: {...}\n\n". Keep the trailing partial frame in
        // the buffer — a JSON payload can be split across reads.
        const frames = buffer.split('\n\n');
        buffer = frames.pop() || '';

        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith('data: ')) continue;
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch (e) {
            console.warn('Bad SSE frame:', e, line.slice(0, 120));
          }
        }
      }
    } finally {
      if (signal) signal.removeEventListener('abort', onAbort);
      try { reader.releaseLock(); } catch (e) { /* already released by cancel */ }
    }
  }

  // Image locations are already URLs — from R2 in production, from the API's
  // local store in development. The backend used to return an absolute
  // filesystem path that this turned into /api/image?path=..., asking the
  // server to read that path off disk.
  static getImageUrl(imagePath) {
    if (!imagePath) return '';
    if (/^https?:\/\//i.test(imagePath)) return imagePath;
    // Legacy value from an older cached response.
    return `${this.BASE_URL}/api/images/${imagePath.replace(/^\/+/, '')}`;
  }
}

export default ApiClient;
