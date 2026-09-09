#!/usr/bin/env bash
# Start / stop a throwaway Postgres for the `db`-marked tests.
#
#   scripts/test_db.sh start
#   scripts/test_db.sh stop
#
# Runs on port 55432 with its own data directory under ~/.cache, so it never
# touches a Postgres you use for anything else. TCP only: the socket path limit
# is 103 bytes and a temp-dir socket blows past it.
set -euo pipefail

PORT=55432
PGDATA="${HOME}/.cache/fashion-archive-testdb"
PGBIN="$(brew --prefix postgresql@17 2>/dev/null || echo /usr/local)/bin"
DB=fashion_archive_test

# Postgres on macOS aborts with "postmaster became multithreaded" unless the
# locale is set explicitly.
export LC_ALL=C LANG=C

case "${1:-start}" in
  start)
    [ -d "$PGDATA" ] || "$PGBIN/initdb" -D "$PGDATA" -U postgres --auth=trust >/dev/null
    "$PGBIN/pg_ctl" -D "$PGDATA" -o "-p $PORT -c unix_socket_directories=''" \
      -l "$PGDATA/server.log" start
    sleep 1
    "$PGBIN/psql" -h 127.0.0.1 -p $PORT -U postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1 || \
      "$PGBIN/createdb" -h 127.0.0.1 -p $PORT -U postgres "$DB"
    echo "ready: postgresql://postgres@127.0.0.1:$PORT/$DB"
    ;;
  stop)
    "$PGBIN/pg_ctl" -D "$PGDATA" stop
    ;;
  *)
    echo "usage: $0 {start|stop}" >&2; exit 1
    ;;
esac
