-- A read-only database role for the nightly backup (docs/BACKUPS.md).
--
-- The backup only needs to read. Giving it its own read-only login means
-- the BACKUP_DATABASE_URL secret in GitHub can't change or delete data even
-- if it leaks.
--
-- Run it once with psql, connected as the role that owns the app's tables
-- (on Neon this is usually neondb_owner; use the *direct*, non-pooler
-- connection string):
--
--   psql "postgresql://neondb_owner:...@ep-xxx.region.aws.neon.tech/neondb?sslmode=require" \
--     -v backup_password="$(openssl rand -base64 32)" \
--     -v app_owner=neondb_owner \
--     -v dbname=neondb \
--     -f scripts/create_backup_role.sql
--
-- (Generate the password into a variable instead if you need to copy it:
--  it goes into BACKUP_DATABASE_URL and nowhere else.)
--
-- What pg_dump needs, and why each grant is here:
--   CONNECT on the database      to log in at all
--   USAGE on schema public       to see the tables in it
--   SELECT on all tables         to read the rows
--   SELECT on all sequences      to record where each ID counter is
--   default privileges           so tables and sequences created by future
--                                migrations are readable too, without
--                                re-running this file
--   default_transaction_read_only  a second guard: every session this role
--                                opens is read-only
\set ON_ERROR_STOP on

CREATE ROLE housemaster_backup WITH LOGIN PASSWORD :'backup_password';
GRANT CONNECT ON DATABASE :"dbname" TO housemaster_backup;
GRANT USAGE ON SCHEMA public TO housemaster_backup;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO housemaster_backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO housemaster_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE :"app_owner" IN SCHEMA public GRANT SELECT ON TABLES TO housemaster_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE :"app_owner" IN SCHEMA public GRANT SELECT ON SEQUENCES TO housemaster_backup;
ALTER ROLE housemaster_backup SET default_transaction_read_only = on;
