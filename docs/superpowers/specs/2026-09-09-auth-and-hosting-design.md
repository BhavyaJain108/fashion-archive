# Login, Userbase & Hosting — Design

**Date**: 2026-09-09
**Status**: Awaiting review
**Scope**: `backend/auth/`, `backend/api/*_routes.py`, `web_ui/`, deployment config
**Domain**: `premiumpropogandafashion.studio`

## Problem

The app is moving from a local Electron tool to a hosted website with public signups. The
existing auth system was written for single-machine use and does not survive that move.

Concrete defects in the current code:

| Defect | Location |
|---|---|
| Passwords hashed with unsalted SHA-256 | `models.py:174`, `models.py:212` |
| Session tokens stored in plaintext as the DB primary key | `models.py:150` |
| `expires_at` written in local time, compared against SQLite UTC `CURRENT_TIMESTAMP` | `models.py:238` vs `models.py:277` |
| All data paths relative to CWD — wrong directory silently yields an empty user DB | `models.py:124`, `brand_following.py:27` |
| `UserManager.list_all_users()` calls `self.db.conn()`, which does not exist | `manager.py:22` |
| `optional_auth` defined, imported nowhere | `middleware.py:80` |
| `create_admin_user_from_existing_data()` creates `admin`/`admin123` | `manager.py:170` |
| Session token accepted via `?session_token=` query param (leaks into logs) | `middleware.py:39` |
| `CORS(origins="*", supports_credentials=True)` | `app.py:29` |
| `DEBUG` defaults to `True` — Werkzeug debugger is RCE if deployed | `config/config.py:24` |
| `HOST` defaults to `127.0.0.1` — health checks cannot reach it | `config/config.py:22` |
| 29 of 45 endpoints have no authentication | `routes.py`, `high_fashion_routes.py` |
| No password reset, no email on the account, no rate limiting | — |
| Zero tests touch auth | `tests/` |

There are **0 users and 0 sessions** in `data/user_data/users.db`, so there is no migration
to write. Existing accounts are not a constraint.

## Decisions

Each was decided during design; rationale kept to one line.

1. **Email + password with verification.** Email is the login identity. Without it there is no
   password reset, and a forgotten password means a lost archive.
2. **Postgres for all relational user data** — accounts, sessions, email tokens, favourites,
   brand-following. Originally accounts-only; extended once R2 removed images from disk,
   leaving too little on disk to justify a persistent volume.
3. **No persistent disk on Render.** A disk pins the service to one instance and makes every
   deploy an outage. Images go to R2; everything else goes to Postgres.
4. **Cloudflare R2 for images.** Zero egress cost, S3-compatible. Served from
   `images.premiumpropogandafashion.studio` as a public bucket.
5. **Subdomain layout, not a proxy.** `api.` on its own hostname rather than proxied through
   the frontend host, so the SSE endpoint at `routes.py:865` streams without an edge proxy
   buffering it.
6. **Web only — Electron dropped.** One client, one auth path.
7. **Auth required on every route** except `/api/health` and the auth endpoints. An
   unauthenticated endpoint that launches Chromium against an arbitrary URL is an abuse vector
   that costs real money.
8. **Resend for email.** One file; swappable.
9. **Cloudflare Pages for the frontend**, not a fourth vendor. DNS, images and the static
   build then live in one account that is already required for R2.

## Architecture

```
                    premiumpropogandafashion.studio   →  CF Pages    (React build)
                api.premiumpropogandafashion.studio   →  Render      (Flask + gunicorn)
             images.premiumpropogandafashion.studio   →  R2 bucket   (public, CDN)
                                                          Render Postgres
                                                          Resend (outbound email)

DNS, images and static hosting: Cloudflare.  Registrar: Squarespace.
```

Both app hostnames sit under one registrable domain so a cookie scoped to
`.premiumpropogandafashion.studio` with `SameSite=Lax` is sent to both. Lax restricts
cross-*site*, not cross-origin, and these are the same site.

### Module layout

`backend/auth/user_system/` (928 lines) is replaced by a flat `backend/auth/`:

