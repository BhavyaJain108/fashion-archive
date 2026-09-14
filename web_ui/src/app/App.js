import React, { useState, useEffect } from 'react';
import LibraryPage from '../features/library/LibraryPage';
import AlbumGrid from '../features/library/AlbumGrid';
import BrandsPage from '../features/brands/BrandsPage';
import AuthPanel from '../features/auth/AuthPanel';
import HighFashionPage from '../features/high-fashion/HighFashionPage';
import { FashionArchiveAPI } from '../shared/api';
import { useRoute } from '../shared/hooks/useRoute';
import {
  clearSession, rememberSession, restoreSession, shouldRestore,
} from './session';

// Which page a parsed route opens. Exported because it is the one rule in
// this file worth testing on its own, and a test that restated it could not
// fail when this changed.
//
// This is the page key TopBar highlights, which is NOT always the component
// that draws: an album is inside the library, so /library/albums/7 keeps the
// key 'library' and the nav goes on saying Library, while the render below
// picks AlbumGrid off route.page. They differ here and nowhere else.
//
// 'shared' is a route a later phase fills in; until then it renders the
// archive, which is where an unfinished link should land rather than on a
// blank screen.
export function pageKeyForRoute(route) {
  if (route.page === 'brands') return 'my-brands';
  if (route.page === 'library' || route.page === 'album') return 'library';
  return 'high-fashion';
}

