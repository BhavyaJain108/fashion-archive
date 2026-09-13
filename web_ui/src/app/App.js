import React, { useState, useEffect } from 'react';
import LibraryPage from '../features/library/LibraryPage';
import BrandsPage from '../features/brands/BrandsPage';
import AuthPanel from '../features/auth/AuthPanel';
import HighFashionPage from '../features/high-fashion/HighFashionPage';
import { FashionArchiveAPI } from '../shared/api';
import { useRoute } from '../shared/hooks/useRoute';

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

  // 'album' and 'shared' are routes that later phases fill in; until then
  // they render the library and the archive, which is where an unfinished
  // link should land rather than on a blank screen.
  const currentPage =
    route.page === 'brands' ? 'my-brands'
    : route.page === 'library' || route.page === 'album' ? 'favourites'
    : 'high-fashion';

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
        : page === 'favourites' ? 'library'
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
