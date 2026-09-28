# Backups and restoring

HouseMaster's data lives in one Neon Postgres database. There are two
layers of protection.

## Where things stand (checked 2026-09-28)

- **No nightly backup has ever succeeded.** The workflow's runs on
  2026-09-27 and 2026-09-28 both stopped at "Check the secrets are set",
  because `BACKUP_DATABASE_URL` and `BACKUP_PASSPHRASE` aren't set. Until
  they are, the only copy of the data is Neon's short restore window.
- The scripts themselves work: a full local drill (read-only backup role →
  encrypted dump → restore into an empty database → row counts compared)
  passed on 2026-09-28 with 43 tables and 41,107 rows. See "Rehearsing
  locally" below.
- Setting this up is the owner's first task: H-1 and H-2 in
  [HUMAN_ACTIONS.md](HUMAN_ACTIONS.md).

## Recovery targets

Fill these in from the first real drill, and update them each term.

| | Target | Measured at the last drill | Date of that drill |
|---|---|---|---|
| **RPO** (most data we can lose) | 24 hours (nightly backup) | | |
| **RTO** (time to be back up from a backup) | 2 hours | | |

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

1. **Create a read-only login for backups.** The backup only reads, so it
   gets its own role that can't change anything, even if its password
   leaks. Neon console → your project → **Connect**: switch **connection
   pooling off** (the host must *not* contain `-pooler`; `pg_dump` doesn't
   work reliably through the pooler) and copy the owner's connection string.
   Then, from a computer with `psql`:

   ```bash
   BACKUP_ROLE_PASSWORD="$(openssl rand -hex 24)"
   psql "postgresql://neondb_owner:...@ep-xxx.region.aws.neon.tech/neondb?sslmode=require" \
     -v backup_password="$BACKUP_ROLE_PASSWORD" -v app_owner=neondb_owner -v dbname=neondb \
     -f scripts/create_backup_role.sql
   ```

   The file explains every grant. Your backup connection string is the same
   direct string with `neondb_owner:<owner password>` replaced by
   `housemaster_backup:$BACKUP_ROLE_PASSWORD`. Check it can't write:
   `psql "<backup string>" -c "delete from students_student"` must fail with
   "cannot execute DELETE in a read-only transaction".
2. **Make a backup passphrase.** A long random phrase, e.g. five or six
   random words. **Save it in your password manager now.** If it's lost,
   every backup is unreadable, and nobody can recover it.
3. **Add both as repository secrets.** GitHub → the HOUSEMASTER repository →
   **Settings → Secrets and variables → Actions → New repository secret**:
   - `BACKUP_DATABASE_URL` = the read-only backup connection string from step 1
   - `BACKUP_PASSPHRASE` = the passphrase from step 2
4. **Run it once by hand.** **Actions** tab → **Database backup** → **Run
   workflow**. It should finish green in a few minutes, with an
   "OK: ... tables and ... rows restored and match" line in the
   "Prove the backup restores" step.

### Optional: a copy outside GitHub

GitHub keeps each backup for 90 days, and GitHub is also where the code
lives. To keep a copy somewhere else, create a bucket with any
S3-compatible storage (AWS S3, Cloudflare R2, Backblaze B2) and a key that
can only write to it, then add these repository secrets:

| Secret | Value |
|---|---|
| `BACKUP_S3_BUCKET` | the bucket name (setting this switches the step on) |
| `BACKUP_S3_ACCESS_KEY_ID` / `BACKUP_S3_SECRET_ACCESS_KEY` | the key |
| `BACKUP_S3_REGION` | the region, or leave unset for `auto` (R2) |
| `BACKUP_S3_ENDPOINT` | only for non-AWS storage, e.g. `https://<account>.r2.cloudflarestorage.com` |

The files are already encrypted with the passphrase. Set a lifecycle rule
on the bucket to delete old copies after however long counsel says to keep
them.

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

## Restore drill checklist (every term)

- [ ] `BACKUP_DATABASE_URL` (the read-only role) and `BACKUP_PASSPHRASE` are
      set as repository secrets; the passphrase is also in a password
      manager outside GitHub.
- [ ] A manual **Run workflow** finishes green, including "Prove the backup
      restores".
- [ ] Download the artifact, decrypt it on your own computer and restore
      into a fresh local Postgres with `scripts/verify_backup.sh`.
- [ ] Run `scripts/row_counts.sh` against production (read-only role) and
      against the restore; the counts match within the backup window.
- [ ] Point a local copy of the app at the restore and open one student's
      report card.
- [ ] Record the time to restore (RTO) and the backup's age (RPO) in the
      table at the top of this file.
- [ ] Confirm a copy exists outside GitHub (the optional bucket, or a
      download kept somewhere safe).
- [ ] Put the next drill in the calendar.

## Rehearsing locally

The whole chain can be tried against a local Postgres with no production
access (this is how the scripts were checked on 2026-09-28):

```bash
# a throwaway database with realistic data
createdb hm_source && createdb hm_restore
DJANGO_DEBUG=True DATABASE_URL=postgresql://localhost/hm_source python manage.py migrate
DJANGO_DEBUG=True DATABASE_URL=postgresql://localhost/hm_source DEMO_PASSWORD=Local-Demo-Only-123 \
  python manage.py seed_demo_school
# read-only role (the connecting role needs CREATEROLE, as Neon's owner has)
psql postgresql://localhost/hm_source -v backup_password=local-only -v app_owner="$USER" \
  -v dbname=hm_source -f scripts/create_backup_role.sql
# back up with the read-only role, then restore and compare
export BACKUP_PASSPHRASE=local-only-passphrase
DATABASE_URL=postgresql://housemaster_backup:local-only@localhost/hm_source scripts/backup_db.sh /tmp/drill
scripts/verify_backup.sh /tmp/drill/*.tar.gpg postgresql://localhost/hm_restore
```
