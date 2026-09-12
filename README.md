# Fashion Archive

Two things share one backend:

- **The archive** — a scraper that reads small and mid-sized fashion brands' own
  shops and records every product in the E0005 export schema: prices, per-size
  stock, images, categories. It keeps the photographs, not just their URLs, and
  keeps a history, so a product's price and availability can be read back over
  time. The brands it follows are listed in `backend/archive/brands.yml`.
- **High Fashion** — runway seasons, collections and look images, with favourites.

The web client shows both: Collections, Favourites, My Brands.

## Running it

Python 3.11+, Node 20+, and Postgres for the login.

```bash
python3 -m venv venv
venv/bin/pip install -r requirements-dev.txt
cp config/.env.example config/.env     # then fill in CLAUDE_API_KEY
```

Start Postgres, the API, and the client — each in its own terminal:

```bash
scripts/test_db.sh start
```

```bash
venv/bin/python backend/app.py
```

```bash
cd web_ui && npm install && npm start
```

The client is on `http://localhost:3000` and the API on `http://localhost:8081`.
Use the same hostname for both — `localhost` for both, or `127.0.0.1` for both, or
the session cookie silently vanishes. Register an account on first run; without
`RESEND_API_KEY` set, the verification link prints to the API's terminal.

## Running the scraper

The scraper is a CLI, not part of the web app. It runs wherever you like and
writes to `backend/archive/data/catalog.db`.

```bash
venv/bin/python -m backend.archive.runner.cli status
```

```
plan  scrape  status  capability  images  brands  hosts  show  daemon
```

`scrape` reads a brand's catalogue; `images` fetches the photographs, which is a
separate pass because it takes hours and a scrape should take minutes; `status`
and `show` report what was collected; `daemon` runs the fleet on a schedule.
Every command takes `--help`.

Image bytes go to Cloudflare R2 when `R2_*` is set in `config/.env`, and to a
local directory when it is not.

## Tests

```bash
venv/bin/pytest -m unit && venv/bin/ruff check tests/ backend/archive/ && venv/bin/mypy
```

That is what CI runs. `-m db` needs the Postgres above; `-m integration` drives a
browser. Lint and type checking are scoped to `tests/` and `backend/archive/` and
widen as the rest is cleaned up.

## Deploying

See [DEPLOYMENT.md](DEPLOYMENT.md): the API on Render, the client on Cloudflare,
images in R2.

The scraper is not deployed. It writes SQLite on the machine it runs on, so a
hosted site cannot read it yet — publishing snapshots the site can serve is the
next piece of work.

## Where things are

```
backend/archive/     the scraper, and the only module that touches its catalogue
backend/api/         Flask routes, one module per area
backend/auth/        accounts and sessions, on Postgres
backend/high_fashion/ runway seasons and collections
web_ui/              React client
docs/superpowers/    design specs and implementation plans
```

MIT licensed.
