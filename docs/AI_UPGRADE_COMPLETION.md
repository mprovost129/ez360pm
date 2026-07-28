# EZ360PM AI Upgrade Completion Point

## Conclusion

V1.16 is the recommended stopping point for speculative AI development. The
assistant now has the complete code-side foundation needed for controlled real
use:

- company-scoped read tools and record links;
- notes, timers, clients, contacts, projects, and status actions;
- proposal and invoice drafting and controlled revision;
- deterministic pricing, time attachment, retainer credits, and payment logic;
- exact confirmation for issuing, sending, follow-ups, voiding, manual payments,
  and time release;
- prompt-injection, explicit-intent, idempotency, stale-data, and tenant-isolation
  protections;
- company controls, budgets, privacy acknowledgement, retention, audit export,
  pilot access, circuit breaker, feedback, incidents, evaluations, and readiness;
- draft-quality and follow-up evidence;
- bounded multi-turn context, server-verified current-page context, and a
  persistent confirmation Action Center;
- OpenAI request troubleshooting IDs, optional organization/project scoping, and
  model-alias stability warnings.

No additional AI capability is recommended before live testing.

## Deliberately not recommended now

The following are not missing implementation tasks. They are evidence-gated or
outside the intended safety boundary:

- scheduled or repeating reminders;
- scheduled proposal or invoice drafts;
- batch client communication;
- autonomous document issuing or sending;
- autonomous project-status changes;
- automatic payment entry from email, bank text, or inferred client messages;
- refunds, chargebacks, fund transfers, or other money movement;
- modification of paid invoices or accepted proposal history;
- deletion of financial or delivery audit history;
- unrestricted database, email, Stripe, file, web, shell, or code tools;
- training or fine-tuning on private customer records.

## Evidence required before one narrow scheduled workflow

Consider a scheduled feature only after the existing evidence screens show that
one specific manual action is repeatedly:

1. requested in the same circumstances;
2. approved with little or no revision;
3. sent to the expected recipient;
4. free from privacy, financial, and support incidents;
5. useful enough to justify scheduling;
6. still separately reviewable and cancelable.

Even then, schedule preparation first—not autonomous sending.

## External work that code cannot complete here

Before production use:

- install the pinned dependencies and run the full Django suite;
- run migrations, deployment checks, contract evaluations, and the live OpenAI
  read-only baseline;
- configure current OpenAI model pricing and company limits;
- perform SMTP success/failure, Stripe webhook replay, backup, and restore drills;
- complete a controlled pilot with real clients and projects;
- review customer-facing privacy language and decide whether an OpenAI DPA or
  qualifying data-retention arrangement is required;
- map AI allowances to subscription plans only when EZ360PM becomes a SaaS
  product.

Future AI changes should come from the real-use log, failed evaluations, user
feedback, or repeated manual behavior—not from adding features merely because AI
can perform them.