// The shell: decide whether anyone is signed in, and which of the three pages
// to show. Nothing else.
//
// It used to hold the whole archive as well — seasons, collections, the loaded
// images, the current look, gallery and zoom modes, a video window, and a
// window-level key handler for the arrows. That was the previous generation of
// this UI, when App owned the data and the panels drew it. HighFashionPage owns
// all of it now and takes four props, none of which was any of that state; the
// rest sat here being set and never read.
function App() {
  // Authentication State.
  //
  // There is no token here any more. The session lives in an HttpOnly cookie
  // the browser attaches automatically and this code cannot read, so the only
  // question the UI can ask is "does /api/auth/me answer?".
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [currentUser, setCurrentUser] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);

  // Set from the URL when arriving via an emailed link.
  const [authMode, setAuthMode] = useState(null);
  const [authNotice, setAuthNotice] = useState('');
  const [resetToken, setResetToken] = useState(null);

  // Which page is open is a fact about the URL, not a piece of state. Back
  // and forward work because there is nothing else to keep in step: the
  // address bar changes, useRoute re-renders, a different page draws.
  const [route, go] = useRoute();

  const currentPage = pageKeyForRoute(route);

  // Restore the session on load.
  //
  // One request. If the cookie is good the user is already in; if not they see
  // the sign-in screen. The previous version kept a copy of the user in
  // localStorage and trusted it, which meant the UI could show someone as
  // logged in after the server had already expired their session.
  useEffect(() => {
    // A 401 from anywhere in the app means the session died mid-use.
    FashionArchiveAPI.onUnauthorized = () => {
      setIsAuthenticated(false);
      setCurrentUser(null);
      setAuthNotice('Your session expired. Please sign in again.');
    };

    const params = new URLSearchParams(window.location.search);
    const onResetPage = window.location.pathname.startsWith('/reset-password');

    if (onResetPage && params.get('token')) {
      setResetToken(params.get('token'));
      setAuthMode('reset');
    } else if (params.get('verified')) {
      setAuthNotice('Email confirmed. You can sign in now.');
    } else if (params.get('error')) {
      setAuthNotice('That confirmation link is invalid or has expired.');
    }

    // Strip only the auth parameters. A reset token must not sit in history
    // where it can be copied out of the address bar — but the filters live in
    // this query string now, and wiping the lot would drop them on every load.
    const AUTH_PARAMS = ['token', 'verified', 'error'];
    if (AUTH_PARAMS.some((k) => params.has(k))) {
      AUTH_PARAMS.forEach((k) => params.delete(k));
      const rest = params.toString();
      // Deliberately not router.js's navigate(): this runs in App's own mount
      // effect, before any route consumer has mounted, and it is scrubbing a
      // secret out of the URL rather than making a navigation — there is
      // nobody to notify and nothing to canonicalize.
      window.history.replaceState(
        {}, '', window.location.pathname + (rest ? `?${rest}` : '')
      );
    }

    const restore = async () => {
      try {
        const user = await FashionArchiveAPI.getMe();
        if (user) {
          setCurrentUser(user);
          setIsAuthenticated(true);
        }
      } catch (error) {
        console.error('Session check failed:', error);
      } finally {
        setAuthChecked(true);
      }
    };

    restore();
  }, []);

  // Reopen the last session, but only on a blank arrival.
  //
  // Declared after the effect above, and so run after it, on purpose: that
  // one strips the auth parameters out of the query string, and an arrival
  // from a confirmation link — "/?verified=1" — is a blank arrival with a
  // receipt stapled to it, not a destination. By the time this runs the
  // receipt is gone and the URL says what the reader actually asked for.
  //
  // replace, never push. A restored session is not somewhere the reader
  // navigated, so it must not leave the bare "/" behind it as an entry Back
  // can walk into: pressing Back from a restored show should leave the app,
  // not bounce between the show and an empty archive. navigate() does
  // nothing at all when the stored route is the one already shown.
  //
  // A stored show that no longer resolves needs nothing here. It goes down
  // the same path a mistyped deep link does — the archive stays on screen
  // and the URL is corrected once the lookup comes back empty.
  useEffect(() => {
    if (!shouldRestore(window.location.pathname, window.location.search)) return;
    const stored = restoreSession();
    if (stored) go(stored, { replace: true });
    // Mount only. A later arrival at "/" is the reader going to the archive,
    // which is a destination like any other.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // And remember it. `route` is a stable reference while the URL is
  // unchanged — router.js caches it — so this writes once per real
  // navigation rather than once per render.
  useEffect(() => {
    rememberSession(route);
  }, [route]);

  const handleAuthenticated = (user) => {
    setCurrentUser(user);
    setIsAuthenticated(true);
    setAuthMode(null);
    setAuthNotice('');
    setResetToken(null);
  };

  const handleLogout = async () => {
    try {
      // The server clears the cookie and deletes the session row; there is no
      // client-side token to forget.
      await FashionArchiveAPI.logout();
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      // Where they were is browsing history, and it does not belong to the
      // next person at this keyboard. Cleared here rather than left to
      // expire, because localStorage does not expire: without this, opening
      // "/" on a shared browser reopened the previous user's last show.
      clearSession();
      setCurrentUser(null);
      setIsAuthenticated(false);
      setAuthMode('login');
      setAuthNotice('');
    }
  };

  // The nav writes a URL; the URL decides the page. Filters are deliberately
  // not carried across — they belong to the archive, and pinning last week's
  // year filter onto My Brands would be meaningless there.
  const handlePageSwitch = (page) => {
    go({
      page: page === 'my-brands' ? 'brands'
        : page === 'library' ? 'library'
        : 'high-fashion',
    });
  };

  // Held back until the cookie check finishes, so a returning user never sees
  // a flash of the sign-in form.
  if (!authChecked) {
    return (
      <div className="ar-page">
        <div className="ar-loading">
          <span className="headline">Loading archive</span>
        </div>
      </div>
    );
  }

  const pageProps = {
    currentPage,
    onPageSwitch: handlePageSwitch,
    currentUser,
    onLogout: handleLogout,
  };

  return (
    <div className="ar-app">
      {currentPage === 'high-fashion' ? (
        <HighFashionPage {...pageProps} />
      ) : currentPage === 'my-brands' ? (
        <BrandsPage {...pageProps} />
      ) : route.page === 'album' ? (
        <AlbumGrid {...pageProps} albumId={route.albumId} />
      ) : (
        <LibraryPage {...pageProps} />
      )}

      {!isAuthenticated && (
        <AuthPanel
          onAuthenticated={handleAuthenticated}
          initialMode={authMode}
          initialNotice={authNotice}
          resetToken={resetToken}
        />
      )}
    </div>
  );
}

export default App;
