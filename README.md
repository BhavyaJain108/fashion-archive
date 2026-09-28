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
rules/<domain>.json              learned rules for fields the channel does not carry
dossiers/<domain>.json           what the learning loop knows about the brand, dated, unbounded
recipes/lanes/<id>.json          lanes the model proposed and the gate proved, as data
control/budget.json              the fleet's daily ceiling and its two pools
control/learning.json            the loop's last tick and its history
control/signatures.json          the roster as clusters of shape, with their walls and rules
learn/proposals/ learnings.jsonl code the model wrote for a person; what it wrote down
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
(curl_cffi), t1p the same handshake from another address (an egress proxy,
`ARCHIVE_PROXY_URL`; the rung exists only when that is set), t2 a real Chromium,
t4 password-gated. The worker image carries Chromium; the API image does not.

Lanes are a transport times a way of finding products times a way of reading one:
Shopify's feed, WooCommerce's API, a sitemap and the page's JSON-LD, a Gatsby
site's page data, Swell's storefront API for a headless shop, and a *recipe*,
which is any of those described as data (see the next section).

## The learning loop

The seven steps a person took to get a new brand reading — measure, name the
wall, look at one page, write the narrowest rule, verify it on the brands that
did not teach it, write it down, measure again — run unattended in
`backend/archive/learn/`. The loop is a thread beside the daemon's workers that
ticks every `LEARN_TICK_SECONDS` (15 minutes) and does the mechanical part
itself; the model is asked only where a rule cannot be written by a rule.

Each tick:

1. **Onboards** a few brands that have no dossier yet, the hard ones first: a
   brand whose notes say it is walled or off-platform goes before a Shopify
   store the shelf already reads. Onboarding climbs the ladder cheapest rung
   first, writes a **signature** (six words for the shape of the shop:
   platform, feed, sitemap, page markup, defence, locale), plans, reads a
   sample and records a verdict. Every step is written to the dossier as it
   happens, and the brand page draws them as a stepper.
2. **Classifies every brand's wall** from its dossier alone, never from its
   name, and commits to one next action:

   | wall | meaning | action |
   |---|---|---|
   | open | reads, all core fields | nothing |
   | field_gap | reads, something the shop publishes is not read | ask the model |
   | busy / rate_limited | the host wants a slower pace | wait, retry slower |
   | tls | refuses Python's handshake | climb to t1 |
   | address | refuses the address, whatever the handshake | climb to t1p; without a proxy, watch |
   | challenge | a script must run first | climb to t2; if the browser does not clear it, ask the model |
   | geo | serves one country, refused from the proxy too | watch; `ARCHIVE_PROXY_URL_<CC>` names that country's exit |
   | gated | a password | nothing |
   | unreadable | lets us in, nothing readable | ask the model |
   | expensive | reads, at three times its neighbours' price per product | ask for a cheaper way |
   | not_a_shop | a portfolio, a landing page | nothing |

   A climb is tried three times before the loop stops and asks the model.
3. **Asks the model** (the analyst, three brands a tick, three a brand a week)
   with the brand's own pages, its ladder and signature, its nearest neighbours
   by signature and the rules that exist. The answer is a validated object: a
   signature, the gaps by class (unread, unsought, absent), and a lane. A lane
   is a **recipe** where a connector that exists can be told what to do (which
   sitemap, which JSON endpoint, which path in it, where each field sits), or
   **code** where none can.
4. **Gates** every recipe before it lands: replayed over the captured pages
   with no network, then live on the brand, then on every neighbour of the same
   signature. A recipe that reads its brand but not its neighbours lands for
   the brand only; one that reads both becomes a rule for the shape. A landing
   must beat the lane the brand already had, or it is recorded and refused.
   Code never lands on its own: with `ARCHIVE_GIT_PUSH_URL` set it goes on a
   `learn/…` branch, otherwise it is filed for `cli learn apply`.
5. **Prices the fleet.** A meter counts each brand's requests by rung, proxy
   requests, browser seconds and model tokens; dollars are a view over those.
   The fleet's ceiling is every brand's predicted daily cost at its cheapest
   lane times `ARCHIVE_BUDGET_MULTIPLIER`, never below `ARCHIVE_BUDGET_FLOOR_USD`.
   The baseline is the **recurring** pool, the headroom the **discretionary**
   pool that probes, proxy sweeps and analyses spend; when recurring would be
   exceeded, cadences stretch rather than brands drop.

Without `ANTHROPIC_API_KEY` the loop still onboards, classifies and climbs; it
cannot ask, so walls that need the model stay where they are. Without
`ARCHIVE_PROXY_URL` the t1p rung does not exist and address walls stay shut.
The model's own findings go to `learn/learnings.jsonl`; the human ones, and the
procedure the loop follows, are in
[backend/archive/access/LEARNINGS.md](backend/archive/access/LEARNINGS.md).

## The control deck

`/dev` on the site, for the addresses in `ADMIN_EMAILS` only. It reads the
objects above and writes nothing but the schedule and its own notes.

- **Brands** — every brand with its gate, fields filled, cost and latency; sort
  any column; select several and run, pause or resume them as one batch; add a
  brand. A held brand shows a progress bar with the phase in words.
