# EZ360PM V1.22 — Discoverable local client intake and route safety

## Purpose

V1.22 makes the zero-token client workflow easier to use and removes one
remaining deployment assumption from the assistant drawer. It adds no new AI
authority.

## Changes

### Discoverable zero-token client intake

- The assistant composer now includes a persistent **Client template** button.
- The button fills the structured `Create this client:` form without making an
  OpenAI request.
- The control is hidden when structured client/project writes are disabled by company policy.
- Existing unsent text is never overwritten without confirmation.
- The filled form remains editable and still requires the normal client preview
  and final confirmation before creating anything.
- `Ctrl+Enter` or `Command+Enter` submits the assistant form.

### One server-owned client template

- The exact client template is now defined once in `assistant.local_actions`.
- The local parser, focused OpenAI instructions, and drawer UI all use that same
  definition.
- This prevents label or field-order drift from silently breaking the zero-token
  route.
- The AI evaluation fingerprint now includes the exact template text.

### Route safety

- The assistant drawer now builds confirm and cancel URLs from Django's reversed
  Action Center URL supplied by the server.
- It no longer assumes that EZ360PM is mounted at `/assistant/`.
- This supports reverse proxies or future deployments under a path prefix.

### Cleanup

- Slow-request language now says EZ360PM is processing rather than incorrectly
  assuming every request called OpenAI.
- Removed a duplicate provider request-ID assignment in the assistant service.

## Deployment

No database migration is required.

```bash
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant.tests.test_phase22_local_client_discovery
python manage.py test assistant
python manage.py test
```
