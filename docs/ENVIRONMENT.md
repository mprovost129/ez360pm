# Environment configuration

EZ360PM keeps development and Render production values in separate files so a
local default cannot be mistaken for a deployment secret. Never concatenate the
files: each section is a complete environment for its target.

## Section 1: Development

Use [`.env.example`](../.env.example) as the development template:

```powershell
Copy-Item .env.example .env
```

Generate a local `SECRET_KEY`, set the PostgreSQL credentials used by your local
database (or by `docker-compose.yml`), and optionally add an OpenAI development
key. AI starts disabled so a fresh checkout passes Django checks without a key.
After adding the key, set `AI_ASSISTANT_ENABLED=true` to use the configured
single-user company defaults.

## Section 2: Render production

Use [`.env.render.example`](../.env.render.example) as the checklist for the
Render web service Environment page. Replace every `replace-*` value and keep
all secrets in Render. The production AI section is enabled for one owner,
allows confirmed client communications, uses a $25 monthly guard, and prices
`gpt-5.6-terra` at the documented per-million-token rates.

Render supplies `PORT`; do not set it manually. `USE_S3_MEDIA=False` requires a
persistent disk mounted at `/app/media`. To use private S3 instead, set
`USE_S3_MEDIA=True` and fill all four AWS values.

After any Render environment change, redeploy and confirm these startup checks
pass:

```text
python manage.py check --deploy
python manage.py deployment_check
python manage.py data_audit
```

When AI is enabled, also run the in-app connection test and a current live
evaluation before relying on assistant writes.
