# EZ360PM V1.6 - AI Real-Use Refinement

## Added

- Deterministic, company-scoped workflow alerts in the assistant drawer. These
  checks run against EZ360PM data and do not call the OpenAI API.
- Dismissible alerts for stale leads, possibly forgotten timers, approved
  projects without funded retainers, completed projects with unbilled time, and
  clients without an email recipient.
- Configurable alert limits, stale thresholds, reminder dismissal period, and
  refresh interval.
- Personalized command suggestions based on completed assistant actions, with a
  safe fixed suggestion library rather than private-prompt training.
- A company/user-scoped AI usage and reliability screen showing requests,
  completion/failure counts, estimated API cost, latency, action outcomes, and
  capability-level results.
- Minimal operational event logging for ambiguities, requested revisions,
  canceled actions, tool failures, suggestion use, and dismissed alerts.
- Additional company-isolation and refinement regression tests.

## Safety boundary

- Proactive alerts are read-only and local; they cannot create or send anything.
- Dismissing an alert only hides that exact condition for the configured period.
- Suggestions are fixed commands selected from known capabilities. EZ360PM does
  not train on private prompts or business data.
- Scheduled drafts, reminders, and autonomous sending remain deferred until real
  usage demonstrates a repeated manually approved need.

## Database

Run migration `assistant.0003_aievent_aiinsightdismissal`.
