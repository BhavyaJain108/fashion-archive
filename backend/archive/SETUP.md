# Running the archive on your machine

Everything below runs from the repo root. The code is on the branch
`claude/codebase-review-90b4e7`, currently in the worktree
`.claude/worktrees/codebase-review-90b4e7/`.

## 1. Go to the code

```bash
cd /Users/bhavyajain/Code/fashion-archive/.claude/worktrees/codebase-review-90b4e7
```

(Or bring it into your main checkout: `git checkout claude/codebase-review-90b4e7`.)

## 2. Python setup — once

Homebrew Python refuses to install packages globally, so use a virtualenv.

```bash
python3 -m venv .venv
.venv/bin/pip install httpx pydantic pyyaml beautifulsoup4 lxml anthropic pytest playwright
```

Only if you want the browser lane (needed for a few blocked shops, ~95MB download):

```bash
.venv/bin/python -m playwright install chromium
```

## 3. API key — only needed for `--find-fields`

Everything else costs $0 and needs no key.

```bash
mkdir -p config
echo 'CLAUDE_API_KEY=sk-ant-your-key-here' >> config/.env
```

If your key is an **identity-linked** key, the API also needs the workspace it acts in,
or every call fails with `anthropic-workspace-id is required`. Find the id in the
Anthropic console URL when your workspace is open — it looks like `wrkspc_...`:

```bash
echo 'ANTHROPIC_WORKSPACE_ID=wrkspc_your_workspace_id' >> config/.env
```

## 4. Check it works

```bash
.venv/bin/python -m pytest tests/unit/archive -q
```

Expect `125 passed`. No network, no key needed.

## 5. Commands

Look at one shop — what can we get from it, and how good is the data?

```bash
.venv/bin/python -m backend.archive.runner.cli capability kuurth.com
```

Look at all 37 shops (about 350 requests, a few minutes):

```bash
.venv/bin/python -m backend.archive.runner.cli capability --all
```

Scrape one shop into the database:

```bash
.venv/bin/python -m backend.archive.runner.cli scrape kuurth.com --full
```

Scrape everything, only writing what changed since last time:

```bash
.venv/bin/python -m backend.archive.runner.cli scrape --all --delta
```

See what the database holds:

```bash
.venv/bin/python -m backend.archive.runner.cli status
```

Find missing fields on a shop (this is the one that costs money — about 5 cents per shop, once):

```bash
.venv/bin/python -m backend.archive.runner.cli scrape psylos1.com --full --find-fields
```

## 6. Where things are written

| Path | What |
|---|---|
| `backend/archive/data/catalog.db` | products, prices over time, learned rules |
| `backend/archive/data/images/` | product photos |
| `backend/archive/data/logs/<shop>/<run>.jsonl` | one line per event in a run |
| `backend/archive/brands.yml` | the list of shops — edit to add one |

All gitignored.

## 7. Adding a shop

Add two lines to `backend/archive/brands.yml`:

```yaml
  - {domain: newshop.com, homepage_url: "https://newshop.com"}
```

Then `capability newshop.com` tells you what it can get before you scrape it.

## Useful flags

| Flag | Does |
|---|---|
| `--sample N` | how many products `capability` checks (default 5) |
| `--no-images` | skip photo downloads |
| `--image-sample N` | photos for N products per run (default 5, `0` = all) |
| `--browser` | allow the Chromium lane for shops that block plain requests |
| `--find-fields` | the paid step — one LLM call per shop to locate missing fields |
| `--show-gated` | list password-locked shops as rows instead of a footnote |
