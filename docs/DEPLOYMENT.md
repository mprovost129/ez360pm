# Deployment and Integration Setup

This is the operational handoff for the personal MVP. Secrets belong in the
deployment environment, never in source control or Django admin fields.

## Production secret key

Generate a unique Django secret key locally, then save only the generated value
as `SECRET_KEY` in the Render service's Environment settings:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Do not copy the blank `SECRET_KEY` entry from `.env.example` as-is, reuse a CI
value, or commit the generated value. Django's production startup gate rejects
short, predictable, and `django-insecure-` keys before the service starts.

## Create the first owner

For a new installation, create the Company and owner together with the
idempotent bootstrap command:

```powershell
$env:EZ360PM_OWNER_PASSWORD='<strong temporary value>'
.\.venv\Scripts\python.exe manage.py bootstrap_personal --company-name "Provost Home Design" --email "owner@example.com" --first-name "Michael" --last-name "Provost" --no-input
Remove-Item Env:EZ360PM_OWNER_PASSWORD
```

The standard `createsuperuser` command is also supported, but its Company prompt
expects the primary key of an existing Company. It cannot create the initial
Company itself.

## Release checks

Run these after installing dependencies and before serving traffic:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
.\.venv\Scripts\python.exe manage.py deployment_check
.\.venv\Scripts\python.exe manage.py data_audit --fail-on-warning
```

For production, set `DJANGO_SETTINGS_MODULE=config.Settings.prod`. Both the
Docker command and the Render `Procfile` call `bin/start.sh`. That single startup
gate runs migrations, Django's deployment security checks, the database/cache
check, and the read-only data audit before Gunicorn can receive traffic.

Set `PUBLIC_BASE_URL` to the public HTTPS origin with no trailing slash. Public
document links in email and Stripe redirects are built from this value.

## Container and reverse-proxy requirements

The production image collects static assets with nonsecret build-only settings,
runs as the unprivileged `ez360pm` user, applies pending migrations before each
container start, writes Gunicorn logs to stdout/stderr, honors the platform's
`PORT` and `WEB_CONCURRENCY` values, and exposes a Docker health check against
`/health/`. If migration fails, Gunicorn does not start and the deployment is
not promoted to receive traffic. `EZ360PM_OWNER_PASSWORD` is strictly a one-time
bootstrap value and must not remain in the deployment environment afterward.

`.dockerignore` excludes `.env`, repository metadata, local virtualenvs, logs,
media, test output, and other workstation files from the build context. Never
pass runtime secrets as Docker build arguments or copy `.env` into an image.

The application trusts `X-Forwarded-Proto: https` from the deployment proxy so
Django can identify secure requests before enforcing HTTPS redirects. Configure
the public load balancer to replace—not append an untrusted client value for—
that header, terminate TLS, and forward only to the private application service.

Company logos can use private Amazon S3 storage. Set `USE_S3_MEDIA=True` together
with `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_REGION_NAME`, `AWS_ACCESS_KEY_ID`, and
`AWS_SECRET_ACCESS_KEY`. Objects are stored below the `media/` prefix, retain
their original content type, and use one-hour signed URLs; keep S3 Block Public
Access enabled. The IAM principal needs `s3:ListBucket` on the bucket and
`s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on `media/*`.

When `USE_S3_MEDIA` is false, the default filesystem `MEDIA_ROOT` needs a
persistent volume at `/app/media` before company logos are treated as durable.
Static assets always remain on WhiteNoise and do not need that volume.

For a remote PostgreSQL service that requires TLS, set `DB_SSLMODE=require` (or
the stricter mode supplied by the provider). `DB_CONN_MAX_AGE` defaults to 60
seconds in production and Django validates a persistent connection before reuse.

## Email

Configure Django's email environment values:

```text
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=<provider SMTP host>
EMAIL_PORT=587
EMAIL_TIMEOUT=10
EMAIL_HOST_USER=<provider username>
EMAIL_HOST_PASSWORD=<provider credential>
DEFAULT_FROM_EMAIL=Provost Home Design <verified-sender@example.com>
```

Render Free web services block outbound connections to SMTP ports 25, 465, and
587. SMTP delivery therefore requires a paid Render web service; on the Free
plan, use an email backend/provider that sends through an HTTPS API instead.
`EMAIL_TIMEOUT` limits an unreachable SMTP attempt so the request fails cleanly
before Gunicorn terminates the worker.

The Company email is used as Reply-To. Development may retain the console email
backend. Every client-document or internal-acceptance attempt creates a
`DocumentDelivery` row before contacting the backend; success or a safe failure
category is then recorded without storing credentials or message bodies. Failed
client, proposal-response, and payment notifications can be retried from the
document's delivery history without rewriting the original attempt.

For Stripe Checkout completion, the verified payment and a pending notification
are committed before the webhook acknowledgement. Fee lookup and notification
delivery run as best-effort post-response work so provider latency does not delay
Stripe's `2xx`; if the process is interrupted, the pending fee remains available
to Revenue reconciliation and the pending notification remains sendable from
the invoice delivery history. A separate task worker remains optional for a
future paid deployment rather than a requirement for the current free instance.

