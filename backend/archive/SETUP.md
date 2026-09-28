# Running the archive by hand

The root [README](../../README.md) is the current guide: how the archive is stored,
what the daemon does, the control deck, the CLI, tests and deploying. This file only
keeps what is specific to a hand-run scrape.

```bash
venv/bin/pip install -r requirements-dev.txt      # includes boto3, curl_cffi, playwright
venv/bin/playwright install chromium               # only for --browser or a t2 brand
```

`config/.env` needs `R2_*` for the bucket, or `ARCHIVE_OBJECTS=/some/dir` to work on a
local directory instead. `ANTHROPIC_API_KEY` and `FINDER_DAILY_USD` are needed only
with `--find-fields` or `--learn`.

```bash
venv/bin/python -m backend.archive.runner.cli capability kuurth.com   # can we get in, how
venv/bin/python -m backend.archive.runner.cli scrape kuurth.com --sample 20 --no-images
venv/bin/python -m backend.archive.runner.cli scrape kuurth.com --learn   # the finder alone
venv/bin/python -m backend.archive.runner.cli show kuurth.com
venv/bin/python -m backend.archive.runner.cli fleet-check                 # every brand, one table
```

The learning loop by hand (README, "The learning loop"). The read-only commands skip
the roster seed and answer in seconds:

```bash
venv/bin/python -m backend.archive.runner.cli learn status
venv/bin/python -m backend.archive.runner.cli walls                        # every brand not simply open
venv/bin/python -m backend.archive.runner.cli dossier kuurth.com --events 40
venv/bin/python -m backend.archive.runner.cli budget
venv/bin/python -m backend.archive.runner.cli signatures                   # the roster as clusters
venv/bin/python -m backend.archive.runner.cli learn onboard example.com   # writes the dossier
venv/bin/python -m backend.archive.runner.cli learn analyse example.com --kind brand   # one model call, then the gate
venv/bin/python -m backend.archive.runner.cli learn proposals
venv/bin/python -m backend.archive.runner.cli learn apply <id> --root .   # a filed code proposal into this tree
```

`learn onboard`, `learn analyse` and `learn tick` write to the bucket and spend money;
`--browser` tells them a t2 rung is available here. Do not run `scrape`, `daemon` or
`learn tick` against the bucket while the hosted daemon is up: the two would claim the
same brands, and two loops would onboard the same ones. Use `--objects DIR` for experiments.