| File | Responsibility |
|---|---|
| `db.py` | psycopg3 connection pool |
| `schema.sql`, `migrate.py` | table definitions, applied on boot |
| `passwords.py` | argon2id hash / verify |
| `tokens.py` | opaque token generation + SHA-256 hashing |
| `repository.py` | every SQL statement for users, sessions, tokens |
| `service.py` | register, verify, login, logout, request-reset, reset |
| `email.py` | Resend client and the two message bodies |
| `middleware.py` | `require_auth`, reads the session cookie |
| `storage.py` | R2 client (boto3 against the R2 endpoint) |

`backend/api/auth_routes.py` stays a thin HTTP layer over `service.py`. No route touches SQL.

## Schema

All timestamps are `timestamptz`. This removes the local-vs-UTC expiry bug by construction
rather than patching the comparison.

```sql
users
  id                uuid primary key default gen_random_uuid()
  email             citext unique not null
  password_hash     text not null
  display_name      text not null
  email_verified_at timestamptz
  created_at        timestamptz not null default now()
  last_login_at     timestamptz
  is_active         boolean not null default true

sessions
  token_hash    bytea primary key          -- sha256 of the opaque token
  user_id       uuid not null references users(id) on delete cascade
  created_at    timestamptz not null default now()
  expires_at    timestamptz not null
  last_used_at  timestamptz not null default now()

email_tokens
  token_hash   bytea primary key           -- sha256 of the emailed token
  user_id      uuid not null references users(id) on delete cascade
  purpose      text not null check (purpose in ('verify','reset'))
  expires_at   timestamptz not null
  consumed_at  timestamptz

favourites
  id            bigserial primary key
  user_id       uuid not null references users(id) on delete cascade
  season        jsonb not null
  collection    jsonb not null
  look          jsonb not null
  image_key     text not null              -- R2 object key
  notes         text
  created_at    timestamptz not null default now()
  unique (user_id, image_key)

brand_following
  user_id                uuid not null references users(id) on delete cascade
  brand_id               text not null
  brand_name             text not null
  followed_at            timestamptz not null default now()
  notes                  text
  notify_new_products    boolean not null default true
  notify_price_changes   boolean not null default false
  primary key (user_id, brand_id)
```

Only token *hashes* are stored. A database read no longer allows impersonation.

## Auth flows

**Register.** Validate email and an 8-character minimum password → argon2id hash → insert with
`email_verified_at` null → issue a `verify` token (24h, single-use) → email it. Response is identical
whether or not the email was already registered, so the endpoint does not disclose who has an
account. An address that already exists still receives an email — one saying an account
already exists, with a reset link — so the user is never left without feedback.

**Verify.** `GET /api/auth/verify?token=…` → hash, look up, check unexpired and unconsumed →
set `email_verified_at`, set `consumed_at` → redirect to the site with a success flag.

**Login.** Look up by email → argon2 verify → if `email_verified_at` is null, refuse with
`EMAIL_NOT_VERIFIED` so the UI can offer a resend → otherwise mint a 32-byte token, store its
hash with a 30-day expiry, set the cookie.

**Session use.** `require_auth` reads the cookie, hashes it, looks up the row, rejects if
expired, and refreshes `last_used_at`. If the session is more than a day old, `expires_at` is
extended — rolling expiry is what "remembering the user" means here. No refresh tokens.

**Logout.** Delete the row, clear the cookie.

**Reset.** Request issues a `reset` token (1h, single-use) and always returns success
regardless of whether the address exists. Consuming it sets a new password and deletes every
session for that user.

Cookie flags: `HttpOnly`, `Secure`, `SameSite=Lax`, `Domain=.premiumpropogandafashion.studio`.

## Route protection

`require_auth` is applied at registration time in `app.py` to every blueprint except the
public allowlist:

```
public: /api/health, /api/auth/login, /api/auth/register,
        /api/auth/verify, /api/auth/resend-verification,
        /api/auth/request-reset, /api/auth/reset
```

Everything else — the 22 scraper routes, the 7 high-fashion routes, favourites, following —
requires a session.

Rate limits via Flask-Limiter, in-memory storage (single web service; resets on redeploy,
which the code will state explicitly rather than imply):

