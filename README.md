# Fashion Archive

Two things share one backend:

- **The archive** — a scraper that reads small and mid-sized fashion brands' own
  shops and records every product in the E0005 export schema: prices, per-size
  stock, images, categories. It keeps the photographs, not just their URLs, and
  stamps every product with the run that first saw it, last read it, and last
  covered it, so what a catalogue held at any run is derived rather than stored.
  The brands it follows are listed in `backend/archive/brands.yml`, plus any added
  from the control deck.
- **High Fashion** — runway seasons, collections and look images, with favourites.

The web client shows both: Collections, Favourites, My Brands. The owner also gets
`/dev`, the control deck.

## Running it

Python 3.11+, Node 20+, and Postgres for the login.

```bash
python3 -m venv venv
venv/bin/pip install -r requirements-dev.txt
cp config/.env.example config/.env     # then fill in ANTHROPIC_API_KEY and R2_*
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

## How the archive works

Everything the scraper knows lives as objects in one R2 bucket — there is no
database for the catalogue. The bucket is also the control plane: which brands
run, when, and who holds them.

```
control/schedule/<domain>.json   one row per brand: enabled, cadence, next_due, claimed_by
fleet.json                       one line per brand: state, last scorecard, next action
plans/<domain>.json              how to get in: transport × discovery × fetch × change signal
recipes/<domain>.json            learned rules for fields the channel does not carry
catalogue/<domain>.json          the products, one entry per URL, stamped with run ids
images/<sha256>                  photographs, content-addressed — nothing is stored twice
runs/ scores/ evidence/ logs/    what each run did, how it scored, where it searched
```

A **run** claims a brand from the schedule with a conditional write, probes it,
follows the plan, writes products and photographs, scores the result against a
gate (six fields a shop cannot sell without), records what to fix next, and
hands the brand back with its next due time. Three runs in a row that need a
human double the wait, up to sixteen times the cadence; nothing is ever dropped.

The **daemon** is one Render worker running two of those loops. It heartbeats
every five minutes; a claim with no beat for fifteen minutes is taken over by
the next worker, and the deck offers *release* after twelve.

The **finder** is the only part that costs money: a model reads a product page
and proposes rules for blank fields, kept only if replaying them reproduces the
value. It is capped per day across the fleet (`FINDER_DAILY_USD`).

Transports: t0 plain HTTP, t1 a browser's handshake without a browser
(curl_cffi), t2 a real Chromium, t4 password-gated. The worker image carries
Chromium; the API image does not.

## The control deck

`/dev` on the site, for the addresses in `ADMIN_EMAILS` only. It reads the
objects above and writes nothing but the schedule and its own notes.

- **Brands** — every brand with its gate, fields filled, cost and latency; sort
  any column; select several and run, pause or resume them as one batch; add a
  brand. A held brand shows a progress bar with the phase in words.
- **A brand** — last actions in words, the plan, every E0005 field with its
  class, fill, learned rules and where we searched, every run with its log,
  what each run added and removed, and how its hosts answered this week.
- **Catalogue** — every product with all its photographs, when it came, was
  last read, and left; filter to live, gone, or added; or view the catalogue
  as of any run.
- **Costs** — our own ledger, then Anthropic, Cloudflare R2 and Render as they
  report it (Render has no billing endpoint; bandwidth is read from metrics).
- **Notes** — a sidebar on every view for change requests; `cli notes` prints
  the open ones.

Buttons and what they do:

| button | when it shows | effect |
|---|---|---|
| run now | idle, on schedule | due now; a worker takes it within ten seconds |
| run once | paused | one run, then still paused |
| pause / pause after run | on schedule | skipped at the next claim; a running brand finishes first |
| resume | paused | back on its cadence; an overdue brand runs at once |
| release | worker dead (no beat for 12 min) | hands the brand back; the run starts over |

## Running the scraper by hand

```bash
venv/bin/python -m backend.archive.runner.cli status
```

```
scrape  status  capability  daemon  brands  hosts  show  images
access  coverage  fleet-check  notes
```

Every command takes `--help` and `--objects DIR` to work on a local directory
instead of the bucket. `fleet-check` is the one-table answer to "which brands
can we get into today, and what should we fix first". Do not run `scrape` or
`daemon` against the bucket while the hosted daemon is running: they would
claim the same brands.

## Tests

```bash
venv/bin/pytest -m unit && venv/bin/ruff check tests/ backend/archive/ && venv/bin/mypy
```

```bash
cd web_ui && CI=true npx react-scripts test --watchAll=false && npm run check:tokens
```

`check:tokens` refuses raw hex colours, pixel font sizes, and ad-hoc radii or
shadows in the deck's CSS: everything comes from the `--ar-*` tokens in
`web_ui/src/shared/styles/archive.css`.

## Deploying

See [DEPLOYMENT.md](DEPLOYMENT.md). `render.yaml` declares three services: the
Postgres database, the API (`fashion-archive-api`), and the scraper daemon
(`fashion-archive-scraper`, standard plan, Chromium image). A push to `master`
rebuilds both images and replaces the daemon's container mid-run, so batch
pushes; the brands it held are released within fifteen minutes or from the
deck. The client is separate:

```bash
cd web_ui && REACT_APP_API_URL=https://api.premiumpropogandafashion.studio npm run build && npx wrangler deploy
```

Environment the API needs beyond DEPLOYMENT.md's table: `ADMIN_EMAILS`,
`FINDER_DAILY_USD`, and for the costs page `ANTHROPIC_ADMIN_KEY`,
`CLOUDFLARE_API_TOKEN`, `RENDER_API_KEY`.

## Where things are

```
backend/archive/         the scraper: planner, runner, scheduler, store, score, recommend
backend/archive/access/  the bench for transports and access experiments
backend/api/             Flask routes, one module per area; dev_routes.py is the deck
backend/auth/            accounts and sessions, on Postgres
backend/high_fashion/    runway seasons and collections
web_ui/src/features/dev/ the control deck
docs/superpowers/        design specs and implementation plans
LEARNINGS.md             what each brand taught us, and the rules that came of it
```

MIT licensed.
