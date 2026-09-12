import React, { useState, useEffect } from 'react';
import FavouritesPanel from './components/FavouritesPanel';
import MyBrandsPanel from './components/MyBrandsPanel';
import AuthPanel from './auth/AuthPanel';
import HighFashionV2 from './components/HighFashionV2';
import { FashionArchiveAPI } from './services/api';

// The shell: decide whether anyone is signed in, and which of the three pages
// to show. Nothing else.
//
// It used to hold the whole archive as well — seasons, collections, the loaded
// images, the current look, gallery and zoom modes, a video window, and a
// window-level key handler for the arrows. That was the previous generation of
// this UI, when App owned the data and the panels drew it. HighFashionV2 owns
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

  const [currentPage, setCurrentPage] = useState('high-fashion');

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

    // Drop token and status out of the address bar so a reset token is not
    // left sitting in history or copied out of the URL bar.
    if (params.toString()) {
      window.history.replaceState({}, '', window.location.pathname);
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

  const handlePageSwitch = (page) => setCurrentPage(page);

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
        <HighFashionV2 {...pageProps} />
      ) : currentPage === 'my-brands' ? (
        <MyBrandsPanel {...pageProps} />
      ) : (
        <FavouritesPanel {...pageProps} />
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