| Endpoint | Limit |
|---|---|
| login | 10/min per IP, 5/min per email |
| register | 5/hour per IP |
| request-reset | 3/hour per email |
| resend verification | 3/hour per email |

## Configuration

All via environment variables; no secrets in the repo.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Render Postgres internal URL |
| `APP_BASE_URL` | `https://premiumpropogandafashion.studio` — builds email links |
| `COOKIE_DOMAIN` | `.premiumpropogandafashion.studio` |
| `RESEND_API_KEY`, `MAIL_FROM` | outbound email |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | storage |
| `R2_PUBLIC_BASE` | `https://images.premiumpropogandafashion.studio` |
| `ANTHROPIC_API_KEY` | existing, scraper LLM |
| `HOST` | `0.0.0.0` — default changes from `127.0.0.1` |
| `DEBUG` | `false` — **default changes from `True`** |

`config.DEBUG` defaulting to true is treated as a defect, not just a deployment setting.

## Deleted

- `backend/auth/user_system/` entirely — `models.py`'s `UserDatabase`, `manager.py` (204 lines,
  imported nowhere, raises `AttributeError` when called), `optional_auth`,
  `create_admin_user_from_existing_data`, `get_or_create_user`.
- `web_ui/src/main.js`, `web_ui/src/preload.js`, and the `electron` / `electron-builder` /
  `electron-is-dev` dependencies.
- The eight hand-rolled `Authorization` header blocks in `web_ui/src/services/api.js`,
  replaced by one `credentials: 'include'` fetch wrapper.
- Hardcoded `http://localhost:8081` in `LoginModal.js` and `App.js`.

## Frontend

`web_ui/src/services/api.js` gets a single `API_BASE` from `REACT_APP_API_BASE` and one fetch
wrapper that sends `credentials: 'include'` and routes every 401 to one handler.

Five screens: Login, Register, Check-your-email, Reset-request, Reset-password. Verification
is a redirect target, not a screen. The app boots by calling `GET /api/auth/me`; a valid
cookie means the user is already in.

## Testing

pytest against a real Postgres.

- register → verify → login happy path
- login refused before verification, with `EMAIL_NOT_VERIFIED`
- wrong password refused; response timing not branch-dependent
- expired session rejected
- verification token rejected on second use
- reset token invalidates all existing sessions
- rate limit trips and recovers
- **route coverage**: walk `app.url_map` and assert every rule is either in the public
  allowlist or wrapped in `require_auth`

The last test is what stops route protection from silently regressing as endpoints are added.

## Build phases

1. Postgres: `db.py`, `schema.sql`, `migrate.py`, `repository.py`, `passwords.py` + tests
2. `service.py` + `email.py`: register, verify, login, logout, reset + tests
3. Cookie `middleware.py`, `require_auth` across all routes, route-coverage test
4. Favourites and brand-following moved to Postgres; per-user SQLite deleted
5. Delete dead auth code and the Electron shell
6. Frontend: `API_BASE`, fetch wrapper, five screens, 401 handler
7. **R2 image migration**: the three disk writers at `scraper/image_downloader.py:75`,
   `tools/image_downloader.py:166`, `scraper/favicon_downloader.py:58` upload to R2;
   `/api/images/...` serving is replaced by R2 public URLs; frontend image paths updated
8. `Dockerfile`, `render.yaml`, Cloudflare Pages build config, env wiring — deploy

Phase 7 touches the scraper rather than auth, but it **must precede phase 8**: the Render
service has no persistent disk, so any image still written to local disk is lost on every
redeploy. Phases 1-6 can be built and tested locally without it.

## Assumptions

- **Resend** as the email provider. Swappable — it is one file.
- Render runs **one gunicorn worker with 8 threads**. `routes.py:639` keeps scrape job state in
  a module-level dict behind a lock; a second worker would not see it. Concurrency comes from
  threads, not workers.
- The 2 GB Render instance is required for Chromium. Chromium will OOM on smaller plans.
- Rate-limit counters reset on redeploy. Acceptable for one service; revisit if it scales out.

## Non-goals

- OAuth / social login
- Two-factor authentication
- Admin UI for user management (`UserManager` is deleted, not replaced)
- Multi-region or multi-instance deployment
- Moving scraped brand data out of Postgres/R2 into anything else
