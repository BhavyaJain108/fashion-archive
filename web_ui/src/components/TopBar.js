import React from 'react';
import './TopBar.css';

function TopBar({ currentPage, onPageSwitch, currentUser, onLogout }) {
  return (
    <div className="topbar">
      <div className="topbar-left">
        <span className="topbar-logo">ARCHIVE</span>
      </div>
      <div className="topbar-nav">
        <button
          className={`topbar-link ${currentPage === 'high-fashion' ? 'active' : ''}`}
          onClick={() => onPageSwitch?.('high-fashion')}
        >
          Collections
        </button>
        <button
          className={`topbar-link ${currentPage === 'favourites' ? 'active' : ''}`}
          onClick={() => onPageSwitch?.('favourites')}
        >
          Favourites
        </button>
        <button
          className={`topbar-link ${currentPage === 'my-brands' ? 'active' : ''}`}
          onClick={() => onPageSwitch?.('my-brands')}
        >
          My Brands
        </button>
      </div>
      <div className="topbar-right">
        {currentUser && (
          <>
            <span className="topbar-user">{currentUser.username}</span>
            <button className="topbar-logout" onClick={onLogout}>Logout</button>
          </>
        )}
      </div>
    </div>
  );
}

export default TopBar;
