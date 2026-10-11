# The extra performance charts

Five charts about one student's results, on the Performance page (pick **Student**) and, where noted, on the
student's profile and the parent's **Progress** tab. Every number is worked out exactly as everywhere else in
HouseMaster:

- a mark is a percentage (score ÷ out of);
- a subject result is the mean of each assessment type's marks, combined by the school's assessment-type weights;
- a term average is the mean of the subject results.

Schools that use levels (CBC, IGCSE 9–1 and others) see the same percentages with the level beside them.

A missing term, subject or mark is always shown as a gap or "no marks", never as zero.

## Comparisons and small classes

On **every** performance chart (these five, the existing Performance page, the staff student profile and the
teacher's class dashboard), an average of another group (a class, the year group, the school) is shown only when
**at least 5 students** in it have marks for that subject, assessment type or term. Below that, a group average
would be close to naming one or two children's results, so it is left out ("—" in tables).

The group you are looking at always shows its own figures (a teacher looking at their class of 3 still sees its
average); only comparisons follow the rule.

This is one setting in the code: `MIN_COMPARE_STUDENTS = 5` in `reporting/analytics.py`.

Comparisons are always averages. No chart ever shows another student's name or marks.

## P-1 Subjects over terms

- **What it shows:** one line per subject, term by term. The first six subjects with the most terms of marks are
  shown; tick boxes show or hide others, and the choice is remembered on that device.
- **Compare with class average:** draws the class as a dashed line for the chosen subjects, when allowed (see
  above).
- **Not enough terms:** with fewer than 2 terms of marks it says "Not enough terms yet" and offers the table.
- **For a class, year group or the whole school:** each subject's average for the group.
- **Who sees it:**
  - Staff, for students and groups they can already see.
  - Parents and the student's own account, for terms with a **finalized report** only, and with no class line.

## P-2 Assessment types

- **What it shows:** the student's average in each of the school's own assessment types in a term (all subjects,
  or one), next to the class average when allowed.
- **The weights** the school uses are listed for information; nothing is weighted twice.
- **Too few marks:** a type with fewer marks than the school's "marks needed" setting (`support_min_marks`,
  default 3) is not drawn, and the table says "Not enough data (n marks; needs 3)".
- **A large gap:** when two types are 10 or more points apart, a neutral sentence says so.
- **Who sees it:** staff only. Parents' view of marks has never included the assessment type, so this chart isn't
  offered to them.

## P-3 Marks through the term

- **What it shows:** every mark in the term as a point, by date. "All subjects" shows the average of each day's
  marks; one subject shows each of its marks.
- **Dates:** marks have no "assessment date" in HouseMaster, so the date is **the day the mark was recorded**, on
  the school's own clock (its time zone).
- **Marks outside the term:** marks recorded outside the term's dates (for example, entered or imported later) are
  left off the chart and counted in a note.
- **No class comparison:** without an assessment date, the class's "same assessment" can't be identified reliably.
- **Who sees it:**
  - Staff.
  - Parents and the student, without assessment types (as in their marks list).

## P-4 Position over terms

- **What it shows:** the student's overall position each term in their class and year group (and the whole
  school, for admins and leadership), shown as "4th of 38". 1st is at the top.
- **Same as the ranked tables:** positions come from the same calculation the ranked tables and report cards use.
  - Tied students share a position.
  - Students are only ranked against others in the same curriculum.
  - If the school requires a share of subjects to be ranked, a term where the student had too few is a gap with
    the reason: "Not ranked: incomplete marks (x of y subjects)".
- **CBC:** learners aren't ranked, so staff see that explanation instead.
- **Who sees it:**
  - Staff.
  - Parents only where their child's finalized 8-4-4 report card already shows stream and form positions.
  - Other parents don't see positions here, because they don't see them anywhere else.

## P-5 Strengths

- **What it shows:** a "radar" with one spoke per subject for the chosen term, on a fixed 0–100% scale, with the
  class as a dashed outline when every subject has an allowed class average.
- **The sentence underneath** names the strongest and weakest subjects.
- **Fewer than 3 or more than 10 subjects:** a radar is easy to misread, so the chart is a plain bar chart instead
  and says why.
- **Who sees it:**
  - Staff.
  - Parents and the student, without the class outline.
