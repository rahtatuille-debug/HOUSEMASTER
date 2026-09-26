#!/usr/bin/env bash
# Prove a backup can actually be restored: decrypt it, restore it into an
# empty database, and check every table has the same number of rows as when
# the backup was taken.
#
# Usage: BACKUP_PASSPHRASE=... scripts/verify_backup.sh <backup.tar.gpg> <empty database url>
#
# The target database must be empty and must NOT be production. The same
# steps are used for a real restore (see docs/BACKUPS.md).
set -euo pipefail

: "${BACKUP_PASSPHRASE:?Set BACKUP_PASSPHRASE to decrypt the backup}"
backup="${1:?Pass the .tar.gpg backup file}"
target="${2:?Pass the URL of an empty database to restore into}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "Decrypting..."
printf '%s' "$BACKUP_PASSPHRASE" | gpg --batch --quiet --pinentry-mode loopback --passphrase-fd 0 \
  --decrypt --output "$work/backup.tar" "$backup"
tar -C "$work" -xf "$work/backup.tar"

echo "Restoring into the test database..."
pg_restore --no-owner --no-privileges --exit-on-error --dbname="$target" "$work/database.dump"

echo "Comparing row counts..."
"$(dirname "$0")/row_counts.sh" "$target" > "$work/restored_counts.txt"
if ! diff -u "$work/row_counts.txt" "$work/restored_counts.txt"; then
  echo "FAILED: the restored database doesn't match the backup's row counts." >&2
  exit 1
fi
echo "OK: $(wc -l < "$work/row_counts.txt") tables and $(awk '{s+=$2} END {print s}' "$work/row_counts.txt") rows restored and match."
