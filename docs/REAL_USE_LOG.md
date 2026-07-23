# Real-use issue log

Phase 7 work starts from repeated production friction, not feature ideas. Add one
row when EZ360PM interrupts a real job, creates accounting risk, or requires a
workaround. Do not include client names, addresses, email addresses, payment
references, or other sensitive data.

| Date | Workflow | Device/browser | Expected | What happened | Workaround | Frequency | Risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-07-23 | Edit a stopped timer entry | Windows / Chrome | Entering 6 hours saves and displays exactly 6 hours | The edited entry retained about 1h 2m of its original paused duration and displayed about an hour less than the entered duration | Entered 7h 2m to make the list display 6h | First | High |
| | | | | | | First / repeated | Low / medium / high |

## Triage rule

Rank an item for implementation when at least one condition is true:

1. It risks incorrect money, lost time, privacy, or inaccessible records.
2. It blocks the primary intake-to-payment workflow without a safe workaround.
3. It has happened at least three times in a month.
4. A measured accessibility, mobile, print, or performance problem prevents the
   workflow from completing.

For each implemented fix, link the test or operational check that prevents a
regression and note the deployment date in the row.

## Resolution notes

- **2026-07-23:** Exact-duration editing now uses active duration while
  preserving pause history. Regression coverage:
  `projects.tests.test_time.TimeEntryViewTests.test_edit_paused_timer_uses_and_saves_exact_active_duration`.
