# Deploying

Three pieces: the API on Render, the frontend on Cloudflare Pages, images in R2.

```
premiumpropogandafashion.studio        Cloudflare Pages   React build
api.premiumpropogandafashion.studio    Render             Flask + Postgres
images.premiumpropogandafashion.studio Cloudflare R2      bucket, public
```

All three sit under one domain on purpose: the session cookie is set on
`.premiumpropogandafashion.studio`, so it reaches the site and the API both.
Split them across unrelated domains and login breaks — `SameSite=Lax` stops the
cookie being sent cross-site.

## 1. API on Render

Render dashboard -> New -> Blueprint -> pick this repo. It reads `render.yaml`
and creates a Postgres database plus the API service, with `DATABASE_URL` wired
between them.

It will prompt for five secrets, which never enter the repo:

| Variable | From |
|---|---|
| `RESEND_API_KEY` | Resend -> API Keys |
| `ANTHROPIC_API_KEY` | your existing key |
| `R2_ACCOUNT_ID` | in the R2 endpoint URL |
| `R2_ACCESS_KEY_ID` | R2 -> Manage R2 API Tokens |
| `R2_SECRET_ACCESS_KEY` | same token, shown once |

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

1. the verification email arrives (not in spam — that is what the DKIM/SPF
   records are for)
2. the link signs the account off as confirmed
3. you can log in
4. **reloading the page keeps you logged in** — if this fails the cookie is not
   crossing subdomains; check `COOKIE_DOMAIN` starts with a dot
5. images load from `images.premiumpropogandafashion.studio`

## Things that will bite

**One worker, on purpose.** `backend/api/routes.py` keeps scrape job state in a
module-level dict. A second worker would not see it, and half of a client's
status polls would hit a process that never heard of the job. Concurrency comes
from `--threads`.

**`DEBUG` must stay false.** It serves the Werkzeug debugger, an interactive
Python console, to anyone who can trigger a traceback.

**Rate-limit counters are in memory** and reset on redeploy. Fine for one
service; revisit if it ever scales out.

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

Without `RESEND_API_KEY` set, verification links print to the terminal, so the
whole signup flow works with no credentials.
