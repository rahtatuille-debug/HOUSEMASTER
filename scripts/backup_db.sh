#!/usr/bin/env bash
# Take an encrypted backup of the production database.
#
# Usage: DATABASE_URL=... BACKUP_PASSPHRASE=... scripts/backup_db.sh [output-dir]
#
# Writes housemaster-<UTC timestamp>.tar.gpg to the output directory
# (default: ./backups). Inside the encrypted file:
#   - database.dump   a full pg_dump of the database (custom format)
#   - row_counts.txt  how many rows each table had at the time, so a
#                     restore can be checked against it (verify_backup.sh)
#
# Use Neon's *direct* connection string (pooling switched off in the Neon
# console). pg_dump doesn't work reliably through the connection pooler.
set -euo pipefail

: "${DATABASE_URL:?Set DATABASE_URL to the database to back up}"
: "${BACKUP_PASSPHRASE:?Set BACKUP_PASSPHRASE; the backup is encrypted with it}"

out_dir="${1:-backups}"
mkdir -p "$out_dir"
stamp="$(date -u +%Y-%m-%dT%H%MZ)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "Dumping database..."
pg_dump --format=custom --no-owner --no-privileges --file="$work/database.dump" "$DATABASE_URL"

echo "Counting rows..."
"$(dirname "$0")/row_counts.sh" "$DATABASE_URL" > "$work/row_counts.txt"
echo "$(wc -l < "$work/row_counts.txt") tables, $(awk '{s+=$2} END {print s}' "$work/row_counts.txt") rows in total"

echo "Encrypting..."
tar -C "$work" -cf "$work/backup.tar" database.dump row_counts.txt
printf '%s' "$BACKUP_PASSPHRASE" | gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 0 \
  --symmetric --cipher-algo AES256 --output "$out_dir/housemaster-$stamp.tar.gpg" "$work/backup.tar"

echo "Backup written to $out_dir/housemaster-$stamp.tar.gpg ($(du -h "$out_dir/housemaster-$stamp.tar.gpg" | cut -f1))"
