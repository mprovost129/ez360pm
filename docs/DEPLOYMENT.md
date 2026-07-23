# Deployment and Integration Setup

This is the operational handoff for the personal MVP. Secrets belong in the
deployment environment, never in source control or Django admin fields.

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

For production, set `DJANGO_SETTINGS_MODULE=config.Settings.prod`. The release
process in `Procfile` runs migrations, Django's deployment security checks, the
database/cache check, and the read-only data audit before the new web process is
promoted.

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
EMAIL_HOST_USER=<provider username>
EMAIL_HOST_PASSWORD=<provider credential>
DEFAULT_FROM_EMAIL=Provost Home Design <verified-sender@example.com>
```

The Company email is used as Reply-To. Development may retain the console email
backend. Every client-document or internal-acceptance attempt creates a
`DocumentDelivery` row before contacting the backend; success or a safe failure
category is then recorded without storing credentials or message bodies.

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

The installed Stripe Python SDK is `14.4.0`, pinned to API version
`2026-02-25.clover`. Configure the webhook endpoint to the same API version.
Checkout is shown only when both secrets are present and the issued invoice has
online payments enabled with a positive balance.

The server reloads and locks the invoice, calculates the current outstanding
balance, and creates the hosted Session. The webhook verifies Stripe's signature
against the raw request body and passes the resulting payment through the same
transactional service as manual payments. The unique Payment Intent ID makes
webhook replay idempotent.

After configuration, confirm the Integrations screen reports Email and Stripe as
configured. Use a Stripe test-mode invoice first, replay its successful webhook,
and verify that only one Stripe Payment row exists and the invoice balance is
zero.

## Monitoring and data audit

Monitor `GET /health/` for an HTTP 200 response and `{"status":"ok"}`. This
endpoint proves that Django and PostgreSQL can answer a request; it deliberately
does not expose internal diagnostics.

Run the read-only integrity audit after each release and on a daily schedule:

```powershell
.\.venv\Scripts\python.exe manage.py data_audit --json --fail-on-warning
```

The command checks stored line/document totals, payment-derived invoice status,
retainer-credit relationships, invoiced-time relationships, company boundaries,
and document deliveries left pending for more than 15 minutes. Use
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
