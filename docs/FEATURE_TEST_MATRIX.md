# Feature-to-Test Matrix

Status as of 2026-08-01. “Backend” means deterministic Django tests. “Browser”
means rendered Chromium interaction. “Operational” means a controlled production
or provider check that automated tests intentionally cannot prove.

| Product area | Backend evidence | Browser evidence | Operational/manual evidence | Next high-value gap |
| --- | --- | --- | --- | --- |
| Authentication and company isolation | `accounts/tests`, `core/tests/test_scoping.py` | Login is exercised by every browser journey | Production password-reset delivery | Add explicit lockout browser journey |
| Intake and quick notes | `intake/tests/test_intake.py` | Client change routes to selected project activity | Mobile capture usability | Add inquiry-to-client/project conversion |
| Clients and contacts | `clients/tests` | Indirect fixture/navigation coverage | Real-data import review | Add create/edit/primary-contact journey |
| Projects and lifecycle | `projects/tests/test_projects.py` | Project activity is visibly updated | Real project closeout review | Add lead → approved → active → complete journey |
| Client forms and uploads | `projects/tests/test_client_forms.py` and upload repair tests | Owner creates/emails a form; anonymous client answers and uploads a PDF; owner sees project specifications | Resend link and object-storage download | Add save-progress, revoke-link, and storage-download browser cases |
| Time tracking | `projects/tests/test_time.py` | Not yet | Mobile timer interruption/recovery | Add start, pause, resume, stop, and manual-entry journey |
| Proposals and public acceptance | `documents/tests/test_proposals.py` | Not yet | PDF/print and real client device review | Add proposal send/public acceptance journey |
| Retainer and final invoice | Proposal/payment workflow tests | Not yet | Real invoice/PDF review | Add proposal → retainer → final-credit journey |
| Manual payments and refunds | Billing, payment-system, reporting, and audit tests | Paid → partially paid with append-only refund history | Check/cash reconciliation | Add full/partial/multiple-refund visual cases |
| Stripe Checkout and webhooks | `documents/tests/test_payment_system.py`, `test_automation.py` | Provider UI intentionally mocked out | Controlled live Checkout/webhook/refund/dispute drill | Add mocked public Checkout redirect journey |
| Revenue and dashboard totals | `core/tests/test_reporting.py`, AI revenue tests | Invoice state is visible; report navigation not yet covered | Period comparison with Stripe/bank records | Add revenue period/filter journey |
| Resend delivery and events | `documents/tests/test_resend.py` | Not yet | Live domain, delivery, bounce, and rollback drill | Add mocked send/delivery-history journey |
| AI assistant safety and actions | `assistant/tests` | Not yet | Dated-model evaluation and limited live provider smoke test | Add drawer read/action-confirmation journey |
| Deployment and data integrity | deployment-safety, checks, migration, and data-audit tests | Not applicable | Backup/restore and Render deploy drill | Automate recurring restore verification |

## Governance rules

- Financial calculations, permissions, public-token access, provider replay, and
  migration repairs require backend regression coverage.
- Cross-page workflows, JavaScript-assisted controls, and client-facing forms
  require browser coverage.
- Browser tests use local fake data and deterministic providers only.
- Live-provider checks must be separately invoked and must identify any real
  external side effect before execution.
- A green matrix row means its stated evidence exists; it does not mean the area
  is bug-free or that deferred evidence can be skipped.
