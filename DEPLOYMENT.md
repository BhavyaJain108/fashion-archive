# Deploying

Four pieces: the API and the scraper daemon on Render, the frontend on Cloudflare Workers, the archive and its images in R2.

```
premiumpropogandafashion.studio        Cloudflare Workers React build, static assets
(no address)                           Render worker      fashion-archive-scraper: the daemon
api.premiumpropogandafashion.studio    Render             Flask + Postgres
images.premiumpropogandafashion.studio Cloudflare R2      bucket, public
```

All three sit under one domain on purpose: the session cookie is set on
`.premiumpropogandafashion.studio`, so it reaches the site and the API both.
Split them across unrelated domains and login breaks — `SameSite=Lax` stops the
cookie being sent cross-site.

## 1. API on Render

Render dashboard -> New -> Blueprint -> pick this repo. It reads `render.yaml`
and creates a Postgres database, the API service, and the scraper worker
(`fashion-archive-scraper`, standard plan, Chromium image, `cli daemon start --workers 2`),
with `DATABASE_URL` wired to the API.

It will prompt for the secrets, which never enter the repo:

| Variable | From |
|---|---|
| `GOOGLE_CLIENT_ID` | Google Cloud -> APIs & Services -> Credentials |
| `GOOGLE_CLIENT_SECRET` | same OAuth client |
| `APPLE_CLIENT_ID` | Apple Developer -> Identifiers -> your Services ID |
| `APPLE_TEAM_ID` | Apple Developer -> Membership |
| `APPLE_KEY_ID` | Apple Developer -> Keys -> the Sign in with Apple key |
| `APPLE_PRIVATE_KEY` | contents of that key's .p8 file |
| `ANTHROPIC_API_KEY` | your existing key |
| `R2_ACCOUNT_ID` | in the R2 endpoint URL |
| `R2_ACCESS_KEY_ID` | R2 -> Manage R2 API Tokens |
| `R2_SECRET_ACCESS_KEY` | same token, shown once |
| `YOUTUBE_API_KEY` | Google Cloud, YouTube Data API |
| `ADMIN_EMAILS` | who may open `/dev`, comma-separated |
| `FINDER_DAILY_USD` | the finder's daily cap; set the same on both services |
| `ANTHROPIC_ADMIN_KEY` | Anthropic console, an admin key, for the costs page |
| `CLOUDFLARE_API_TOKEN` | Cloudflare, read access to R2 analytics, for the costs page |
| `RENDER_API_KEY` | Render account settings, for the costs page |

First build takes 5-15 minutes; the image contains Chromium.

Then: the service -> Settings -> Custom Domains -> `api.premiumpropogandafashion.studio`.
DNS is on Cloudflare, so add the CNAME it shows you there, **DNS only** (grey
cloud, not proxied) — a proxied record breaks certificate issuance.

Check it:

```bash
curl -i https://api.premiumpropogandafashion.studio/api/health
```

## 2. Frontend on Cloudflare Workers

Pages and Workers are merged now, so a static site deploys as a Worker with
assets. `web_ui/wrangler.jsonc` declares the build output and the SPA fallback.

Do NOT add a `_redirects` file with the usual `/*  /index.html  200` rule — the
Workers asset handler rejects it as an infinite loop, because it already strips
`/index` and `.html`. `not_found_handling` in wrangler.jsonc does that job.

Cloudflare -> Workers & Pages -> Create -> Connect to Git.

| Setting | Value |
|---|---|
| Root directory | `web_ui` |
| Build command | `npm run build` |
| Output directory | `build` |
| Environment variable | `REACT_APP_API_URL` = `https://api.premiumpropogandafashion.studio` |

`REACT_APP_API_URL` is compiled into the bundle, so changing it needs a rebuild,
not just a redeploy.

Then add the custom domain `premiumpropogandafashion.studio` under the project's
Custom Domains tab.

## 3. Check it end to end

Open the site and register. Confirm, in order:

1. the Google (or Apple) consent screen appears
2. it sends you back signed in
3. the account is the same one you had before, if you had signed up by email
4. **reloading the page keeps you logged in** — if this fails the cookie is not
   crossing subdomains; check `COOKIE_DOMAIN` starts with a dot
5. images load from `images.premiumpropogandafashion.studio`

## Things that will bite

**One API process, on purpose.** The deck's ten-second overview cache and the
provider caches are module-level. A second gunicorn worker would answer half the
polls from a cold cache. Concurrency comes from `--threads`.

**Every push replaces the scraper's container.** A run in flight is lost; the
brand shows "worker dead" on the deck for up to fifteen minutes, or press
*release*. Batch pushes.

**`DEBUG` must stay false.** It serves the Werkzeug debugger, an interactive
Python console, to anyone who can trigger a traceback.

**No persistent disk.** Anything written to the container filesystem is gone on
the next deploy. Images go to R2, everything else to Postgres. If you add a
feature that writes a file, it needs one of those two.

## Local development

```bash
scripts/test_db.sh start
venv/bin/python backend/app.py           # config/.env supplies the rest
cd web_ui && REACT_APP_API_URL=http://localhost:8081 npm start
```

Use the same hostname for both — `localhost` for both, or `127.0.0.1` for both.
The browser treats them as different sites, and mixing them makes the session
cookie silently vanish. See `web_ui/README.md`.

Sign-in needs a provider: with no `GOOGLE_CLIENT_*` or `APPLE_*` variables set,
`/api/auth/providers` returns an empty list and the site says so rather than
offering a button that dead-ends. Google allows `http://localhost` redirect
URIs, so it works locally; Apple does not, so Apple can only be tested on the
deployed domain.
