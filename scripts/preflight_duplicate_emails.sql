-- Run before deploying backend Phase 2 (docs/HUMAN_ACTIONS.md, H-6), with
-- the read-only backup connection string:
--
--   psql "<read-only backup string>" -f scripts/preflight_duplicate_emails.sql
--
-- The count must be 0: the accounts migration adds a unique index on the
-- lower-cased email and refuses to run while two accounts share one. Only
-- user IDs are shown; look the accounts up in the app or the Django admin.

\echo 'Email addresses used by more than one account (case-insensitive):'
SELECT count(*) AS shared_emails FROM (
  SELECT lower(email) FROM auth_user WHERE email <> '' GROUP BY lower(email) HAVING count(*) > 1
) AS shared;

\echo 'The user IDs involved, grouped:'
SELECT string_agg(id::text, ', ' ORDER BY id) AS user_ids FROM auth_user
 WHERE email <> '' GROUP BY lower(email) HAVING count(*) > 1;
