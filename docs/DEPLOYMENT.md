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

Development and Render values are intentionally separated. Use `.env.example`
only for development and use `.env.render.example` as the Render Environment-page
checklist. See `docs/ENVIRONMENT.md` for the two-section handoff.

Set `PUBLIC_BASE_URL=https://www.ez360pm.com`. Public document links in email
and Stripe redirects are built from this canonical origin. The deployment check
fails if the value contains a path/query or its hostname is absent from
`ALLOWED_HOSTS`.

## Container and reverse-proxy requirements

The production image collects static assets with nonsecret build-only settings,
runs as the unprivileged `ez360pm` user, applies pending migrations before each
container start, writes Gunicorn logs to stdout/stderr, honors the platform's
`PORT` and `WEB_CONCURRENCY` values, and exposes a Docker health check against
`/health/`. If migration fails, Gunicorn does not start and the deployment is
not promoted to receive traffic. `EZ360PM_OWNER_PASSWORD` is strictly a one-time
bootstrap value and must not remain in the deployment environment afterward.

The Render service Start Command must be `sh ./bin/start.sh` (or left empty for
the Dockerfile `CMD`). Do not override it with a direct `gunicorn` command,
because that bypasses migrations and release checks. WSGI also verifies the
migration graph before serving traffic, so a future accidental override fails
the deployment instead of exposing pages backed by an older schema.

If production reports an undefined model column, stop testing that release and
run the following in the Render Shell against the web service environment:

```text
python manage.py showmigrations
python manage.py migrate --noinput
python manage.py deployment_check
```

Then set the Start Command correctly and redeploy. Never use `--fake` for this
recovery unless the database schema has been independently verified to match the
migration exactly.

`.dockerignore` excludes `.env`, repository metadata, local virtualenvs, logs,
media, test output, and other workstation files from the build context. Never
pass runtime secrets as Docker build arguments or copy `.env` into an image.

The application trusts `X-Forwarded-Proto: https` from the deployment proxy so
Django can identify secure requests before enforcing HTTPS redirects. Configure
the public load balancer to replace—not append an untrusted client value for—
that header, terminate TLS, and forward only to the private application service.

Company logos, client-form uploads, and project-activity attachments can use private Amazon S3 storage. Set `USE_S3_MEDIA=True` together
with `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_REGION_NAME`, `AWS_ACCESS_KEY_ID`, and
`AWS_SECRET_ACCESS_KEY`. Objects are stored below the `media/` prefix, retain
their original content type, and use one-hour signed URLs; keep S3 Block Public
Access enabled. The IAM principal needs `s3:ListBucket` on the bucket and
`s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on `media/*`.

When `USE_S3_MEDIA` is false, the default filesystem `MEDIA_ROOT` needs a
persistent volume at `/app/media` before company logos, client-form uploads, and project-activity attachments are treated as durable.
Static assets always remain on WhiteNoise and do not need that volume.

For a remote PostgreSQL service that requires TLS, set `DB_SSLMODE=require` (or
the stricter mode supplied by the provider). `DB_CONN_MAX_AGE` defaults to 60
seconds in production and Django validates a persistent connection before reuse.

## Email

Production uses the Resend HTTPS API for transactional email. Configure:

```text
EMAIL_PROVIDER=resend
EMAIL_BACKEND=core.email_backends.ResendEmailBackend
EMAIL_TIMEOUT=10
DEFAULT_FROM_EMAIL=Provost Home Design <notifications@verified-sending-domain>
DEFAULT_REPLY_TO_EMAIL=office@provosthomedesign.com
RESEND_API_KEY=re_...
RESEND_WEBHOOK_SECRET=whsec_...
```

Verify a dedicated sending subdomain in Resend and publish the exact SPF and DKIM
records Resend provides. Add DMARC deliberately after SPF/DKIM verify. Register
this webhook endpoint and subscribe to `email.sent`, `email.delivered`,
`email.delivery_delayed`, `email.failed`, `email.bounced`, `email.complained`,
and `email.suppressed`:

```text
https://www.ez360pm.com/webhooks/resend/
```

The webhook signing secret is endpoint-specific. Verification uses the raw body
and Resend's Svix signature headers; duplicate `svix-id` values are ignored and
older events cannot regress a newer delivery state. Never paste an API key or
webhook secret into Company settings or source control.

The root domain `ez360pm.com` redirects to `www`, but provider callbacks use the
canonical `www` URL directly so delivery does not depend on redirect behavior.
DNS uses the Render apex A record `216.24.57.1` and a `www` CNAME to
`ez360pm.onrender.com`; remove conflicting apex AAAA records.

The Render Basic service can use SMTP, but HTTPS remains the primary transport
for provider IDs and delivery events. During the cutover window, Gmail/Google
Workspace SMTP remains a manual rollback: set `EMAIL_PROVIDER=django`, set
`EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, and restore
`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, and `EMAIL_HOST_PASSWORD`. Never
run both providers for the same customer message.

The Company email is preferred as Reply-To; `DEFAULT_REPLY_TO_EMAIL` covers
framework and internal messages. Development retains `EMAIL_PROVIDER=django`
with the console backend. Every document, client-form, and internal notification
attempt creates a `DocumentDelivery` row before contacting the provider. API
acceptance, provider ID, delivery events, or a safe failure category are recorded
without storing credentials or rendered message bodies.

Before removing the Gmail application credential, send controlled proposal,
invoice, client-form, internal-notification, and password-reset messages; confirm
their Resend IDs appear in EZ360PM; replay one webhook; rotate the Resend API key;
and exercise the SMTP rollback once.

## Stripe Checkout

Set both values or leave both blank:

```text
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

Create the Stripe webhook endpoint at:

```text
https://www.ez360pm.com/webhooks/stripe/
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
if company logos, client-form uploads, or project-activity attachments are stored on the application filesystem.

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

## Optional AI isolation

With `AI_ASSISTANT_ENABLED=false`, authenticated page rendering, Company/User creation, and ordinary document-change signals do not query or create assistant policy, access, or draft-quality records. This lets ordinary EZ360PM workflows remain independent of the optional assistant. Even when the platform flag is enabled, company policy and selected-user access remain lazily provisioned. When enabling AI, run all assistant migrations before serving requests and review Company Settings → AI Settings.


### Optional AI environment parsing

The optional assistant must not make the core application unavailable because of a
malformed AI-only environment value. With `AI_ASSISTANT_ENABLED=false`, invalid AI
booleans, integers, decimals, or pricing JSON fall back to safe defaults during
settings import and appear as `assistant.W007` warnings in `check --deploy`.

With AI enabled, the same issues are `assistant.E028` errors and deployment should
stop until they are corrected. `AI_PROVIDER` must be `openai` (`assistant.E029`).
Always run `python manage.py check --deploy` after editing AI environment values.

## Gunicorn and AI request timeouts

EZ360PM resolves `GUNICORN_TIMEOUT_SECONDS` through its defensive settings parser and
passes the resolved value to Gunicorn. The recommended value with the AI assistant is:

```env
GUNICORN_TIMEOUT_SECONDS=180
AI_BROWSER_REQUEST_TIMEOUT_SECONDS=195
```

`AI_BROWSER_REQUEST_TIMEOUT_SECONDS` must remain longer than the Gunicorn timeout.
The assistant deployment check also confirms that the worker timeout can accommodate
the configured provider timeout and maximum tool rounds.

Deployment checks fail on errors by default while still printing warnings. To make
warnings block a deliberately strict deployment, set:

```env
DJANGO_DEPLOY_CHECK_FAIL_LEVEL=WARNING
```
