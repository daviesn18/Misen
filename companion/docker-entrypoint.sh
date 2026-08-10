#!/bin/sh
#
# Migrate, then serve.
#
# Running `alembic upgrade head` on every start is safe — it is a no-op when
# the database is already at head — and it means a `docker compose up -d --build`
# after a schema change does the right thing without a second command that
# someone will eventually forget.
#
# It runs in the foreground and the script is `set -e`, so a failed migration
# stops the container instead of starting an app against a schema it doesn't
# match. Compose's healthcheck then keeps Caddy from fronting a broken service.

set -e

echo "==> alembic upgrade head"
alembic upgrade head

echo "==> starting uvicorn"
exec "$@"
