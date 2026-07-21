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
```

Set `PUBLIC_BASE_URL` to the public HTTPS origin with no trailing slash. Public
document links in email and Stripe redirects are built from this value.

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
