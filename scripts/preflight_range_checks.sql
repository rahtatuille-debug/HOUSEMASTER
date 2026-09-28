-- Run before deploying backend Phase 2 (docs/HUMAN_ACTIONS.md, H-6), with
-- the read-only backup connection string:
--
--   psql "<read-only backup string>" -f scripts/preflight_range_checks.sql
--
-- Every count must be 0. The gradebook migration refuses to add its
-- constraints while any grade breaks them. Only IDs are shown, never names.

\echo 'Grades with a mark below 0, above the maximum, or a maximum of 0 or less:'
SELECT count(*) AS bad_grades FROM gradebook_grade
 WHERE max_score <= 0 OR score < 0 OR score > max_score;
SELECT id FROM gradebook_grade
 WHERE max_score <= 0 OR score < 0 OR score > max_score
 ORDER BY id LIMIT 50;

-- Attendance isn't blocked by the migration (the rule depends on today's
-- date), but new or edited records more than a day ahead are refused, so
-- fix these now.
\echo 'Attendance records dated more than one day in the future:'
SELECT count(*) AS future_attendance FROM attendance_attendancerecord
 WHERE date > (now() AT TIME ZONE 'Africa/Nairobi')::date + 1;
SELECT id FROM attendance_attendancerecord
 WHERE date > (now() AT TIME ZONE 'Africa/Nairobi')::date + 1
 ORDER BY id LIMIT 50;
