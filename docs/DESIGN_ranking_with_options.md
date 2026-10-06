# Design note: ranking when students take different subjects

Status: note only (D-1, optional). Nothing here is built.

## Today (after D-1)

- **Ranking rule.** A student's overall position is their average subject percentage (8-4-4: mean points, then average).
  Students are compared within the same curriculum and group.
- **Incomplete marks.** A student is ranked only with marks in at least `School.ranking_min_share` % (default 75) of the
  usual number of subjects in their group (the median). Otherwise the student shows "Not ranked: incomplete marks
  (n of m subjects)" and doesn't push anyone else down.
- **Where the rule applies.** The same rule is used on the performance pages, the grades export and the 8-4-4 report
  card.
- **Basis.** Every row shows its basis: subjects and marks counted, and the usual number of subjects.

## The open question

Electives and options (sciences vs humanities, IB HL/SL, a missing language) mean students in one group legitimately
take different numbers of subjects. A 75% share copes with one or two missing options, but:

- an average over 7 subjects and one over 9 are compared as if they were the same thing;
- a student dropping a weak subject can rise in the ranking.

## Options

| | Rule | For | Against |
|---|---|---|---|
| A. Keep D-1 (default) | Average of what each student takes, with the completeness share | Simple; already consistent everywhere | Different subject sets still compared |
| B. Best N | Rank on each student's best N subjects (KCSE-style "best 7"), N set per year group | Familiar in Kenya; fair across options | Hides weak subjects; needs N per year group |
| C. Core only | Rank on the subjects every student in the group takes | Like-for-like | Ignores options entirely; small cores rank on little |
| D. No overall rank where subject sets differ | Show subject positions only | Most honest | Schools that report positions will object |

## Recommendation

Keep A. Offer B as a per-year-group setting **only if** a pilot school asks for it.
[VERIFY: whether KCSE best-7 rules apply to internal school rankings in pilot schools.]