The login page exposes Django's email-based password reset flow, and an
authenticated owner can change their password from Company settings. Keep the
company/owner email deliverable so shell access is not required for routine
account recovery. Django Administration is intentionally limited to superusers.

## Stripe Checkout

Set both values or leave both blank:

```text
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

Create the Stripe webhook endpoint at:

```text
https://<public-host>/webhooks/stripe/
```

Subscribe it to:

- `checkout.session.completed`
- `checkout.session.async_payment_succeeded`

Also subscribe to `refund.created`, `refund.updated`, `charge.refunded`,
`charge.succeeded`, `charge.updated`, `charge.dispute.created`, and
`charge.dispute.closed` for fee, refund, and dispute reporting. Failed financial
adjustment imports appear under **Administration → Stripe webhook failures**.
The queue stores safe identifiers and error categories, never raw webhook
payloads. Stripe retries increase the attempt count; a successful replay marks
the item resolved automatically.
- `charge.succeeded`
- `charge.updated`
- `refund.created`
- `refund.updated`
- `charge.refunded`
- `charge.dispute.created`
- `charge.dispute.closed`

The installed Stripe Python SDK is `14.4.0`, pinned to API version
`2026-02-25.clover`. Configure the webhook endpoint to the same API version.
Checkout is shown only when both secrets are present and the issued invoice has
online payments enabled with a positive balance.

The server reloads and locks the invoice, calculates the current outstanding
balance, and creates the hosted Session. The webhook verifies Stripe's signature
against the raw request body and passes the resulting payment through the same
transactional service as manual payments. The unique Payment Intent ID makes
payment replay idempotent. Refunds, disputes, reversals, and later fee changes
are imported as append-only adjustments using unique Stripe provider IDs.

After configuration, confirm the Integrations screen reports Email and Stripe as
configured. Use a Stripe test-mode invoice first, replay its successful webhook,
and verify that only one Stripe Payment row exists and the invoice balance is
zero.


## Revenue & Fees release migration

Before serving the V1.1 code, apply the new account and document migrations:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
```

The migrations add `Company.books_closed_through`, the append-only
`PaymentAdjustment` ledger, current Stripe fee tracking, and append-only fee
reconciliation attempt history. Review the Revenue & Fees report and resolve
all pending fees before setting a year-end lock; the settings form also enforces
that prerequisite.
The report is payment-level net reporting; it does not reconcile Stripe payout
batches to individual bank deposits.

## Monitoring and data audit

Monitor `GET /health/` for an HTTP 200 response and `{"status":"ok"}`. This
endpoint proves that Django and PostgreSQL can answer a request; it deliberately
does not expose internal diagnostics.

Run the read-only integrity audit after each release and on a daily schedule:

```powershell
.\.venv\Scripts\python.exe manage.py data_audit --json --fail-on-warning
```

The command checks stored line/document totals, payment-derived invoice status,
retainer-credit relationships, invoiced-time relationships, payment/adjustment
and fee-attempt company boundaries, and document deliveries left pending for
more than 15 minutes. Use
`--company-id <id>` to isolate one company or `--pending-minutes <minutes>` to
change the delivery threshold. A nonzero result should alert the operator. The
audit never modifies records; investigate against a backup before making a
manual correction.

Tokenized proposal/invoice pages and PDFs return `private, no-store`, a
no-referrer policy, and `X-Robots-Tag: noindex, nofollow, noarchive`. These are
defense-in-depth controls; the public token must still be treated as a secret.

## PostgreSQL backup and restore drill

Use the hosting provider's encrypted daily PostgreSQL backups for routine
retention. At least monthly, restore the latest backup into a new, isolated
database—not over the live database—and record the recovery time.

For a provider that exposes PostgreSQL command-line access, the equivalent flow
is:

```powershell
pg_dump --format=custom --no-owner --file=<dated-backup-file> <live-database-url>
createdb <isolated-restore-database>
pg_restore --no-owner --dbname=<isolated-restore-database> <dated-backup-file>
```

Point a temporary EZ360PM environment at the isolated restore, then run:

```powershell
.\.venv\Scripts\python.exe manage.py deployment_check --skip-cache
.\.venv\Scripts\python.exe manage.py data_audit --fail-on-warning
```

Verify that the owner can sign in and open representative accepted proposals,
paid invoices, payment history, and attached time. Destroy the isolated restore
through the provider after the drill. Back up and restore `MEDIA_ROOT` separately
if company logos are stored on the application filesystem.

## Stripe webhook replay drill

In Stripe test mode, replay a previously successful Checkout event to the
production-like webhook endpoint. Confirm both deliveries return success, only
one Payment exists for the Payment Intent, the invoice balance is unchanged by
the replay, and `data_audit` still passes. Never edit a Stripe Payment directly
to repair a replay problem.

## Real-use evidence

Record workflow friction in [the real-use issue log](REAL_USE_LOG.md), excluding
client or payment-sensitive information. Phase 7 changes should cite a repeated
issue, an operational failure, or a measured accessibility/performance problem.
