# Fashion Archive — web client

React app, served as static files by Cloudflare Pages in production.

## Running locally

The backend must be running first (see `scripts/test_db.sh` and `backend/app.py`).

```bash
npm install
REACT_APP_API_URL=http://localhost:8099 npm start
```

`REACT_APP_API_URL` is baked in at compile time, so changing it needs a restart
of the dev server, not just a page reload.

## Use the same hostname for both servers

Run the frontend and the API on the same hostname — `localhost` for both, or
`127.0.0.1` for both. Do not mix them.

The session cookie is `SameSite=Lax`. The browser treats `localhost` and
`127.0.0.1` as different sites, so a frontend on `localhost:3000` talking to an
API on `127.0.0.1:8099` is a cross-site request and the cookie is never sent
back. Login returns 200 and every request after it is a 401, which looks like a
broken session rather than a configuration mistake.

The same rule is what shapes production: the site and the API are subdomains of
one registrable domain (`premiumpropogandafashion.studio` and
`api.premiumpropogandafashion.studio`), which makes them same-site and lets one
cookie cover both.

## Authentication

There is no token in this codebase. The session lives in an HttpOnly cookie the
browser attaches automatically and JavaScript cannot read, so an XSS bug cannot
exfiltrate it.

- Every request in `services/api.js` sends `credentials: 'include'`.
- `App.js` calls `GET /api/auth/me` once on load; a 200 means the user is
  already signed in.
- `FashionArchiveAPI.onUnauthorized` is the single place a 401 is handled.
- `auth/AuthPanel.js` holds all five signed-out screens.