- **A brand** — last actions in words, the plan, every E0005 field with its
  class, fill, learned rules and where we searched, every run with its log,
  what each run added and removed, and how its hosts answered this week. Below
  that its **dossier**: the signature and the wall, every rung ever tried,
  every lane that read it, the gaps by class, the money by day, what the model
  said and what the gate answered, and the timeline. A brand being onboarded
  shows the six steps as they happen.
- **Learning** (`/dev/learning`) — the loop's own page: the budget and its two
  pools, the roster as clusters by signature, every brand not simply open with
  its wall and next action, what the last tick did, the code the model wrote,
  the rules that exist and the notebook. *tick now* runs one tick from the API
  (no browser there, so t2 climbs wait for the worker's tick).
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
| learn fields | idle | a finder-only run: a spread of product pages is read, rules are written, nothing is stored, the scheduled turn is kept; *retry searched fields* asks again about fields given up on |
| probe again | on the dossier | re-runs onboarding: the ladder, the signature, the wall, a sample |
| climb t1 / t1p / t2 | on the dossier | one rung, by hand; t1p needs `ARCHIVE_PROXY_URL` on the API |
| ask the model / find a cheaper way | on the dossier | one analysis, then the gate; needs `ANTHROPIC_API_KEY` on the API |
| sweep (`POST …/sweep`) | idle | a stock-only run: the bulk feed is re-read and only what is in stock, and at what price, is updated on products already held; no pages, no images, nothing added or removed, the scheduled turn is kept. `POST …/sweep_seconds {"seconds": n}` sets a per-brand sweep cadence (0 = off); rows carry `last_sweep` |

From the terminal the same runs are `cli scrape X --learn [--retry-searched]` and
`cli scrape X --sweep`; `cli brands sweep X --every 900` sets the sweep cadence.

## Running the scraper by hand

```bash
venv/bin/python -m backend.archive.runner.cli status
```

```
scrape  status  capability  daemon  brands  hosts  show  images
access  coverage  fleet-check  notes  failures  periods  backup  restore
learn   dossier  walls  budget  signatures
```

The learning loop from the terminal: `learn status`, `learn tick`, `learn
onboard X`, `learn analyse X [--kind brand|failure|cheapen]`, `learn proposals`
and `learn apply ID` write a filed code proposal into the working tree;
`dossier X`, `walls`, `budget` and `signatures` print the loop's objects.
`daemon start --no-learn` runs the workers without the loop.

Every command takes `--help` and `--objects DIR` to work on a local directory
instead of the bucket. `fleet-check` is the one-table answer to "which brands
can we get into today, and what should we fix first". Do not run `scrape` or
`daemon` against the bucket while the hosted daemon is running: they would
claim the same brands.

## Tests

```bash
venv/bin/pytest -m unit && venv/bin/ruff check tests/ backend/archive/ && venv/bin/ruff format --check tests/ backend/archive/ && venv/bin/mypy
```

```bash
cd web_ui && CI=true npx react-scripts test --watchAll=false && npm run check:tokens && npm run check:css
```

`check:tokens` refuses raw hex colours, pixel font sizes, and ad-hoc radii or
shadows in the deck's CSS: everything comes from the `--ar-*` tokens in
`web_ui/src/shared/styles/archive.css`.

## Deploying

See [DEPLOYMENT.md](DEPLOYMENT.md). `render.yaml` declares a database and two services: the
Postgres database, the API (`fashion-archive-api`), and the scraper daemon
(`fashion-archive-scraper`, standard plan, Chromium image). A push to `master`
rebuilds and deploys the API; the worker has auto-deploy off and is deployed
from the Render dashboard once a batch is ready, because a new container drops
the run in flight (the brands it held are released within fifteen minutes or
from the deck). The client is separate:

```bash
cd web_ui && REACT_APP_API_URL=https://api.premiumpropogandafashion.studio npm run build && npx wrangler deploy
```

Environment the API needs beyond DEPLOYMENT.md's table: `ADMIN_EMAILS`,
`FINDER_DAILY_USD`, and for the costs page `ANTHROPIC_ADMIN_KEY`,
`CLOUDFLARE_API_TOKEN`, `RENDER_API_KEY`. `ANTHROPIC_API_KEY` and
`ARCHIVE_PROXY_URL` go on both services: the worker's loop uses them on its
own, and the deck's buttons use the API's copy.

## Where things are

```
backend/archive/         the scraper: planner, runner, scheduler, store, score, recommend
backend/archive/learn/   the learning loop: signature, dossier, walls, meter, budget, recipes, gate, analyst
backend/archive/connectors/  one lane each: shopify, woocommerce, sitemap, structured, runfair, swell
backend/archive/access/  the bench for transports and access experiments
backend/api/             Flask routes, one module per area; dev_routes.py is the deck
backend/auth/            accounts and sessions, on Postgres
backend/high_fashion/    runway seasons and collections
web_ui/src/features/dev/ the control deck
docs/superpowers/        design specs and implementation plans
backend/archive/access/LEARNINGS.md  what each brand taught us, and the rules that came of it
```

MIT licensed.
