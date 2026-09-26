# Backups and restoring

HouseMaster's data lives in one Neon Postgres database. There are two
layers of protection.

## 1. Neon's own restore window

Neon keeps a short history of the database and can restore it to an
earlier point in time. How far back depends on the Neon plan, and the free
plan's window is short. Check it in the Neon console: open the project,
then **Settings → Storage** (look for "history retention" or "restore
window"). Use it for "we deleted something in the last few hours".

To use it: Neon console → **Branches** → **Restore** (or create a branch
from a past point in time), then point Render's `DATABASE_URL` at it if
you restored into a new branch.

This protects against mistakes, but not against losing the Neon account or
project, and it doesn't reach back far on the free plan. That's what the
second layer is for.

## 2. Nightly encrypted backups (GitHub Actions)

`.github/workflows/backup.yml` runs every night at 00:17 UTC (03:17 in
Nairobi). It:

1. takes a full copy of the database with `pg_dump`,
2. encrypts it with a passphrase only you know (AES-256),
3. **restores it into a throwaway database and checks every table has the
   same number of rows**, so each backup is proven to work, not assumed to,
4. keeps the encrypted file for 90 days as a download on the workflow run.

The repository is public, so anyone can download these files. That's why
they're encrypted. Without the passphrase they're unreadable.

If a night's backup fails, GitHub emails whoever last edited the workflow
file, and the run shows a red cross under the repository's **Actions** tab.

### One-time setup

1. **Get Neon's direct connection string.** Neon console → your project →
   **Connect** (or Dashboard → Connection details). Switch **connection
   pooling off**; the host must *not* contain `-pooler`. Copy the whole
   `postgresql://...` string. (`pg_dump` doesn't work reliably through the
   pooler.)
2. **Make a backup passphrase.** A long random phrase, e.g. five or six
   random words. **Save it in your password manager now.** If it's lost,
   every backup is unreadable, and nobody can recover it.
3. **Add both as repository secrets.** GitHub → the HOUSEMASTER repository →
   **Settings → Secrets and variables → Actions → New repository secret**:
   - `BACKUP_DATABASE_URL` = the direct connection string from step 1
   - `BACKUP_PASSPHRASE` = the passphrase from step 2
4. **Run it once by hand.** **Actions** tab → **Database backup** → **Run
   workflow**. It should finish green in a few minutes, with an
   "OK: ... tables and ... rows restored and match" line in the
   "Prove the backup restores" step.

### Things to know

- GitHub pauses scheduled workflows on a public repository after **60 days
  with no commits**. If the repository goes quiet, check the Actions tab;
  it offers a button to turn the schedule back on.
- Backups older than 90 days are deleted automatically. For a copy you want
  to keep for longer (e.g. end of each school year), download it and store
  it somewhere safe, such as a private cloud drive. It's already encrypted.
- Each backup contains everything: students, grades, health notes, photos,
  messages, accounts. Treat the passphrase like the keys to all of it.

## Restoring from a nightly backup

Only do this for real data loss. It replaces what the app uses.

You need a computer with PostgreSQL 17 client tools (`pg_restore`,
`psql`) and `gpg`, and this repository checked out.

1. **Download the backup.** GitHub → **Actions** → **Database backup** →
   pick the run from before the problem → **Artifacts** → download. Unzip it
   to get `housemaster-<date>.tar.gpg`.
2. **Create an empty database to restore into.** In Neon, create a new
   branch or database (don't restore over the broken one; keep it until
   you're sure). Copy its *direct* connection string.
3. **Restore and check it** (from the repository folder):

   ```bash
   BACKUP_PASSPHRASE='your passphrase' \
     scripts/verify_backup.sh housemaster-<date>.tar.gpg 'postgresql://...new database...'
   ```

   It decrypts the backup, restores it, and checks every table's row count
   against the backup. It must end with `OK: ... restored and match`.
4. **Point the app at it.** Render → the backend service → **Environment** →
   set `DATABASE_URL` to the new database's connection string (the pooled
   one is fine here) → save. Render redeploys.
5. **Check the live site**, then update `BACKUP_DATABASE_URL` in GitHub so
   the nightly backups follow the new database.

## Testing a restore without touching production

Do this once a term, so you know the steps work:

1. Download last night's backup as in step 1 above.
2. Create a throwaway Neon branch (or use any empty Postgres database).
3. Run `scripts/verify_backup.sh` against it as in step 3.
4. Delete the throwaway branch.
