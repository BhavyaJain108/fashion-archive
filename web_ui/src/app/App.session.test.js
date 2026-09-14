// Session restore, at the level it actually runs: App's three effects and
// the address bar they write.
//
// session.test.js tests the storage module — what a URL survives, what a
// corrupt value does — and it passes with every one of these effects
// deleted. The mount effects are the feature: reopen the last route, but
// only on a blank arrival, and without leaving an entry Back can walk into.
// Each of the four is one line, and a reviewer deleted each of them in turn
// with the whole suite staying green.
//
// The three pages are stubs. What is under test is which URL App lands on
// and what it stores, and a real HighFashionPage would bring a catalogue,
// a stream and a designer index to answer a question none of them is part
// of.
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

// Written out four times rather than through a helper: jest.mock's factory
// has to be an inline function literal, which babel-plugin-jest-hoist
// enforces at compile time.
// The archive stub carries a log-out button, because onLogout is a prop
// App hands the pages and there is no other way in to it.
jest.mock('../features/high-fashion/HighFashionPage', () => ({
  __esModule: true,
  default: (props) => {
    const R = require('react');
    return R.createElement('div', null, 'archive page',
      R.createElement('button', { onClick: props.onLogout }, 'log out'));
  },
}));
jest.mock('../features/library/LibraryPage', () => ({
  __esModule: true,
  default: () => require('react').createElement('div', null, 'library page'),
}));
jest.mock('../features/brands/BrandsPage', () => ({
  __esModule: true,
  default: () => require('react').createElement('div', null, 'brands page'),
}));
jest.mock('../features/auth/AuthPanel', () => ({
  __esModule: true,
  default: () => require('react').createElement('div', null, 'sign in'),
}));

jest.mock('../shared/api', () => ({
  FashionArchiveAPI: { getMe: jest.fn(), logout: jest.fn() },
}));

// eslint-disable-next-line import/first
import App from './App';
// eslint-disable-next-line import/first
import { SESSION_KEY } from './session';

// eslint-disable-next-line import/first
const { FashionArchiveAPI: API } = require('../shared/api');

const path = () => window.location.pathname + window.location.search;
const stored = () => window.localStorage.getItem(SESSION_KEY);

const SHOW = '/hf/yohji-yamamoto/1234/7';

beforeEach(() => {
  window.localStorage.clear();
  jest.clearAllMocks();
  API.getMe.mockResolvedValue({ email: 'test@example.test' });
  API.logout.mockResolvedValue({});
});

const arriveOn = (url) => { window.history.replaceState({}, '', url); };
const rememberLast = (url) => {
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(url));
};

test('a blank arrival reopens the last route', async () => {
  rememberLast(SHOW);
  arriveOn('/');

  render(<App />);
  await screen.findByText('archive page');

  await waitFor(() => expect(path()).toBe(SHOW));
});

test('reopening it leaves no history entry to walk back into', async () => {
  // replace, not push. A restored session is not somewhere the reader
  // navigated to, so pressing Back from it should leave the app rather than
  // bounce them to the empty archive they never asked for.
  rememberLast(SHOW);
  arriveOn('/');
  const entriesBefore = window.history.length;

  render(<App />);
  await waitFor(() => expect(path()).toBe(SHOW));

  expect(window.history.length).toBe(entriesBefore);
});

test('a URL that names a destination is left alone', async () => {
  // The reader asked for the library. Last night's show must not land on
  // top of it.
  rememberLast(SHOW);
  arriveOn('/library');

  render(<App />);
  await screen.findByText('library page');

  expect(path()).toBe('/library');
});

test('where the reader is gets stored as they go', async () => {
  // Nothing to restore here — this arrival names a show — so the only
  // effect with anything to do is the one that remembers it. Without it
  // every test above passes on a value nothing ever writes.
  arriveOn(SHOW);

  render(<App />);
  await screen.findByText('archive page');

  await waitFor(() => expect(stored()).toBe(JSON.stringify(SHOW)));
});

test('logging out forgets where the reader was', async () => {
  // The privacy defect: the last show's slug and filters are browsing
  // history, localStorage has no expiry, and nothing cleared it. On a shared
  // browser the next person to open "/" was put back into this reader's
  // last show.
  arriveOn(SHOW);

  render(<App />);
  await screen.findByText('archive page');
  await waitFor(() => expect(stored()).toBe(JSON.stringify(SHOW)));

  fireEvent.click(screen.getByText('log out'));

  await waitFor(() => expect(stored()).toBeNull());
});
