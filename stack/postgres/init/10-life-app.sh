#!/usr/bin/env bash
# Creates life-app's role and database. Postgres runs this only on an empty
# data volume.
set -euo pipefail

# The role owns the database, so migrations can create tables in its public
# schema.
psql -v ON_ERROR_STOP=1 -v pw="$LIFE_APP_DB_PASSWORD" --username "$POSTGRES_USER" <<'SQL'
CREATE ROLE life_app LOGIN PASSWORD :'pw';
CREATE DATABASE life_app OWNER life_app;
SQL
