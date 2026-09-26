#!/usr/bin/env bash
# Print "<table> <row count>" for every table in the public schema, sorted.
# Usage: scripts/row_counts.sh <database url>
set -euo pipefail
url="$1"
tables="$(psql "$url" -At -v ON_ERROR_STOP=1 -c \
  "select tablename from pg_tables where schemaname = 'public' order by tablename")"
for table in $tables; do
  count="$(psql "$url" -At -v ON_ERROR_STOP=1 -c "select count(*) from public.\"$table\"")"
  echo "$table $count"
done
