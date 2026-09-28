DRAFT — NOT LEGAL ADVICE — for review and adaptation by a qualified Kenyan data-protection advocate.

# Sub-processors

Every outside service that stores or sees personal data held in
HouseMaster. This list is Annex C of the data processing agreement; a
school must be told before a new one is added (DPA clause 7).

What each service receives comes from the code and configuration on
2026-09-28. Regions and legal terms could not be checked from the
environment these drafts were written in: every region, transfer ground
and link below is **[TO CONFIRM]** by the owner (from the provider's
dashboard and current terms) and by counsel. Hosting abroad counts as a
cross-border transfer [VERIFY]; the ground for each transfer is question 3
in [QUESTIONS_FOR_COUNSEL.md](QUESTIONS_FOR_COUNSEL.md).

| Sub-processor | Purpose | Personal data it handles | Region | Transfer ground | Terms / DPA | Reviewed |
|---|---|---|---|---|---|---|
| **Neon** (Neon Inc.) | The database: every record in HouseMaster | Everything in Annex A of the DPA: pupils (names, dates of birth, gender, nationality, class, health notes, photos, grades, attendance, reports), parents (names, contact details, relationship, links to children), staff (names, emails, roles), messages, alerts, the activity log | **[TO CONFIRM]**: the region chosen when the Neon project was created (the brief says US) | **[TO CONFIRM]** | Neon's DPA, linked from its legal pages [VERIFY link] | 2026-09-28, from the configuration only |
| **Render** (Render Services, Inc.) | Runs the backend application | Everything the database holds passes through it while requests are served; request logs (IP addresses, paths, times) | **[TO CONFIRM]**: the service's region in the Render dashboard (the brief says US) | **[TO CONFIRM]** | Render's DPA [VERIFY link] | 2026-09-28, from the configuration only |
| **Vercel** (Vercel Inc.) | Serves the frontend (the web pages) | Visitors' IP addresses and request logs. No school records: the pages call the backend directly | Global edge network **[TO CONFIRM]** | **[TO CONFIRM]** | Vercel's DPA [VERIFY link] | 2026-09-28 |
| **Sentry** (Functional Software, Inc.) | Error reports from the backend and the frontend | Error details, which can include fragments of the data being handled when the error happened (a pupil's name in an error message, a URL with an ID); IP addresses are not sent (`send_default_pii` is off in both) | **[TO CONFIRM]**: US or EU, depending on the Sentry organisation (the CSP allows both) | **[TO CONFIRM]** | Sentry's DPA [VERIFY link] | 2026-09-28 |
| **Google** (Gemini API) | Drafts report comments and announcement wording | Minimised data only (docs/AI_DATA_FLOW.md): subject names, marks, attendance counts and a placeholder instead of the pupil's name; announcement briefs with known names and emails masked. A first name typed into a brief is not caught | **[TO CONFIRM]** | **[TO CONFIRM]** | Gemini API terms and Google's data processing addendum; **must be a paid tier whose terms rule out training on prompts** (HUMAN_ACTIONS.md, H-8) [VERIFY] | 2026-09-28 |
| **Email provider** (not chosen yet) | Sends invites, password resets, notifications and urgent alerts | Recipients' names and email addresses; the email's content (for example an alert's text, a report being ready, an invite link) | **[TO CONFIRM]** | **[TO CONFIRM]** | The chosen provider's DPA | Not yet |
| **GitHub** (Actions) | Runs the nightly database backup and keeps it for 90 days as an encrypted file | The whole database, **encrypted** with a passphrase GitHub doesn't hold (docs/BACKUPS.md). The backup is also restored into a throwaway database on GitHub's runner to prove it works, so for a few minutes it exists there **unencrypted** | **[TO CONFIRM]** | **[TO CONFIRM]** | GitHub's data protection agreement [VERIFY link] | 2026-09-28 |
| **S3-compatible storage** (optional, not set up) | A second copy of the encrypted backup, if the owner sets `BACKUP_S3_BUCKET` | The encrypted backup file only | Chosen by the owner | **[TO CONFIRM]** | The chosen provider's DPA | Not set up |

## Not sub-processors any more

- **Google Fonts**: the frontend loaded its fonts from Google, which saw
  every visitor's IP address. Since the follow-up release (F-2) the fonts
  are served from HouseMaster's own site.

## Worth knowing

- **Backups on GitHub**: the restore check runs the backup, decrypted, on a
  GitHub runner. Counsel should confirm this is acceptable, or the check
  should move somewhere else (question 3).
- **Error reports** are the likeliest place for personal data to reach a
  service unnoticed. Keep Sentry's own data scrubbing on, and don't raise
  its retention above what is needed.
