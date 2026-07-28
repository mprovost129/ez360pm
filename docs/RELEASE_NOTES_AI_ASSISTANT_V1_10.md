# EZ360PM V1.10 - AI Controlled-Use Readiness

## Purpose

Turn the V1.9 evaluation framework into a clear, repeatable company launch gate
without adding scheduled drafts, autonomous sending, refunds, or money movement.

## Added

- Company-scoped AI readiness screen.
- Minimal, tool-free OpenAI Responses API connection test.
- Exact provider response contract and request-ID, token, cost, and latency audit.
- Required checks for platform configuration, company policy, model allowlist,
  usage allowance, contract evaluation, connection test, and full live baseline.
- Warnings for stale evaluations, recent assistant failures, high allowance use,
  and expired pending confirmations.
- `check_ai_readiness` deployment command with optional JSON output and nonzero
  exit status while required checks fail.
- Configurable evaluation freshness window.
- Company-isolation, exact-response, usage-audit, and endpoint regression tests.

## Migration

V1.10 adds a configuration fingerprint to evaluation runs so a passing result
from an older model/tool/provider contract cannot satisfy the current release.

```text
assistant.0006_aievaluationrun_configuration_fingerprint
```

## Commands

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant
python manage.py evaluate_ai_assistant
python manage.py evaluate_ai_assistant --live --user owner@example.com --suite all
python manage.py check_ai_readiness --user owner@example.com --output var/ai-readiness.json
python manage.py test
```

## Boundary retained

Scheduled drafts and reminders remain deferred. All existing confirmation rules
remain unchanged. The assistant still cannot issue refunds, alter paid invoices,
delete financial history, or move money.
