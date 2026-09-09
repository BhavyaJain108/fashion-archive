# Playwright's own image, because the scraper drives Chromium and this ships the
# browser plus the system libraries it needs. Building those on a plain Python
# base means chasing apt packages every time the browser updates.
#
# The tag must match the playwright version in requirements — a mismatched
# client and browser fail at runtime, not at build time.
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Dependencies first: this layer is cached unless the requirements change, so
# ordinary code deploys skip reinstalling everything.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Unbuffered, or logs arrive in blocks and a crash loses the lines explaining it.
ENV PYTHONUNBUFFERED=1

# One worker, eight threads — deliberately.
#
# backend/api/routes.py keeps scrape job state in a module-level dict behind a
# threading.Lock. With two workers, half of a client's status polls reach a
# process that has never heard of the job. Concurrency comes from threads here,
# not from workers.
#
# --timeout 0 because a scrape and its progress stream both outlive gunicorn's
# default 30s, and it would kill the worker mid-run.
CMD gunicorn backend.app:app \
    --bind 0.0.0.0:$PORT \
    --workers 1 \
    --threads 8 \
    --timeout 0 \
    --access-logfile - \
    --error-logfile -
